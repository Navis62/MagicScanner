"""Export CSV pour l'import de TCG Powertools (cf. example-import.csv)."""
import csv
import io
import sqlite3

from . import inventory

COLUMNS = ["cardmarketId", "quantity", "name", "set", "condition", "language", "isSigned", "price", "comment",
           "finishType", "buyPrice"]
LANGUAGES = {"en": "English", "fr": "French"}


def build(con: sqlite3.Connection, everything: bool = False) -> tuple[str, int, int]:
    """(contenu CSV, lignes exportées, cartes sans identifiant Cardmarket laissées de côté).
    Les lignes exportées sont marquées : le prochain export ne contiendra que les nouvelles cartes."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    exported, skipped = [], 0
    for r in inventory.powertools_rows(con, everything):
        if not r["cardmarket_id"]:
            skipped += r["amount"]
            continue
        w.writerow([r["cardmarket_id"], r["amount"], r["name"], r["set_name"], r["condition"],
                    LANGUAGES.get(r["lang"], r["lang"]), "false", f"{r['price']:.2f}", "",
                    "Foil" if r["foil"] else "Regular", ""])
        exported.append(r["line_id"])
    if not everything:
        inventory.mark_exported(con, exported)
    return out.getvalue(), len(exported), skipped
