"""Inventaire : une ligne par (impression, langue, état, prix, finition) avec une quantité.

Chaque scan incrémente la ligne correspondante et reste traçable (table scans) pour pouvoir être annulé
ou réaffecté. Les lignes ne sont jamais supprimées (les scans y font référence) : quantité 0 = vide.
"""
import sqlite3

from .config import DEFAULT_CONDITION, DEFAULT_PRICE


def _line_id(con: sqlite3.Connection, card_id: str, lang: str, foil: bool = False, price: float = DEFAULT_PRICE) -> int:
    """Ligne d'inventaire de (carte, langue, finition, prix) à l'état par défaut, créée si besoin."""
    key = (card_id, lang, DEFAULT_CONDITION, round(price, 2), int(foil))
    con.execute(
        """INSERT INTO inventory (card_id, lang, condition, price, foil) VALUES (?,?,?,?,?)
           ON CONFLICT(card_id, lang, condition, price, foil) DO NOTHING""",
        key,
    )
    return con.execute(
        "SELECT id FROM inventory WHERE card_id=? AND lang=? AND condition=? AND price=? AND foil=?", key
    ).fetchone()["id"]


def _add(con: sqlite3.Connection, line_id: int, delta: int) -> None:
    con.execute("UPDATE inventory SET quantity = quantity + ?, updated_at = CURRENT_TIMESTAMP WHERE id=?", (delta, line_id))


def _active_scan(con: sqlite3.Connection, scan_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM scans WHERE id=? AND undone=0", (scan_id,)).fetchone()


def add_scan(con: sqlite3.Connection, card_id: str, lang: str, confidence: float, ocr_text: str,
             foil: bool = False, price: float = DEFAULT_PRICE) -> int:
    line_id = _line_id(con, card_id, lang, foil, price)
    _add(con, line_id, 1)
    cur = con.execute(
        "INSERT INTO scans (inventory_id, card_id, lang, confidence, ocr_text) VALUES (?,?,?,?,?)",
        (line_id, card_id, lang, confidence, ocr_text),
    )
    con.commit()
    return cur.lastrowid


def undo_scan(con: sqlite3.Connection, scan_id: int) -> bool:
    scan = _active_scan(con, scan_id)
    if scan is None:
        return False
    _add(con, scan["inventory_id"], -1)
    con.execute("UPDATE scans SET undone=1 WHERE id=?", (scan_id,))
    con.commit()
    return True


def reassign_scan(con: sqlite3.Connection, scan_id: int, card_id: str, lang: str, foil: bool | None = None,
                  price: float | None = None) -> bool:
    """Correction : déplace le scan vers une autre impression, langue, finition et/ou prix (None = inchangé)."""
    scan = _active_scan(con, scan_id)
    if scan is None:
        return False
    _add(con, scan["inventory_id"], -1)
    old = con.execute("SELECT foil, price FROM inventory WHERE id=?", (scan["inventory_id"],)).fetchone()
    line_id = _line_id(con, card_id, lang, bool(old["foil"]) if foil is None else foil,
                       old["price"] if price is None else price)
    _add(con, line_id, 1)
    con.execute("UPDATE scans SET inventory_id=?, card_id=?, lang=? WHERE id=?", (line_id, card_id, lang, scan_id))
    con.commit()
    return True


def quantity(con: sqlite3.Connection, card_id: str, lang: str, foil: bool = False,
             price: float = DEFAULT_PRICE) -> int:
    """Exemplaires en stock de cette carte dans cette langue, finition et ce prix."""
    row = con.execute(
        "SELECT quantity FROM inventory WHERE card_id=? AND lang=? AND condition=? AND price=? AND foil=?",
        (card_id, lang, DEFAULT_CONDITION, round(price, 2), int(foil)),
    ).fetchone()
    return row["quantity"] if row else 0


def scan_line(con: sqlite3.Connection, scan_id: int) -> sqlite3.Row:
    """Finition et prix de la ligne où est rangé le scan."""
    return con.execute("SELECT i.foil, i.price FROM scans s JOIN inventory i ON i.id = s.inventory_id WHERE s.id=?",
                       (scan_id,)).fetchone()


def recent_scans(con: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT s.*, i.foil, i.price FROM scans s JOIN inventory i ON i.id = s.inventory_id
           WHERE s.undone=0 ORDER BY s.id DESC LIMIT ?""", (limit,)).fetchall()


def stats(con: sqlite3.Connection) -> dict:
    row = con.execute(
        """SELECT COALESCE(SUM(quantity), 0) AS cards,
                  COUNT(CASE WHEN quantity > 0 THEN 1 END) AS lines,
                  COALESCE(SUM(MAX(quantity - exported_quantity, 0)), 0) AS to_export,
                  COALESCE(SUM(quantity * price), 0) AS value
           FROM inventory"""
    ).fetchone()
    today = con.execute("SELECT COUNT(*) FROM scans WHERE undone=0 AND date(created_at) = date('now')").fetchone()[0]
    return {**dict(row), "today": today, "default_price": DEFAULT_PRICE}


def export_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT i.*, c.name, c.set_code, c.collector_number, c.cardmarket_id, s.name AS set_name
           FROM inventory i JOIN cards c ON c.id = i.card_id JOIN sets s ON s.code = c.set_code
           WHERE i.quantity > 0 ORDER BY s.name, c.name"""
    ).fetchall()


def powertools_rows(con: sqlite3.Connection, everything: bool = False) -> list[sqlite3.Row]:
    """Lignes à importer dans TCG Powertools : la quantité pas encore exportée de chaque ligne (tout le stock si
    `everything`). `missing_id` = carte sans identifiant Cardmarket, que l'import ne saurait pas rattacher."""
    already = "0" if everything else "i.exported_quantity"
    return con.execute(
        f"""SELECT i.id AS line_id, i.quantity - {already} AS amount, i.lang, i.condition, i.price, i.foil,
                   c.name, c.cardmarket_id, s.code AS set_code, s.name AS set_name
            FROM inventory i JOIN cards c ON c.id = i.card_id JOIN sets s ON s.code = c.set_code
            WHERE i.quantity > {already} ORDER BY s.name, c.name"""
    ).fetchall()


def mark_exported(con: sqlite3.Connection, line_ids: list[int]) -> None:
    """Les lignes données sont entièrement exportées (leur stock actuel ne sera plus proposé)."""
    con.executemany("UPDATE inventory SET exported_quantity = quantity WHERE id=?", [(i,) for i in line_ids])
    con.commit()
