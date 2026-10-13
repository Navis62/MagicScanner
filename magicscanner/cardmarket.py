"""Construction des URLs produit Cardmarket : /en/Magic/Products/Singles/<Expansion-Slug>/<Card-Slug>.

Les slugs produit Cardmarket ne suivent pas une règle unique (« Akroma's Memorial » -> Akroma-s-Memorial,
« Lim-Dûl's Cohort » -> LimDuls-Cohort, « Plains (V.1) » -> Plains-V-1). On génère donc des variantes
dans l'ordre de probabilité ; le lister valide la page (titre) et mémorise l'URL qui marche.
"""
import re
import sqlite3
import unicodedata

BASE = "https://www.cardmarket.com/en/Magic/Products/Singles"

# Valeurs du formulaire de vente Cardmarket.
CM_LANGUAGE_ID = {"en": 1, "fr": 2, "de": 3, "es": 4, "it": 5, "zhs": 6, "ja": 7, "pt": 8, "ru": 9, "ko": 10, "zht": 11}
CM_CONDITION = {"MT": 1, "NM": 2, "EX": 3, "GD": 4, "LP": 5, "PL": 6, "PO": 7}


def _ascii(s: str) -> str:
    s = s.replace("Æ", "Ae").replace("æ", "ae")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def _dash(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")


def slug_variants(name: str, version: int | None = None) -> list[str]:
    base = _ascii(name).replace(" // ", " ").replace(" / ", " ")
    variants = [
        _dash(re.sub(r"[',.!?:\"]", "", base)),                   # Akromas-Memorial, Jace-the-Mind-Sculptor
        _dash(re.sub(r"[,.!?:\"]", "", base)),                    # Akroma-s-Memorial
        _dash(re.sub(r"[',.!?:\"]", "", base.replace("-", ""))),  # LimDuls-Cohort
    ]
    out = []
    for v in variants:
        if version:
            v = f"{v}-V-{version}"
        if v not in out:
            out.append(v)
    return out


def slugify(name: str) -> str:
    return slug_variants(name)[0]


def _version(con: sqlite3.Connection, card_id: str, id_product: int | None, id_exp: int | None, cm_name: str) -> int | None:
    """Plusieurs produits de même nom dans une extension = versions V.1, V.2... (ordre des idProduct,
    rapproché de l'ordre des numéros de collection Scryfall)."""
    if not id_product or id_exp is None:
        return None
    ids = [r[0] for r in con.execute(
        "SELECT id_product FROM cm_products WHERE id_expansion=? AND name=? ORDER BY id_product", (id_exp, cm_name))]
    if len(ids) < 2:
        return None
    return ids.index(id_product) + 1 if id_product in ids else None


def candidate_urls(con: sqlite3.Connection, card_id: str) -> list[str]:
    row = con.execute(
        """SELECT c.name, c.cardmarket_id, p.id_expansion, COALESCE(e.slug, s.cm_slug) AS exp_slug, p.name AS cm_name
           FROM cards c JOIN sets s ON s.code = c.set_code
           LEFT JOIN cm_products p ON p.id_product = c.cardmarket_id
           LEFT JOIN cm_expansions e ON e.id_expansion = p.id_expansion
           WHERE c.id = ?""",
        (card_id,),
    ).fetchone()
    if row is None or not row["exp_slug"]:
        return []
    name = row["cm_name"] or row["name"]
    version = _version(con, card_id, row["cardmarket_id"], row["id_expansion"], name)
    return [f"{BASE}/{row['exp_slug']}/{s}" for s in slug_variants(name, version)]


def product_url(con: sqlite3.Connection, card_id: str) -> str | None:
    """URL connue (validée par le lister) sinon la variante la plus probable."""
    row = con.execute(
        "SELECT u.url FROM cm_urls u JOIN cards c ON c.cardmarket_id = u.id_product WHERE c.id=?", (card_id,)
    ).fetchone()
    if row:
        return row["url"]
    urls = candidate_urls(con, card_id)
    return urls[0] if urls else None


def product_label(con: sqlite3.Connection, card_id: str) -> tuple[str, str] | None:
    """(nom produit Cardmarket, code extension) pour valider le titre de page : « Gravecrawler (DKA) - MTG Singles »."""
    row = con.execute(
        """SELECT COALESCE(p.name, c.name) AS name, c.set_code FROM cards c
           LEFT JOIN cm_products p ON p.id_product = c.cardmarket_id WHERE c.id=?""", (card_id,)).fetchone()
    return (row["name"], row["set_code"]) if row else None
