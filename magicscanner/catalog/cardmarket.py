"""Import du catalogue public Cardmarket (produits + guide des prix) et rattachement des éditions Scryfall
aux extensions Cardmarket (idExpansion + slug d'URL)."""
import json
import logging
import re
import sqlite3
import time
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


PRICE_GUIDE = CARDMARKET_DIR / "price_guide.json"


def download_prices() -> dict:
    """Télécharge le guide des prix Cardmarket (mis à jour chaque nuit), sans toucher à la base."""
    return json.loads(download(CM_PRICES_URL, PRICE_GUIDE).read_text(encoding="utf-8"))


def prices_age_hours() -> float | None:
    """Âge du guide des prix téléchargé en dernier (None s'il n'a jamais été téléchargé)."""
    return (time.time() - PRICE_GUIDE.stat().st_mtime) / 3600 if PRICE_GUIDE.exists() else None


def import_prices(con: sqlite3.Connection) -> str | None:
    """Télécharge le guide des prix Cardmarket et remplace les prix en base. Renvoie sa date de publication."""
    return store_prices(con, download_prices())


def store_prices(con: sqlite3.Connection, guide: dict) -> str | None:
    """Remplace les prix en base par ceux du guide. Renvoie la date de publication du guide."""
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
    for s in con.execute("SELECT code, name, set_type, parent_set_code FROM sets WHERE cm_slug_source IS NOT 'manual'").fetchall():
        exp = votes[s["code"]].most_common(1)[0][0] if votes.get(s["code"]) else None
        if s["set_type"] == "token":
            # Les idProduct de Scryfall pour les jetons sont souvent ceux d'une autre extension (tmh2 -> War of the Spark) :
            # l'extension Cardmarket des jetons se lit sur son code, pas sur le vote.
            exp = _token_expansion(con, s["code"], s["parent_set_code"]) or exp
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


TOKEN_SUFFIX = re.compile(r"\s+Token\b(\s*\([^)]*\))?\s*$", re.IGNORECASE)   # « Kor Soldier Token (White 1/1) » -> « Kor Soldier »


def _token_expansion(con: sqlite3.Connection, code: str, parent: str | None) -> int | None:
    """Extension Cardmarket des jetons d'une édition `t*` : « <Édition>: Tokens » (code TMH3) pour les éditions récentes,
    « <Édition>: Extras » (code XMH2) pour les plus anciennes. Seule une extension qui contient des produits « Token »
    est retenue (sinon None : on garde le vote des cartes)."""
    for sample in (code.upper(), "X" + (parent or code[1:]).upper()):
        for r in con.execute("SELECT id_expansion FROM cm_expansions WHERE id_expansion IS NOT NULL AND UPPER(sample_code)=?", (sample,)):
            if con.execute("SELECT 1 FROM cm_products WHERE id_expansion=? AND name LIKE '% Token%' LIMIT 1", (r[0],)).fetchone():
                return r[0]
    return None


def _token_sets(con: sqlite3.Connection) -> dict[str, tuple[int, ...]]:
    """Éditions de tokens : leurs produits sont dans l'extension Cardmarket de l'édition (« Skeleton Token (Black 1/1) »)."""
    return {r["code"]: (r["cm_id_expansion"],) for r in con.execute(
        "SELECT code, cm_id_expansion FROM sets WHERE set_type='token' AND cm_id_expansion IS NOT NULL")}


def _product_key(name: str) -> tuple[str, bool]:
    """Clé de comparaison d'un produit Cardmarket avec le nom Scryfall, et « est un jeton » (suffixe « Token »).
    Le suffixe est retiré face par face : « Bird Token (W 1/1) // Clue Token » -> « bird // clue »."""
    faces = re.split(r"\s+//?\s+", name)
    if any(TOKEN_SUFFIX.search(f) for f in faces):
        return " // ".join(TOKEN_SUFFIX.sub("", f).strip().lower() for f in faces), True
    return name.lower(), False


def _name_keys(name: str) -> list[str]:
    """Écritures possibles du nom d'une carte « A // B » : telle quelle, puis faces inversées (Cardmarket range parfois
    « The Initiative // Undercity » là où Scryfall écrit « Undercity // The Initiative »)."""
    name = name.lower()
    return [name, " // ".join(reversed(name.split(" // ")))] if " // " in name else [name]


def _token_index(con: sqlite3.Connection, expansions) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Produits des extensions, par nom : (jetons « X Token (…) », autres produits au nom complet).
    La frontière : un jeton-créature (type « Token Creature… ») n'est vendu que sous la forme « X Token (…) », jamais
    sous un nom nu ; une carte « extra » de l'extension qui porte le même nom (« Spider ») n'est donc pas lui. Un
    emblème, un donjon, « The Monarch » (type sans « Token ») se vendent sous leur nom complet."""
    marks = ",".join("?" * len(expansions))
    tokens: dict[str, list[int]] = defaultdict(list)
    others: dict[str, list[int]] = defaultdict(list)
    for p in con.execute(f"SELECT id_product, name FROM cm_products WHERE id_expansion IN ({marks})", tuple(expansions)):
        key, is_token = _product_key(p["name"])
        (tokens if is_token else others)[key].append(p["id_product"])
    return tokens, others


def _sister_names(con: sqlite3.Connection, set_code: str, own: int) -> set[str]:
    """Noms de produits des extensions « Extras » / « Tokens » sœurs vers lesquelles Scryfall renvoie d'autres cartes de
    l'édition (tdmu : Dominaria United: Extras et Commander: Dominaria United: Extras). Un nom qu'on y trouve aussi est
    ambigu : on ne sait pas dans laquelle des deux la carte se vend."""
    sisters = [r[0] for r in con.execute(
        "SELECT DISTINCT p.id_expansion FROM cards c JOIN cm_products p ON p.id_product = c.cardmarket_id "
        "JOIN cm_expansions e ON e.id_expansion = p.id_expansion "
        "WHERE c.set_code=? AND p.id_expansion != ? AND (e.name LIKE '%: Extras' OR e.name LIKE '%: Tokens')", (set_code, own))]
    if not sisters:
        return set()
    tokens, others = _token_index(con, sisters)
    return set(tokens) | set(others)


def _plain_candidates(by_name: dict[str, list[int]], name: str) -> list[int]:
    """Produits de ce nom ; « A // B » s'écrit aussi « A / B »."""
    return by_name.get(name) or by_name.get(name.replace(" // ", " / "), [])


def _anchor_pick(number: int, anchors: list[tuple[int, int]]) -> int | None:
    """idProduct attendu pour la carte n° `number`, d'après les cartes déjà liées (numéro entier, idProduct), triées :
    celle d'à côté donne le décalage idProduct - numéro ; l'ancre de l'autre côté, si elle existe, doit donner le même."""
    below = [a for a in anchors if a[0] < number]
    above = [a for a in anchors if a[0] > number]
    sides = [side for side in (below[-1:], above[:1]) if side]
    offsets = {pid - cn for (cn, pid), in sides}
    if len(offsets) != 1:
        return None
    return number + offsets.pop()


def _double_face_pick(name: str, token_names: dict[str, list[int]], taken: set[int]) -> int | None:
    """Jeton imprimé seulement au dos d'une autre carte (« Goblin Token (R 1/1) // Dungeon of the Mad Mage ») : le produit
    double face dont une face est ce jeton, s'il n'y en a qu'un dans l'extension (pris ou non : un produit déjà pris
    prouve que d'autres cartes y figurent) et qu'il est libre."""
    found = {i for key, ids in token_names.items() if " // " in key and name in key.split(" // ") for i in ids}
    return found.pop() if len(found) == 1 and not found & taken else None


def _link_by_position(con, set_code, leftovers, known, taken, token_names, other_names, homonyms, sister) -> int:
    """Seconde passe des éditions de jetons, pour les cartes que le nom seul ne départage pas : l'idProduct suit le numéro
    de collection dans l'extension (tmh2 : 568765 + numéro). Détail des règles dans `_anchor_pick` et `_double_face_pick`."""
    anchors = sorted((int(r["collector_number"]), r["cardmarket_id"]) for r in con.execute(
        "SELECT collector_number, cardmarket_id FROM cards WHERE set_code=? AND cardmarket_id IS NOT NULL", (set_code,))
        if r["cardmarket_id"] in known and r["collector_number"].isdigit())
    # Un jeton à qui Scryfall donne le produit d'une autre extension (tmh2 n°6 -> War of the Spark) est candidat lui aussi :
    # le produit à sa position, s'il porte son nom, est le bon.
    leftovers = leftovers + [(c, _token_found(c, token_names, other_names)) for c in con.execute(
        "SELECT id, name, type_line, collector_number, cardmarket_id FROM cards WHERE set_code=? AND cardmarket_id IS NOT NULL",
        (set_code,)) if c["cardmarket_id"] not in known and not any(k in sister for k in _name_keys(c["name"].lower()))]
    linked = 0
    for card, found in leftovers:
        number = card["collector_number"]
        pick = None
        if found and number.isdigit() and "Dungeon" not in (card["type_line"] or ""):
            # Donjons exclus : chez Cardmarket ils existent en version oversized, le produit à la position n'est pas sûr.
            guess = _anchor_pick(int(number), anchors)
            pick = guess if guess in found and guess not in taken else None
        elif (not found and card["cardmarket_id"] is None and homonyms[card["name"].lower()] == 1
              and (card["type_line"] or "Token").startswith("Token")):
            pick = _double_face_pick(card["name"].lower(), token_names, taken)
        if pick is not None:
            con.execute("UPDATE cards SET cardmarket_id=? WHERE id=?", (pick, card["id"]))
            taken.add(pick)
            linked += 1
    return linked


def _token_found(card, token_names, other_names) -> list[int]:
    """Produits de l'extension qui portent le nom de la carte (jeton : « X Token (…) » ; sinon aussi le nom complet)."""
    keys = _name_keys(card["name"].lower())
    found = [i for k in keys for i in token_names.get(k, [])]
    if not (card["type_line"] or "Token").startswith("Token"):
        found += [i for k in keys for i in other_names.get(k, [])]
    return found


def link_list_cards(con: sqlite3.Connection) -> int:
    """Scryfall n'indique pas l'idProduct de certaines cartes (environ 1 carte plst sur 5, quelques cartes de FBB,
    Renaissance, Salvat). On le retrouve par le nom, mais seulement quand ça ne laisse aucun doute : un seul produit de
    ce nom dans les extensions de l'édition, pas déjà pris par une autre carte de l'édition, et une seule carte de
    l'édition sans identifiant de ce nom. Le reste reste en erreur plutôt que de risquer une annonce sur la mauvaise
    page. Renvoie le nombre de cartes rattachées."""
    linked = 0
    tokens = _token_sets(con)
    for set_code, expansions in {**tokens, **LINKED_SETS}.items():
        is_token = set_code in tokens
        if is_token:
            token_names, other_names = _token_index(con, expansions)
            sister = _sister_names(con, set_code, expansions[0])
        else:
            marks = ",".join("?" * len(expansions))
            token_names, other_names, sister = defaultdict(list), defaultdict(list), set()
            for p in con.execute(f"SELECT id_product, name FROM cm_products WHERE id_expansion IN ({marks})", expansions):
                token_names[p["name"].lower()].append(p["id_product"])
        known = {i for ids in (*token_names.values(), *other_names.values()) for i in ids}
        taken = {r[0] for r in con.execute("SELECT cardmarket_id FROM cards WHERE set_code=? AND cardmarket_id IS NOT NULL", (set_code,))}
        missing = con.execute("SELECT id, name, type_line, collector_number, cardmarket_id FROM cards WHERE set_code=? AND cardmarket_id IS NULL "
                              "ORDER BY CAST(collector_number AS INTEGER), collector_number", (set_code,)).fetchall()
        homonyms = Counter(m["name"].lower() for m in missing)
        if is_token:
            # Un jeton dont Scryfall donne le produit d'une autre extension compte aussi : c'est peut-être lui qui
            # porte l'unique produit de ce nom ici.
            homonyms.update(r["name"].lower() for r in con.execute(
                "SELECT name, cardmarket_id FROM cards WHERE set_code=? AND cardmarket_id IS NOT NULL", (set_code,))
                if r["cardmarket_id"] not in known)
        rank: Counter = Counter()
        leftovers = []
        for card in missing:
            name = card["name"].lower()
            if is_token:
                keys = _name_keys(name)
                if any(k in sister for k in keys):
                    continue
                found = _token_found(card, token_names, other_names)
            else:
                found = _plain_candidates(token_names, name)
            products = sorted(p for p in found if p not in taken)
            if len(products) == 1 and homonyms[name] == 1:
                pick = products[0]
            elif set_code in ORDERED_SETS and len(products) == homonyms[name]:
                pick = products[rank[name]]
                rank[name] += 1
            else:
                if is_token:
                    leftovers.append((card, found))
                continue
            con.execute("UPDATE cards SET cardmarket_id=? WHERE id=?", (pick, card["id"]))
            linked += 1
            if pick in products and len(products) == 1:
                taken.add(pick)
        if is_token:
            taken |= {r[0] for r in con.execute("SELECT cardmarket_id FROM cards WHERE set_code=? AND cardmarket_id IS NOT NULL", (set_code,))}
            linked += _link_by_position(con, set_code, leftovers, known, taken, token_names, other_names, homonyms, sister)
    con.commit()
    log.info("%d cartes rattachées à leur produit Cardmarket par le nom", linked)
    return linked
