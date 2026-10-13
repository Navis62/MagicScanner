"""Inventaire : chaque scan incrémente la quantité de (impression, langue, état, prix) ; annulable."""
import sqlite3

from . import cardmarket
from .config import DEFAULT_CONDITION, DEFAULT_PRICE, PRICE_ALERT


def _upsert(con: sqlite3.Connection, card_id: str, lang: str, delta: int) -> int:
    con.execute(
        """INSERT INTO inventory (card_id, lang, condition, price, quantity) VALUES (?,?,?,?,?)
           ON CONFLICT(card_id, lang, condition, price)
           DO UPDATE SET quantity = quantity + excluded.quantity, updated_at = CURRENT_TIMESTAMP""",
        (card_id, lang, DEFAULT_CONDITION, DEFAULT_PRICE, delta),
    )
    return con.execute(
        "SELECT id FROM inventory WHERE card_id=? AND lang=? AND condition=? AND price=?",
        (card_id, lang, DEFAULT_CONDITION, DEFAULT_PRICE),
    ).fetchone()["id"]


def add_scan(con: sqlite3.Connection, card_id: str, lang: str, confidence: float, ocr_text: str) -> int:
    inv_id = _upsert(con, card_id, lang, 1)
    cur = con.execute(
        "INSERT INTO scans (inventory_id, card_id, lang, confidence, ocr_text) VALUES (?,?,?,?,?)",
        (inv_id, card_id, lang, confidence, ocr_text),
    )
    con.commit()
    return cur.lastrowid


def undo_scan(con: sqlite3.Connection, scan_id: int) -> bool:
    scan = con.execute("SELECT * FROM scans WHERE id=? AND undone=0", (scan_id,)).fetchone()
    if scan is None:
        return False
    con.execute("UPDATE inventory SET quantity = quantity - 1, updated_at = CURRENT_TIMESTAMP WHERE id=?", (scan["inventory_id"],))
    con.execute("UPDATE scans SET undone=1 WHERE id=?", (scan_id,))
    con.commit()
    return True


def reassign_scan(con: sqlite3.Connection, scan_id: int, card_id: str, lang: str) -> bool:
    """Correction manuelle : déplace le scan vers une autre impression et/ou langue."""
    scan = con.execute("SELECT * FROM scans WHERE id=? AND undone=0", (scan_id,)).fetchone()
    if scan is None:
        return False
    con.execute("UPDATE inventory SET quantity = quantity - 1 WHERE id=?", (scan["inventory_id"],))
    inv_id = _upsert(con, card_id, lang, 1)
    con.execute("UPDATE scans SET inventory_id=?, card_id=?, lang=? WHERE id=?", (inv_id, card_id, lang, scan_id))
    con.commit()
    return True


def card_info(con: sqlite3.Connection, card_id: str, lang: str | None = None) -> dict:
    c = con.execute(
        """SELECT c.*, s.name AS set_name, s.icon_svg, s.released_at AS set_date,
                  l.printed_name AS fr_name, l.image_normal AS fr_image,
                  pr.trend, pr.low, pr.avg
           FROM cards c JOIN sets s ON s.code = c.set_code
           LEFT JOIN localized l ON l.set_code = c.set_code AND l.collector_number = c.collector_number AND l.lang='fr'
           LEFT JOIN cm_prices pr ON pr.id_product = c.cardmarket_id
           WHERE c.id=?""",
        (card_id,),
    ).fetchone()
    fr_name = c["fr_name"]
    if not fr_name:  # pas de fiche FR pour cette édition : nom VF connu via une autre édition
        r = con.execute("SELECT name FROM names WHERE oracle_id=? AND lang='fr' LIMIT 1", (c["oracle_id"],)).fetchone()
        fr_name = r["name"] if r else None
    image = c["fr_image"] if lang == "fr" and c["fr_image"] else c["image_normal"]
    qty = 0
    if lang:
        r = con.execute("SELECT quantity FROM inventory WHERE card_id=? AND lang=? AND condition=? AND price=?",
                        (card_id, lang, DEFAULT_CONDITION, DEFAULT_PRICE)).fetchone()
        qty = r["quantity"] if r else 0
    return {
        "card_id": card_id,
        "name": c["name"],
        "fr_name": fr_name,
        "set_code": c["set_code"],
        "set_name": c["set_name"],
        "set_icon": c["icon_svg"],
        "set_date": c["set_date"],
        "collector_number": c["collector_number"],
        "rarity": c["rarity"],
        "image": image,
        "image_small": c["image_small"],
        "has_fr_scan": bool(c["fr_image"]),
        "cardmarket_url": cardmarket.product_url(con, card_id),
        "cardmarket_id": c["cardmarket_id"],
        "trend": c["trend"],
        "price_alert": bool(c["trend"] and c["trend"] >= PRICE_ALERT),
        "quantity": qty,
    }


def stats(con: sqlite3.Connection) -> dict:
    r = con.execute(
        """SELECT COALESCE(SUM(quantity),0) AS cards, COUNT(CASE WHEN quantity > 0 THEN 1 END) AS lines,
                  COALESCE(SUM(MAX(quantity - listed_quantity, 0)),0) AS to_list,
                  COALESCE(SUM(listed_quantity),0) AS listed,
                  COALESCE(SUM(quantity * price),0) AS value
           FROM inventory"""
    ).fetchone()
    today = con.execute("SELECT COUNT(*) FROM scans WHERE undone=0 AND date(created_at)=date('now')").fetchone()[0]
    return {**dict(r), "today": today}
