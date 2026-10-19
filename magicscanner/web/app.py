"""Serveur local : interface de scan (webcam dans le navigateur) + API de reconnaissance et d'inventaire."""
import base64
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

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
from .publisher import PublishJob

STATIC = Path(__file__).parent / "static"
MAX_ALTERNATIVES = 11


@dataclass
class Services:
    con: sqlite3.Connection
    catalog: Catalog
    recognizer: Recognizer
    lock: threading.Lock          # une seule connexion SQLite partagée entre les threads du serveur
    previous_set: str | None = None  # édition du dernier scan (les piles sont souvent triées)


svc: Services
publisher = PublishJob()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global svc
    ensure_dirs()
    con = db.connect()
    catalog = Catalog(con)
    svc = Services(con, catalog, Recognizer(catalog), threading.Lock())
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


class PublishRequest(BaseModel):
    limit: int | None = None   # n'en publier que quelques-unes (premiers essais)
    dry_run: bool = False      # remplit les formulaires sans rien publier


# --- Helpers ------------------------------------------------------------------------------------------------

def _card(card_id: str, lang: str | None = None, candidate: Candidate | None = None, foil: bool = False,
          price: float = DEFAULT_PRICE) -> dict:
    """Fiche pour l'UI : référentiel + stock (quantité, dont déjà publiées) (+ détail du score si candidate)."""
    info = svc.catalog.card_info(card_id, lang, foil)
    info["foil"], info["price"] = foil, price
    info["quantity"], info["listed"] = inventory.quantity(svc.con, card_id, lang, foil, price) if lang else (0, 0)
    if candidate:
        info.update(asdict(candidate))
    return info


def _review_reason(rec) -> str | None:
    if rec.off_set:
        return "hors de l'édition fixée"
    if rec.confidence < LOW_CONFIDENCE:
        return "confiance faible"
    if rec.ambiguous:
        return "plusieurs extensions Cardmarket possibles"
    return None


FAILED_KEPT = 20


def _keep_failed_frame(frame: np.ndarray) -> None:
    """Garde les dernières images des scans ratés (data/scans/failed/) pour comprendre ce qui s'est passé."""
    folder = SCANS_DIR / "failed"
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / f"{time.strftime('%Y%m%d-%H%M%S')}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    for old in sorted(folder.glob("*.jpg"))[:-FAILED_KEPT]:
        old.unlink()


def _jpeg_data_url(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode() if ok else ""


async def _decode(image: UploadFile) -> np.ndarray:
    frame = cv2.imdecode(np.frombuffer(await image.read(), np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(400, "image invalide")
    return frame


# --- Routes -------------------------------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/scan")
async def scan(image: UploadFile = File(...), foil: bool = Form(False),
               price: float = Form(DEFAULT_PRICE, ge=MIN_PRICE), locked_set: str = Form("")):
    """Reconnaît la carte et l'ajoute immédiatement au stock (annulable). `locked_set` : édition fixée (paquet d'une
    seule édition), vide pour toutes."""
    frame = await _decode(image)
    with svc.lock:
        rec = svc.recognizer.recognize(frame, previous_set=svc.previous_set, foil=foil, locked_set=locked_set or None)
        out = {
            "ok": rec.ok, "error": rec.error, "lang": rec.lang, "confidence": rec.confidence,
            "title": rec.title, "ocr": rec.lines, "corners": rec.corners, "list_symbol": rec.list_symbol,
            "warped": _jpeg_data_url(rec.warped) if rec.warped is not None else None,
        }
        if not rec.ok:
            _keep_failed_frame(frame)
            return out
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
async def detect_card(image: UploadFile = File(...)):
    """Localise la carte sans la reconnaître ni l'ajouter (cadrage de l'aperçu)."""
    corners = detect.find_card(await _decode(image))
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
        try:
            inventory.undo_scan(svc.con, scan["id"])
        except inventory.AlreadyListed as e:
            raise HTTPException(409, str(e)) from None
        card = _card(scan["card_id"], scan["lang"], foil=bool(scan["foil"]), price=scan["price"])
        return {"ok": True, "card": card, "lang": scan["lang"], "stats": inventory.stats(svc.con)}


@app.post("/api/scans/{scan_id}/reassign")
def reassign(scan_id: int, body: CardChoice):
    with svc.lock:
        try:
            moved = inventory.reassign_scan(svc.con, scan_id, body.card_id, body.lang, body.foil, body.price)
        except inventory.AlreadyListed as e:
            raise HTTPException(409, str(e)) from None
        if not moved:
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
        with svc.lock:
            created = cardmarket.import_prices(svc.con)
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
        raise HTTPException(400, "Rien à exporter : toutes les cartes ont déjà été exportées.")
    return Response(content, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": 'attachment; filename="powertools-import.csv"',
        "X-Export-Lines": str(lines), "X-Export-Skipped": str(skipped),
        "Access-Control-Expose-Headers": "X-Export-Lines, X-Export-Skipped",
    })


# --- Publication Cardmarket ----------------------------------------------------------------------------------

@app.get("/api/publish")
def publish_status():
    return publisher.snapshot()


@app.post("/api/publish")
def publish(body: PublishRequest | None = None):
    """Met en vente sur Cardmarket les exemplaires pas encore publiés (la différence stock - publiées)."""
    body = body or PublishRequest()
    with svc.lock:
        if inventory.stats(svc.con)["to_list"] == 0:
            raise HTTPException(400, "Rien à publier : tout le stock est déjà en vente.")
    if not publisher.start(submit=not body.dry_run, limit=body.limit):
        raise HTTPException(409, "Une publication est déjà en cours.")
    return publisher.snapshot()


@app.post("/api/publish/reset")
def publish_reset():
    """Remet le compteur « à publier » à zéro : tout le stock est considéré comme déjà en vente."""
    if publisher.snapshot()["state"] == "running":
        raise HTTPException(409, "Une publication est en cours.")
    with svc.lock:
        marked = inventory.mark_all_listed(svc.con)
        return {"marked": marked, "stats": inventory.stats(svc.con)}


@app.post("/api/publish/stop")
def publish_stop():
    publisher.stop()
    return publisher.snapshot()
