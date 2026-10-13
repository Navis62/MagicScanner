"""Import du catalogue public Cardmarket (produits + guide des prix) et rattachement des éditions Scryfall
aux extensions Cardmarket (idExpansion + slug d'URL)."""
import json
import logging
import sqlite3
from collections import Counter, defaultdict

from ..config import CARDMARKET_DIR, CM_PRICES_URL, CM_PRODUCTS_URL
from ..market.urls import slugify
from .download import download

log = logging.getLogger(__name__)


def import_catalog(con: sqlite3.Connection) -> None:
    products = json.loads(download(CM_PRODUCTS_URL, CARDMARKET_DIR / "products_singles.json").read_text(encoding="utf-8"))["products"]
    guides = json.loads(download(CM_PRICES_URL, CARDMARKET_DIR / "price_guide.json").read_text(encoding="utf-8"))["priceGuides"]
    con.execute("DELETE FROM cm_products")
    con.executemany(
        "INSERT INTO cm_products VALUES (?,?,?,?)",
        [(p["idProduct"], p["name"], p.get("idExpansion"), p.get("idMetacard")) for p in products],
    )
    con.execute("DELETE FROM cm_prices")
    con.executemany(
        "INSERT OR REPLACE INTO cm_prices VALUES (?,?,?,?,?,?)",
        [(g["idProduct"], g.get("trend"), g.get("avg"), g.get("low"), g.get("avg7"), g.get("avg30")) for g in guides],
    )
    con.commit()
    log.info("%d produits, %d prix", len(products), len(guides))


def store_expansions(con: sqlite3.Connection, expansions: list[tuple[int | None, str, str, str | None]]) -> None:
    """Enregistre la liste officielle (idExpansion, slug, nom, code) lue sur cardmarket.com."""
    con.execute("DELETE FROM cm_expansions")
    con.executemany("INSERT OR REPLACE INTO cm_expansions VALUES (?,?,?,?)", expansions)
    con.commit()


def map_sets(con: sqlite3.Connection) -> None:
    """idExpansion de chaque édition = vote majoritaire de ses cartes (via cardmarket_id) ; slug = celui lu sur
    Cardmarket si connu, sinon dérivé du nom Scryfall. Les slugs saisis à la main ('manual') sont conservés."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for code, exp in con.execute(
        "SELECT c.set_code, p.id_expansion FROM cards c JOIN cm_products p ON p.id_product = c.cardmarket_id"
    ):
        votes[code][exp] += 1
    official = {r["id_expansion"]: r["slug"] for r in con.execute("SELECT * FROM cm_expansions WHERE id_expansion IS NOT NULL")}

    confirmed = 0
    for s in con.execute("SELECT code, name FROM sets WHERE cm_slug_source IS NOT 'manual'").fetchall():
        exp = votes[s["code"]].most_common(1)[0][0] if votes.get(s["code"]) else None
        if exp in official:
            slug, source = official[exp], "cardmarket"
            confirmed += 1
        else:
            slug, source = slugify(s["name"]), "guess"
        con.execute("UPDATE sets SET cm_id_expansion=?, cm_slug=?, cm_slug_source=? WHERE code=?", (exp, slug, source, s["code"]))
    con.commit()
    log.info("slugs : %d confirmés par Cardmarket, le reste deviné depuis le nom Scryfall", confirmed)
