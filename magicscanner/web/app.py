"""Serveur local : interface de scan (webcam dans le navigateur) + API de reconnaissance et d'inventaire."""
import base64
import logging
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import cv2
import httpx
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import db, inventory, powertools
from ..catalog import Catalog, cardmarket
from ..config import (
    DEFAULT_PRICE,
    KEEP_SCANS,
    LOW_CONFIDENCE,
    MIN_PRICE,
    SCANS_DIR,
    ensure_dirs,
)
from ..recognition import Candidate, Recognizer, detect
from ..recognition.recognizer import NAME_SURE

STATIC = Path(__file__).parent / "static"
Image = Annotated[UploadFile, File()]
MAX_ALTERNATIVES = 11


@dataclass
class Services:
    con: sqlite3.Connection
    catalog: Catalog
    recognizer: Recognizer
    lock: threading.Lock          # une seule connexion SQLite partagée entre les threads du serveur
    previous_set: str | None = None  # édition du dernier scan (les piles sont souvent triées)


svc: Services
log = logging.getLogger(__name__)

PRICES_MAX_AGE_HOURS = 6   # guide Cardmarket publié chaque nuit : inutile de le retélécharger à chaque redémarrage


def _refresh_prices() -> str | None:
    """Télécharge le guide hors du verrou (quelques secondes) : les scans continuent pendant ce temps."""
    t = time.perf_counter()
    guide = cardmarket.download_prices()
    downloaded = time.perf_counter()
    with svc.lock:
        created = cardmarket.store_prices(svc.con, guide)
    log.info("prix tendance : téléchargés en %.1f s, enregistrés en %.1f s (scans bloqués pendant ce temps)",
             downloaded - t, time.perf_counter() - downloaded)
    return created


def _refresh_prices_at_startup() -> None:
    age = cardmarket.prices_age_hours()
    if age is not None and age < PRICES_MAX_AGE_HOURS:
        log.info("prix tendance téléchargés il y a %.1f h : pas de mise à jour", age)
        return
    try:
        log.info("prix tendance à jour (guide Cardmarket du %s)", _refresh_prices())
    except (httpx.HTTPError, ValueError, KeyError) as e:   # hors ligne, guide illisible : on garde les prix en base
        log.warning("prix tendance non mis à jour au démarrage : %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global svc
    ensure_dirs()
    con = db.connect()
    catalog = Catalog(con)
    svc = Services(con, catalog, Recognizer(catalog), threading.Lock())
    threading.Thread(target=_refresh_prices_at_startup, name="prices", daemon=True).start()
    yield
    con.close()


app = FastAPI(title="MagicScanner", lifespan=lifespan)


class FreshStaticFiles(StaticFiles):
    """Le navigateur revalide les fichiers à chaque chargement : une mise à jour du JS/CSS est vue sans vider le cache."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", FreshStaticFiles(directory=STATIC), name="static")


class CardChoice(BaseModel):
    card_id: str
    lang: str
    foil: bool | None = None   # None : finition inchangée (correction) ou non-foil (ajout manuel)
    price: float | None = Field(None, ge=MIN_PRICE)   # None : prix inchangé (correction) ou prix par défaut


# --- Helpers ------------------------------------------------------------------------------------------------

def _card(card_id: str, lang: str | None = None, candidate: Candidate | None = None, foil: bool = False,
          price: float = DEFAULT_PRICE) -> dict:
    """Fiche pour l'UI : référentiel + stock (quantité) (+ détail du score si candidate)."""
    info = svc.catalog.card_info(card_id, lang, foil)
    info["foil"], info["price"] = foil, price
    info["quantity"] = inventory.quantity(svc.con, card_id, lang, foil, price) if lang else 0
    if candidate:
        info.update(asdict(candidate))
    return info


def _review_reason(rec) -> str | None:
    if rec.off_set:
        return "hors de l'édition fixée"
    if rec.name_score < NAME_SURE:
        return "nom mal lu, carte approchante"
    if rec.confidence < LOW_CONFIDENCE:
        return "confiance faible"
    if rec.ambiguous:
        return "plusieurs extensions Cardmarket possibles"
    return None


FRAMES_KEPT = 20


def _keep_frame(frame: np.ndarray, kind: str) -> None:
    """Garde les dernières images reçues dans data/scans/<kind>/ pour comprendre ce qui s'est passé : « failed » (scan
    raté), « slow » (carte retrouvée par son texte, faute de bord : le secours lent)."""
    folder = SCANS_DIR / kind
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / f"{time.strftime('%Y%m%d-%H%M%S')}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    for old in sorted(folder.glob("*.jpg"))[:-FRAMES_KEPT]:
        old.unlink()


def _jpeg_data_url(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode() if ok else ""


async def _decode(image: UploadFile) -> np.ndarray:
    frame = cv2.imdecode(np.frombuffer(await image.read(), np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(400, "image invalide")
    if frame.max() < 8:
        raise HTTPException(400, "image noire : la caméra ne renvoie rien (relance la caméra)")
    return frame


MIN_CROP_PX = 200   # zone recadrée plus petite que ça : on garde l'image entière


def _crop(frame: np.ndarray, value: str) -> tuple[np.ndarray, tuple[int, int]]:
    """Zone à analyser envoyée par l'interface (« x0,y0,x1,y1 » en fractions de l'image : ce que montre l'aperçu
    zoomé, plus une marge) et décalage de son coin haut-gauche. Valeur absente ou invalide : l'image entière."""
    try:
        x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in value.split(","))
    except ValueError:
        return frame, (0, 0)
    h, w = frame.shape[:2]
    left, top, right, bottom = round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)
    if right - left < MIN_CROP_PX or bottom - top < MIN_CROP_PX:
        return frame, (0, 0)
    return frame[top:bottom, left:right], (left, top)


def _orientation(value: str) -> str | None:
    """Sens de la carte envoyé par l'interface ; toute autre valeur : inconnu (les deux sens sont cherchés)."""
    return value if value in ("portrait", "landscape") else None


# --- Routes -------------------------------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/scan")
async def scan(image: Image, foil: bool = Form(False),
               price: float = Form(DEFAULT_PRICE, ge=MIN_PRICE), locked_set: str = Form(""),
               orientation: str = Form(""), crop: str = Form("")):
    """Reconnaît la carte et l'ajoute immédiatement au stock (annulable). `locked_set` : édition fixée (paquet d'une
    seule édition), vide pour toutes. `crop` : zone de l'image à analyser (aperçu zoomé), vide pour l'image entière."""
    start = time.perf_counter()
    whole = await _decode(image)
    frame, (dx, dy) = _crop(whole, crop)
    decoded = time.perf_counter()
    with svc.lock:
        locked = time.perf_counter()
        rec = svc.recognizer.recognize(frame, previous_set=svc.previous_set, foil=foil, locked_set=locked_set or None,
                                     orientation=_orientation(orientation))
        recognized = time.perf_counter()
        out = _scan_result(frame, rec, (dx, dy), foil, price)
    steps = {"décodage": decoded - start, "attente": locked - decoded, **rec.timings,
             "après": time.perf_counter() - recognized}
    _log_scan(frame, rec, orientation, frame is not whole, steps, time.perf_counter() - start)
    return out


def _log_scan(frame: np.ndarray, rec, orientation: str, zoomed: bool, steps: dict[str, float], total: float) -> None:
    """Une ligne par scan dans la console : où part le temps (attente du verrou, contours, OCR, localisation par le
    texte, comparaison des impressions) et la taille de l'image analysée, pour comprendre un scan lent."""
    h, w = frame.shape[:2]
    detail = ", ".join(f"{step} {seconds:.2f}" for step, seconds in steps.items())
    log.info("scan %.2f s (%s) — %d×%d %s%s — %s", total, detail, w, h, orientation or "?",
             " zoomé" if zoomed else "", f"lu « {rec.title} »" if rec.ok else rec.error)


def _scan_result(frame: np.ndarray, rec, offset: tuple[int, int], foil: bool, price: float) -> dict:
    """Réponse de /api/scan, sous le verrou : un scan réussi est ajouté au stock, l'image d'un scan raté est gardée."""
    dx, dy = offset
    corners = [[x + dx, y + dy] for x, y in rec.corners] if rec.corners else None   # repère de l'image entière
    out = {
        "ok": rec.ok, "error": rec.error, "lang": rec.lang, "confidence": rec.confidence,
        "title": rec.title, "ocr": rec.lines, "corners": corners, "list_symbol": rec.list_symbol,
        "warped": _jpeg_data_url(rec.warped) if rec.warped is not None else None,
    }
    if not rec.ok:
        _keep_frame(frame, "failed")
        return out
    if "texte" in rec.timings:
        _keep_frame(frame, "slow")
    best = rec.best
    scan_id = inventory.add_scan(svc.con, best.card_id, rec.lang, rec.confidence, " | ".join(rec.lines),
                                 foil, price)
    if KEEP_SCANS == "all" or (KEEP_SCANS == "low" and rec.confidence < LOW_CONFIDENCE):
        cv2.imwrite(str(SCANS_DIR / f"{scan_id}.jpg"), rec.warped, [cv2.IMWRITE_JPEG_QUALITY, 70])
    card = _card(best.card_id, rec.lang, best, foil, price)
    svc.previous_set = card["set_code"]
    return out | {
        "scan_id": scan_id,
        "needs_review": _review_reason(rec) is not None,
        "review_reason": _review_reason(rec),
        "card": card,
        "alternatives": [_card(c.card_id, candidate=c) for c in rec.candidates[1:1 + MAX_ALTERNATIVES]],
        "stats": inventory.stats(svc.con),
    }


@app.post("/api/detect")
async def detect_card(image: Image, orientation: str = Form("")):
    """Localise la carte sans la reconnaître ni l'ajouter (cadrage de l'aperçu)."""
    corners = detect.find_card(await _decode(image), _orientation(orientation))
    return {"corners": corners.tolist() if corners is not None else None}


@app.post("/api/manual")
def add_manual(body: CardChoice):
    """Ajout manuel (après une recherche, quand la reconnaissance a échoué)."""
    with svc.lock:
        foil, price = bool(body.foil), body.price or DEFAULT_PRICE
        scan_id = inventory.add_scan(svc.con, body.card_id, body.lang, 1.0, "manuel", foil, price)
        card = _card(body.card_id, body.lang, foil=foil, price=price)
        return {"ok": True, "scan_id": scan_id, "card": card, "stats": inventory.stats(svc.con)}


@app.post("/api/undo")
def undo_last():
    """Annule le dernier scan encore actif : appelé plusieurs fois, remonte scan après scan."""
    with svc.lock:
        last = inventory.recent_scans(svc.con, 1)
        if not last:
            raise HTTPException(404, "Aucun scan à annuler")
        scan = last[0]
        inventory.undo_scan(svc.con, scan["id"])
        card = _card(scan["card_id"], scan["lang"], foil=bool(scan["foil"]), price=scan["price"])
        return {"ok": True, "card": card, "lang": scan["lang"], "stats": inventory.stats(svc.con)}


@app.post("/api/scans/{scan_id}/reassign")
def reassign(scan_id: int, body: CardChoice):
    with svc.lock:
        if not inventory.reassign_scan(svc.con, scan_id, body.card_id, body.lang, body.foil, body.price):
            raise HTTPException(404, "scan introuvable ou annulé")
        line = inventory.scan_line(svc.con, scan_id)
        card = _card(body.card_id, body.lang, foil=bool(line["foil"]), price=line["price"])
        svc.previous_set = card["set_code"]
        return {"ok": True, "card": card, "stats": inventory.stats(svc.con)}


@app.get("/api/search")
def search(q: str, locked_set: str = ""):
    """Recherche manuelle par nom (VO ou VF) ; les impressions de l'édition fixée viennent en tête."""
    with svc.lock:
        lang, card_ids = svc.catalog.search(q, set_code=locked_set or None)
        return {"lang": lang, "results": [_card(cid) for cid in card_ids]}


@app.get("/api/sets")
def sets():
    """Éditions proposées pour fixer l'édition du paquet scanné."""
    with svc.lock:
        return svc.catalog.sets()


@app.get("/api/stats")
def stats():
    with svc.lock:
        return inventory.stats(svc.con)


@app.get("/api/recent")
def recent(limit: int = 30):
    with svc.lock:
        return [{"scan_id": s["id"], "lang": s["lang"], **_card(s["card_id"], s["lang"], foil=bool(s["foil"]), price=s["price"])}
                for s in inventory.recent_scans(svc.con, limit)]


# --- Prix tendance --------------------------------------------------------------------------------------------

@app.post("/api/prices/refresh")
def refresh_prices():
    """Retélécharge le guide des prix Cardmarket (prix tendance, y compris foil)."""
    try:
        created = _refresh_prices()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Téléchargement impossible : {e}") from None
    return {"created_at": created}


# --- Export TCG Powertools -----------------------------------------------------------------------------------

@app.get("/api/export")
def export_powertools(everything: bool = False):
    """CSV d'import TCG Powertools des cartes pas encore exportées (tout le stock avec `everything`)."""
    with svc.lock:
        content, lines, skipped = powertools.build(svc.con, everything)
    if not lines:
        if skipped:
            raise HTTPException(400, f"Rien à exporter : {skipped} carte(s) sans identifiant Cardmarket "
                                     "(mets à jour les données Cardmarket).")
        raise HTTPException(400, "Rien à exporter : toutes les cartes ont déjà été exportées.")
    return Response(content, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="powertools-import.csv"',
        "X-Export-Lines": str(lines), "X-Export-Skipped": str(skipped),
        "Access-Control-Expose-Headers": "X-Export-Lines, X-Export-Skipped",
    })

