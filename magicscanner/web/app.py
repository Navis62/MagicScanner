"""Serveur local : interface de scan (webcam dans le navigateur) + API de reconnaissance et d'inventaire."""
import base64
import sqlite3
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import db, inventory
from ..catalog import Catalog
from ..config import SCANS_DIR, ensure_dirs
from ..recognition import Candidate, Recognizer, detect

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
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class CardChoice(BaseModel):
    card_id: str
    lang: str


# --- Helpers ------------------------------------------------------------------------------------------------

def _card(card_id: str, lang: str | None = None, candidate: Candidate | None = None) -> dict:
    """Fiche pour l'UI : référentiel + quantité en stock (+ détail du score si candidate)."""
    info = svc.catalog.card_info(card_id, lang)
    info["quantity"] = inventory.quantity(svc.con, card_id, lang) if lang else 0
    if candidate:
        info.update(asdict(candidate))
    return info


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
async def scan(image: UploadFile = File(...)):
    """Reconnaît la carte et l'ajoute immédiatement au stock (annulable)."""
    frame = await _decode(image)
    with svc.lock:
        rec = svc.recognizer.recognize(frame, previous_set=svc.previous_set)
        out = {
            "ok": rec.ok, "error": rec.error, "lang": rec.lang, "confidence": rec.confidence,
            "title": rec.title, "ocr": rec.lines, "corners": rec.corners,
            "warped": _jpeg_data_url(rec.warped) if rec.warped is not None else None,
        }
        if not rec.ok:
            return out
        best = rec.best
        scan_id = inventory.add_scan(svc.con, best.card_id, rec.lang, rec.confidence, " | ".join(rec.lines))
        cv2.imwrite(str(SCANS_DIR / f"{scan_id}.jpg"), rec.warped)
        card = _card(best.card_id, rec.lang, best)
        svc.previous_set = card["set_code"]
        return out | {
            "scan_id": scan_id,
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
        scan_id = inventory.add_scan(svc.con, body.card_id, body.lang, 1.0, "manuel")
        return {"ok": True, "scan_id": scan_id, "card": _card(body.card_id, body.lang), "stats": inventory.stats(svc.con)}


@app.post("/api/scans/{scan_id}/undo")
def undo(scan_id: int):
    with svc.lock:
        if not inventory.undo_scan(svc.con, scan_id):
            raise HTTPException(404, "scan introuvable ou déjà annulé")
        return {"ok": True, "stats": inventory.stats(svc.con)}


@app.post("/api/scans/{scan_id}/reassign")
def reassign(scan_id: int, body: CardChoice):
    with svc.lock:
        if not inventory.reassign_scan(svc.con, scan_id, body.card_id, body.lang):
            raise HTTPException(404, "scan introuvable ou annulé")
        card = _card(body.card_id, body.lang)
        svc.previous_set = card["set_code"]
        return {"ok": True, "card": card, "stats": inventory.stats(svc.con)}


@app.get("/api/search")
def search(q: str):
    """Recherche manuelle par nom (VO ou VF)."""
    with svc.lock:
        lang, card_ids = svc.catalog.search(q)
        return {"lang": lang, "results": [_card(cid) for cid in card_ids]}


@app.get("/api/stats")
def stats():
    with svc.lock:
        return inventory.stats(svc.con)


@app.get("/api/recent")
def recent(limit: int = 30):
    with svc.lock:
        return [{"scan_id": s["id"], "lang": s["lang"], **_card(s["card_id"], s["lang"])}
                for s in inventory.recent_scans(svc.con, limit)]
