"""URLs produit Cardmarket : /en/Magic/Products/Singles/<Extension>/<Carte>.

Les slugs Cardmarket ne suivent pas une règle unique (« Akroma's Memorial » -> Akroma-s-Memorial,
« Lim-Dûl's Cohort » -> LimDuls-Cohort, « Plains (V.1) » -> Plains-V-1) : on génère des variantes par ordre
de probabilité, le lister ouvre chacune et garde celle dont le formulaire porte le bon idProduct (table cm_urls).
"""
import re
import sqlite3
import unicodedata

from ..config import CM_SINGLES_URL


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
    suffix = f"-V-{version}" if version else ""
    return list(dict.fromkeys(v + suffix for v in variants))


def slugify(name: str) -> str:
    return slug_variants(name)[0]


def _version(con: sqlite3.Connection, id_product: int | None, id_expansion: int | None, name: str) -> int | None:
    """Plusieurs produits de même nom dans une extension = versions V.1, V.2… numérotées dans l'ordre des idProduct."""
    if not id_product or id_expansion is None:
        return None
    ids = [r[0] for r in con.execute(
        "SELECT id_product FROM cm_products WHERE id_expansion=? AND name=? ORDER BY id_product", (id_expansion, name))]
    if len(ids) < 2 or id_product not in ids:
        return None
    return ids.index(id_product) + 1


def _product(con: sqlite3.Connection, card_id: str) -> sqlite3.Row | None:
    return con.execute(
        """SELECT COALESCE(p.name, c.name) AS name, c.cardmarket_id, p.id_expansion,
                  COALESCE(e.slug, s.cm_slug) AS exp_slug, u.url AS known_url
           FROM cards c JOIN sets s ON s.code = c.set_code
           LEFT JOIN cm_products p ON p.id_product = c.cardmarket_id
           LEFT JOIN cm_expansions e ON e.id_expansion = p.id_expansion
           LEFT JOIN cm_urls u ON u.id_product = c.cardmarket_id
           WHERE c.id = ?""",
        (card_id,),
    ).fetchone()


def product_name(con: sqlite3.Connection, card_id: str) -> str | None:
    row = _product(con, card_id)
    return row["name"] if row else None


def candidate_urls(con: sqlite3.Connection, card_id: str) -> list[str]:
    """URL déjà validée en premier, puis les variantes de slug."""
    row = _product(con, card_id)
    if row is None or not row["exp_slug"]:
        return []
    version = _version(con, row["cardmarket_id"], row["id_expansion"], row["name"])
    urls = [f"{CM_SINGLES_URL}/{row['exp_slug']}/{s}" for s in slug_variants(row["name"], version)]
    return list(dict.fromkeys(([row["known_url"]] if row["known_url"] else []) + urls))


def product_url(con: sqlite3.Connection, card_id: str) -> str | None:
    urls = candidate_urls(con, card_id)
    return urls[0] if urls else None


def remember_url(con: sqlite3.Connection, id_product: int, url: str) -> None:
    con.execute("INSERT OR REPLACE INTO cm_urls VALUES (?,?)", (id_product, url))
    con.commit()
