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

# plst (The List + Mystery Booster) : réparti entre The List, Mystery Booster, Mystery Booster 2, Secret Lair…
MULTI_EXPANSION_SETS = {"plst"}


def import_catalog(con: sqlite3.Connection) -> None:
    products = json.loads(download(CM_PRODUCTS_URL, CARDMARKET_DIR / "products_singles.json").read_text(encoding="utf-8"))["products"]
    con.execute("DELETE FROM cm_products")
    con.executemany(
        "INSERT INTO cm_products VALUES (?,?,?,?)",
        [(p["idProduct"], p["name"], p.get("idExpansion"), p.get("idMetacard")) for p in products],
    )
    con.commit()
    log.info("%d produits", len(products))
    import_prices(con)


def import_prices(con: sqlite3.Connection) -> str | None:
    """Télécharge le guide des prix Cardmarket (mis à jour chaque nuit) et remplace les prix en base.
    Renvoie la date de publication du guide."""
    guide = json.loads(download(CM_PRICES_URL, CARDMARKET_DIR / "price_guide.json").read_text(encoding="utf-8"))
    guides = guide["priceGuides"]
    con.execute("DELETE FROM cm_prices")
    con.executemany(
        "INSERT OR REPLACE INTO cm_prices (id_product, trend, avg, low, avg7, avg30, trend_foil) VALUES (?,?,?,?,?,?,?)",
        [(g["idProduct"], g.get("trend"), g.get("avg"), g.get("low"), g.get("avg7"), g.get("avg30"), g.get("trend-foil"))
         for g in guides],
    )
    con.commit()
    log.info("%d prix", len(guides))
    return guide.get("createdAt")


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
        if s["code"] in MULTI_EXPANSION_SETS:
            # Les cartes de cette édition se vendent dans plusieurs extensions Cardmarket : un slug « majoritaire »
            # pointerait vers la page d'une autre version. Seul l'idProduct de chaque carte fait foi.
            con.execute("UPDATE sets SET cm_id_expansion=NULL, cm_slug=NULL, cm_slug_source='none' WHERE code=?", (s["code"],))
            continue
        if exp in official:
            slug, source = official[exp], "cardmarket"
            confirmed += 1
        else:
            slug, source = slugify(s["name"]), "guess"
        con.execute("UPDATE sets SET cm_id_expansion=?, cm_slug=?, cm_slug_source=? WHERE code=?", (exp, slug, source, s["code"]))
    con.commit()
    log.info("slugs : %d confirmés par Cardmarket, le reste deviné depuis le nom Scryfall", confirmed)


# Extensions Cardmarket où se vendent les cartes plst (The List, Mystery Booster, Mystery Booster 2).
LIST_EXPANSIONS = (3494, 2874, 5911)


# Éditions dont des cartes n'ont pas d'idProduct chez Scryfall : extensions Cardmarket où les chercher par le nom.
# Éditions où les homonymes (terrains de base) se rattachent dans l'ordre : numéro de collection croissant = idProduct
# croissant (vérifié sur les terrains de FBB déjà rattachés par Scryfall).
ORDERED_SETS = {"fbb"}
LINKED_SETS = {"plst": LIST_EXPANSIONS, "fbb": (57,), "ren": (60,), "psal": (105,)}


def link_list_cards(con: sqlite3.Connection) -> int:
    """Scryfall n'indique pas l'idProduct de certaines cartes (environ 1 carte plst sur 5, quelques cartes de FBB,
    Renaissance, Salvat). On le retrouve par le nom, mais seulement quand ça ne laisse aucun doute : un seul produit de
    ce nom dans les extensions de l'édition, pas déjà pris par une autre carte de l'édition, et une seule carte de
    l'édition sans identifiant de ce nom. Le reste reste en erreur plutôt que de risquer une annonce sur la mauvaise
    page. Renvoie le nombre de cartes rattachées."""
    linked = 0
    for set_code, expansions in LINKED_SETS.items():
        marks = ",".join("?" * len(expansions))
        by_name: dict[str, list[int]] = defaultdict(list)
        for p in con.execute(f"SELECT id_product, name FROM cm_products WHERE id_expansion IN ({marks})", expansions):
            by_name[p["name"].lower()].append(p["id_product"])
        taken = {r[0] for r in con.execute("SELECT cardmarket_id FROM cards WHERE set_code=? AND cardmarket_id IS NOT NULL", (set_code,))}
        missing = con.execute("SELECT id, name FROM cards WHERE set_code=? AND cardmarket_id IS NULL "
                              "ORDER BY CAST(collector_number AS INTEGER), collector_number", (set_code,)).fetchall()
        homonyms = Counter(m["name"].lower() for m in missing)
        rank: Counter = Counter()
        for card in missing:
            name = card["name"].lower()
            products = sorted(p for p in by_name.get(name) or by_name.get(name.replace(" // ", " / "), []) if p not in taken)
            if len(products) == 1 and homonyms[name] == 1:
                pick = products[0]
            elif set_code in ORDERED_SETS and len(products) == homonyms[name]:
                pick = products[rank[name]]
                rank[name] += 1
            else:
                continue
            con.execute("UPDATE cards SET cardmarket_id=? WHERE id=?", (pick, card["id"]))
            linked += 1
            if pick in products and len(products) == 1:
                taken.add(pick)
    con.commit()
    log.info("%d cartes rattachées à leur produit Cardmarket par le nom", linked)
    return linked
