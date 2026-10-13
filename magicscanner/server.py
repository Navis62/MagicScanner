"""Serveur local : interface de scan (webcam dans le navigateur) + API de reconnaissance/inventaire."""
import base64
import threading

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, inventory
from .config import ROOT, SCANS_DIR
from .recognition.recognizer import Recognizer

STATIC = ROOT / "magicscanner" / "static"
app = FastAPI(title="MagicScanner")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_recognizer: Recognizer | None = None
_rec_lock = threading.Lock()


def recognizer() -> Recognizer:
    global _recognizer
    if _recognizer is None:
        with db.shared() as con:
            _recognizer = Recognizer(con)
    return _recognizer


@app.on_event("startup")
def _warmup() -> None:
    recognizer()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def _jpeg_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode() if ok else ""


@app.post("/api/scan")
async def scan(image: UploadFile = File(...)):
    data = np.frombuffer(await image.read(), np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(400, "image invalide")
    with _rec_lock, db.shared() as con:
        r = recognizer()
        rec = r.recognize(frame)
        out = {
            "ok": rec.ok, "error": rec.error, "lang": rec.lang, "confidence": rec.confidence,
            "title": rec.title, "ocr": rec.lines, "corners": rec.corners,
            "warped": _jpeg_b64(rec.warped) if rec.warped is not None else None,
        }
        if not rec.ok:
            return out
        best = rec.candidates[0]
        scan_id = inventory.add_scan(con, best["card_id"], rec.lang, rec.confidence, " | ".join(rec.lines))
        cv2.imwrite(str(SCANS_DIR / f"{scan_id}.jpg"), rec.warped)
        r.last_set = inventory.card_info(con, best["card_id"])["set_code"]
        out["scan_id"] = scan_id
        out["card"] = {**inventory.card_info(con, best["card_id"], rec.lang), **best}
        out["alternatives"] = [{**inventory.card_info(con, c["card_id"]), **c} for c in rec.candidates[1:12]]
        out["stats"] = inventory.stats(con)
        return out


class Reassign(BaseModel):
    card_id: str
    lang: str


@app.post("/api/manual")
def manual(body: Reassign):
    """Ajout manuel (après une recherche, quand la reconnaissance a échoué)."""
    with db.shared() as con:
        scan_id = inventory.add_scan(con, body.card_id, body.lang, 1.0, "manuel")
        return {"ok": True, "scan_id": scan_id, "card": inventory.card_info(con, body.card_id, body.lang),
                "stats": inventory.stats(con)}


@app.post("/api/scans/{scan_id}/undo")
def undo(scan_id: int):
    with db.shared() as con:
        if not inventory.undo_scan(con, scan_id):
            raise HTTPException(404, "scan introuvable ou déjà annulé")
        return {"ok": True, "stats": inventory.stats(con)}


@app.post("/api/scans/{scan_id}/reassign")
def reassign(scan_id: int, body: Reassign):
    with db.shared() as con:
        if not inventory.reassign_scan(con, scan_id, body.card_id, body.lang):
            raise HTTPException(404, "scan introuvable ou annulé")
        recognizer().last_set = inventory.card_info(con, body.card_id)["set_code"]
        return {"ok": True, "card": inventory.card_info(con, body.card_id, body.lang), "stats": inventory.stats(con)}


@app.get("/api/search")
def search(q: str):
    """Recherche manuelle (nom VO ou VF) quand la reconnaissance échoue."""
    with db.shared() as con:
        r = recognizer()
        matches = r._match_name([q])[:3]
        if not matches:
            return {"results": []}
        rows = r._printings([m[0] for m in matches])
        rows = sorted(rows, key=lambda p: p["released_at"] or "", reverse=True)
        return {"lang": matches[0][1], "results": [inventory.card_info(con, p["id"]) for p in rows[:40]]}


@app.get("/api/stats")
def get_stats():
    with db.shared() as con:
        return inventory.stats(con)


@app.get("/api/recent")
def recent(limit: int = 30):
    with db.shared() as con:
        rows = con.execute("SELECT * FROM scans WHERE undone=0 ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"scan_id": s["id"], "lang": s["lang"], **inventory.card_info(con, s["card_id"], s["lang"])} for s in rows]
