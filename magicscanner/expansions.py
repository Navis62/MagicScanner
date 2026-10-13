"""Récupère la liste officielle des extensions Cardmarket (slug + nom) et la rattache aux idExpansion."""
import re
import sqlite3

from . import browser
from .data_import import map_sets

EXPANSIONS_URL = "https://www.cardmarket.com/en/Magic/Expansions"

JS_ROWS = """() => [...document.querySelectorAll('.expansion-row[data-url]')].map(r => ({
    url: r.dataset.url,
    name: r.dataset.localName,
    img: (r.querySelector('img[data-echo]') || {}).dataset?.echo || null,
}))"""


def sync(con: sqlite3.Connection) -> None:
    with browser.cardmarket_page() as page:
        browser.goto(page, EXPANSIONS_URL)
        rows = page.evaluate(JS_ROWS)
    print(f"  {len(rows)} extensions lues sur Cardmarket")
    con.execute("DELETE FROM cm_expansions")
    linked = 0
    for r in rows:
        slug = r["url"].rstrip("/").rsplit("/", 1)[-1]
        id_exp, code = None, None
        # L'image d'aperçu contient un idProduct : .../1/DKA/252474/252474.jpg -> idExpansion via le catalogue.
        m = re.search(r"/\d+/([^/]+)/(\d+)/", r["img"] or "")
        if m:
            code = m.group(1)
            row = con.execute("SELECT id_expansion FROM cm_products WHERE id_product=?", (int(m.group(2)),)).fetchone()
            if row:
                id_exp = row["id_expansion"]
                linked += 1
        con.execute("INSERT OR REPLACE INTO cm_expansions VALUES (?,?,?,?)", (id_exp, slug, r["name"], code))
    con.commit()
    print(f"  {linked} rattachées à un idExpansion")
    map_sets(con)
