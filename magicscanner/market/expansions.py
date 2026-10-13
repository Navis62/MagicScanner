"""Lecture de la liste officielle des extensions sur cardmarket.com (slug + nom), rattachée aux idExpansion."""
import logging
import re
import sqlite3

from ..catalog import cardmarket as cm_catalog
from ..config import CM_EXPANSIONS_URL
from . import browser

log = logging.getLogger(__name__)

JS_ROWS = """() => [...document.querySelectorAll('.expansion-row[data-url]')].map(r => ({
    url: r.dataset.url,
    name: r.dataset.localName,
    img: (r.querySelector('img[data-echo]') || {}).dataset?.echo || null,
}))"""

# L'image d'aperçu de chaque extension contient un idProduct : .../1/DKA/252474/252474.jpg
PREVIEW_RE = re.compile(r"/\d+/([^/]+)/(\d+)/")


def sync(con: sqlite3.Connection) -> None:
    with browser.cardmarket_page() as page:
        browser.goto(page, CM_EXPANSIONS_URL)
        rows = page.evaluate(JS_ROWS)
    log.info("%d extensions lues sur Cardmarket", len(rows))

    expansions = []
    for r in rows:
        slug = r["url"].rstrip("/").rsplit("/", 1)[-1]
        id_expansion = code = None
        if m := PREVIEW_RE.search(r["img"] or ""):
            code = m.group(1)
            product = con.execute("SELECT id_expansion FROM cm_products WHERE id_product=?", (int(m.group(2)),)).fetchone()
            id_expansion = product["id_expansion"] if product else None
        expansions.append((id_expansion, slug, r["name"], code))
    cm_catalog.store_expansions(con, expansions)
    log.info("%d rattachées à un idExpansion", sum(e[0] is not None for e in expansions))
    cm_catalog.map_sets(con)
