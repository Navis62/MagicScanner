"""Export CSV pour l'import de TCG Powertools (cf. example-import.csv)."""
import csv
import io
import sqlite3

from . import inventory

COLUMNS = ["cardmarketId", "quantity", "name", "set", "condition", "language", "isSigned", "price", "comment",
           "finishType", "buyPrice"]
LANGUAGES = {"en": "English", "fr": "French"}
# Éditions que l'import attend sous un autre libellé que le nom Scryfall.
SET_LABELS = {"fbb": "DTL - Foreign Black Bordered"}
FWB_LABEL = "DTU - Foreign White Bordered"   # Revised (3ed) en langue étrangère : Scryfall n'a pas d'édition FWB


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
        set_label = FWB_LABEL if r["set_code"] == "3ed" and r["lang"] != "en" else SET_LABELS.get(r["set_code"], r["set_name"])
        w.writerow([r["cardmarket_id"], r["amount"], r["name"], set_label, r["condition"],
                    LANGUAGES.get(r["lang"], r["lang"]), "false", f"{r['price']:.2f}", "",
                    "Foil" if r["foil"] else "Regular", ""])
        exported.append(r["line_id"])
    if not everything:
        inventory.mark_exported(con, exported)
    return out.getvalue(), len(exported), skipped
