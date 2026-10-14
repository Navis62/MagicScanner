"""Inventaire : une ligne par (impression, langue, état, prix, finition) avec une quantité.

Chaque scan incrémente la ligne correspondante et reste traçable (table scans) pour pouvoir être annulé
ou réaffecté. Les lignes ne sont jamais supprimées (les scans y font référence) : quantité 0 = vide.
"""
import sqlite3

from .config import DEFAULT_CONDITION, DEFAULT_PRICE


class AlreadyListed(Exception):
    """L'exemplaire est déjà en vente sur Cardmarket : on ne peut pas le retirer du stock d'ici."""


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


def _check_removable(con: sqlite3.Connection, line_id: int) -> None:
    line = con.execute("SELECT quantity, listed_quantity FROM inventory WHERE id=?", (line_id,)).fetchone()
    if line["quantity"] - 1 < line["listed_quantity"]:
        raise AlreadyListed("Cet exemplaire est déjà publié sur Cardmarket : retire l'annonce là-bas, pas ici.")


def undo_scan(con: sqlite3.Connection, scan_id: int) -> bool:
    scan = _active_scan(con, scan_id)
    if scan is None:
        return False
    _check_removable(con, scan["inventory_id"])
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
    _check_removable(con, scan["inventory_id"])
    _add(con, scan["inventory_id"], -1)
    old = con.execute("SELECT foil, price FROM inventory WHERE id=?", (scan["inventory_id"],)).fetchone()
    line_id = _line_id(con, card_id, lang, bool(old["foil"]) if foil is None else foil,
                       old["price"] if price is None else price)
    _add(con, line_id, 1)
    con.execute("UPDATE scans SET inventory_id=?, card_id=?, lang=? WHERE id=?", (line_id, card_id, lang, scan_id))
    con.commit()
    return True


def quantity(con: sqlite3.Connection, card_id: str, lang: str, foil: bool = False,
             price: float = DEFAULT_PRICE) -> tuple[int, int]:
    """(en stock, déjà publiées sur Cardmarket) pour cette carte dans cette langue, finition et ce prix."""
    row = con.execute(
        "SELECT quantity, listed_quantity FROM inventory WHERE card_id=? AND lang=? AND condition=? AND price=? AND foil=?",
        (card_id, lang, DEFAULT_CONDITION, round(price, 2), int(foil)),
    ).fetchone()
    return (row["quantity"], row["listed_quantity"]) if row else (0, 0)


def scan_line(con: sqlite3.Connection, scan_id: int) -> sqlite3.Row:
    """Finition et prix de la ligne où est rangé le scan."""
    return con.execute("SELECT i.foil, i.price FROM scans s JOIN inventory i ON i.id = s.inventory_id WHERE s.id=?",
                       (scan_id,)).fetchone()


def recent_scans(con: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT s.*, i.foil, i.price FROM scans s JOIN inventory i ON i.id = s.inventory_id
           WHERE s.undone=0 ORDER BY s.id DESC LIMIT ?""", (limit,)).fetchall()


def mark_listed(con: sqlite3.Connection, line_id: int, amount: int, url: str | None = None) -> None:
    """Enregistre une mise en vente : avance le compteur de la ligne et l'inscrit au journal avec son prix."""
    con.execute(
        """UPDATE inventory SET listed_quantity = listed_quantity + ?, list_error = NULL,
           updated_at = CURRENT_TIMESTAMP WHERE id=?""",
        (amount, line_id),
    )
    con.execute(
        """INSERT INTO listings (inventory_id, card_id, lang, condition, price, foil, amount, url)
           SELECT id, card_id, lang, condition, price, foil, ?, ? FROM inventory WHERE id=?""",
        (amount, url, line_id),
    )
    con.commit()


def mark_all_listed(con: sqlite3.Connection) -> int:
    """Considère tout le stock comme déjà en vente (publié ailleurs, par exemple via TCG Powertools) : plus rien
    n'est « à publier ». Chaque ligne est inscrite au journal comme une mise en vente. Renvoie le nombre d'exemplaires."""
    total = 0
    for line in con.execute("SELECT id, quantity - listed_quantity AS n FROM inventory WHERE quantity > listed_quantity").fetchall():
        mark_listed(con, line["id"], line["n"])
        total += line["n"]
    return total


def withdraw_listing(con: sqlite3.Connection, line_id: int, amount: int = 1) -> None:
    """À appeler après avoir retiré à la main une annonce sur Cardmarket : le compteur « publiées » baisse et le
    journal garde la trace du retrait (ligne de quantité négative, la publication d'origine reste visible)."""
    line = con.execute("SELECT listed_quantity FROM inventory WHERE id=?", (line_id,)).fetchone()
    if line is None:
        raise ValueError(f"ligne d'inventaire {line_id} introuvable")
    if not 0 < amount <= line["listed_quantity"]:
        raise ValueError(f"la ligne {line_id} n'a que {line['listed_quantity']} exemplaire(s) publié(s)")
    con.execute("UPDATE inventory SET listed_quantity = listed_quantity - ?, updated_at = CURRENT_TIMESTAMP WHERE id=?",
                (amount, line_id))
    con.execute(
        """INSERT INTO listings (inventory_id, card_id, lang, condition, price, foil, amount, url)
           SELECT id, card_id, lang, condition, price, foil, ?,
                  (SELECT url FROM listings WHERE inventory_id = inventory.id AND amount > 0 ORDER BY id DESC LIMIT 1)
           FROM inventory WHERE id=?""",
        (-amount, line_id),
    )
    con.commit()


def listings(con: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    """Dernières mises en vente (carte, langue, état, prix auquel elle a été faite, quantité, date)."""
    return con.execute(
        """SELECT l.*, datetime(l.listed_at, 'localtime') AS listed_local, c.name, c.set_code, c.collector_number FROM listings l JOIN cards c ON c.id = l.card_id
           ORDER BY l.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def mark_list_error(con: sqlite3.Connection, line_id: int, message: str) -> None:
    con.execute("UPDATE inventory SET list_error=? WHERE id=?", (message[:300], line_id))
    con.commit()


def stats(con: sqlite3.Connection) -> dict:
    row = con.execute(
        """SELECT COALESCE(SUM(quantity), 0) AS cards,
                  COUNT(CASE WHEN quantity > 0 THEN 1 END) AS lines,
                  COALESCE(SUM(MAX(quantity - listed_quantity, 0)), 0) AS to_list,
                  COUNT(CASE WHEN quantity > listed_quantity THEN 1 END) AS lines_to_list,
                  COALESCE(SUM(MAX(quantity - listed_quantity, 0) * price), 0) AS to_list_value,
                  COALESCE(SUM(MAX(quantity - exported_quantity, 0)), 0) AS to_export,
                  COALESCE(SUM(listed_quantity), 0) AS listed,
                  COALESCE(SUM(quantity * price), 0) AS value
           FROM inventory"""
    ).fetchone()
    today = con.execute("SELECT COUNT(*) FROM scans WHERE undone=0 AND date(created_at) = date('now')").fetchone()[0]
    return {**dict(row), "today": today, "default_price": DEFAULT_PRICE}


def list_errors(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT list_error, COUNT(*) AS n FROM inventory WHERE list_error IS NOT NULL GROUP BY list_error"
    ).fetchall()


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
                   c.name, c.cardmarket_id, s.name AS set_name
            FROM inventory i JOIN cards c ON c.id = i.card_id JOIN sets s ON s.code = c.set_code
            WHERE i.quantity > {already} ORDER BY s.name, c.name"""
    ).fetchall()


def mark_exported(con: sqlite3.Connection, line_ids: list[int]) -> None:
    """Les lignes données sont entièrement exportées (leur stock actuel ne sera plus proposé)."""
    con.executemany("UPDATE inventory SET exported_quantity = quantity WHERE id=?", [(i,) for i in line_ids])
    con.commit()
