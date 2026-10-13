"""Import du référentiel : Scryfall (all_cards en/fr + sets) et catalogue public Cardmarket (produits + prix)."""
import gzip
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from .cardmarket import slugify
from .config import CARDMARKET_DIR, CM_PRICES_URL, CM_PRODUCTS_URL, LANGS, SCRYFALL_DIR, SCRYFALL_UA

SKIP_LAYOUTS = {"token", "double_faced_token", "emblem", "art_series", "vanguard", "planar", "scheme", "reversible_card"}
SKIP_SET_TYPES = {"token", "memorabilia", "minigame", "alchemy", "vanguard", "treasure_chest"}


def _download(url: str, dest: Path) -> Path:
    print(f"  téléchargement {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, headers=SCRYFALL_UA, follow_redirects=True, timeout=None) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def download_scryfall(force: bool = False) -> Path:
    info = httpx.get("https://api.scryfall.com/bulk-data/all-cards", headers=SCRYFALL_UA).json()
    url = info.get("jsonl_download_uri") or info["download_uri"]
    dest = SCRYFALL_DIR / url.rsplit("/", 1)[-1]
    if dest.exists() and not force:
        print(f"  déjà présent : {dest.name}")
        return dest
    for old in SCRYFALL_DIR.glob("all-cards*"):
        old.unlink()
    return _download(url, dest)


def _front(card: dict, key: str) -> str | None:
    faces = card.get("card_faces")
    if faces and faces[0].get(key):
        return faces[0][key]
    v = card.get(key)
    return v.split(" // ")[0] if v else None


def _image(card: dict, size: str) -> str | None:
    if card.get("image_status") in ("missing", "placeholder"):
        return None
    uris = card.get("image_uris") or (card.get("card_faces") or [{}])[0].get("image_uris") or {}
    return uris.get(size)


def import_scryfall(con: sqlite3.Connection, path: Path) -> None:
    con.execute("DELETE FROM cards")
    con.execute("DELETE FROM localized")
    con.execute("DELETE FROM names")
    cards, locs, names = [], [], set()
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip().rstrip(",")
            if not line.startswith("{"):
                continue
            c = json.loads(line)
            lang = c.get("lang")
            if lang not in LANGS or "paper" not in c.get("games", []) or c.get("oversized"):
                continue
            if c.get("layout") in SKIP_LAYOUTS or c.get("set_type") in SKIP_SET_TYPES:
                continue
            oid = c.get("oracle_id") or (c.get("card_faces") or [{}])[0].get("oracle_id")
            if lang == "en":
                cards.append((
                    c["id"], oid, c["name"], _front(c, "name"), c["set"], c["collector_number"], c.get("rarity"),
                    c.get("cardmarket_id"), _image(c, "normal"), _image(c, "small"), c.get("released_at"),
                    c.get("layout"), c.get("frame"), int(bool(c.get("promo"))), c.get("set_type"),
                ))
                names.add((oid, "en", _front(c, "name")))
            else:
                pn = c.get("printed_name") or " // ".join(f.get("printed_name", "") for f in c.get("card_faces", [])) or None
                fpn = _front(c, "printed_name")
                locs.append((c["id"], lang, oid, c["set"], c["collector_number"], pn, fpn, _image(c, "normal")))
                if fpn:
                    names.add((oid, lang, fpn))
    con.executemany("INSERT OR REPLACE INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", cards)
    con.executemany("INSERT OR REPLACE INTO localized VALUES (?,?,?,?,?,?,?,?)", locs)
    con.executemany("INSERT OR IGNORE INTO names VALUES (?,?,?)", [n for n in names if n[0] and n[2]])
    con.commit()
    print(f"  {len(cards)} impressions VO, {len(locs)} fiches localisées, {len(names)} noms")


def import_sets(con: sqlite3.Connection) -> None:
    data = httpx.get("https://api.scryfall.com/sets", headers=SCRYFALL_UA, timeout=60).json()["data"]
    for s in data:
        con.execute(
            """INSERT INTO sets (code, name, released_at, set_type, card_count, printed_size, icon_svg)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET name=excluded.name, released_at=excluded.released_at,
                 set_type=excluded.set_type, card_count=excluded.card_count,
                 printed_size=excluded.printed_size, icon_svg=excluded.icon_svg""",
            (s["code"], s["name"], s.get("released_at"), s.get("set_type"), s.get("card_count"),
             s.get("printed_size"), s.get("icon_svg_uri")),
        )
    con.commit()
    print(f"  {len(data)} éditions")


def import_cardmarket(con: sqlite3.Connection) -> None:
    prod = _download(CM_PRODUCTS_URL, CARDMARKET_DIR / "products_singles.json")
    price = _download(CM_PRICES_URL, CARDMARKET_DIR / "price_guide.json")
    products = json.loads(prod.read_text(encoding="utf-8"))["products"]
    con.execute("DELETE FROM cm_products")
    con.executemany(
        "INSERT INTO cm_products VALUES (?,?,?,?)",
        [(p["idProduct"], p["name"], p.get("idExpansion"), p.get("idMetacard")) for p in products],
    )
    guides = json.loads(price.read_text(encoding="utf-8"))["priceGuides"]
    con.execute("DELETE FROM cm_prices")
    con.executemany(
        "INSERT OR REPLACE INTO cm_prices VALUES (?,?,?,?,?,?)",
        [(g["idProduct"], g.get("trend"), g.get("avg"), g.get("low"), g.get("avg7"), g.get("avg30")) for g in guides],
    )
    con.commit()
    print(f"  {len(products)} produits, {len(guides)} prix")


def map_sets(con: sqlite3.Connection) -> None:
    """Associe chaque édition Scryfall à son idExpansion Cardmarket (vote majoritaire via cardmarket_id)
    puis à son slug (scrapé si disponible, sinon deviné depuis le nom)."""
    votes: dict[str, Counter] = defaultdict(Counter)
    for code, exp in con.execute(
        "SELECT c.set_code, p.id_expansion FROM cards c JOIN cm_products p ON p.id_product = c.cardmarket_id"
    ):
        votes[code][exp] += 1
    scraped = {r["id_expansion"]: r["slug"] for r in con.execute("SELECT * FROM cm_expansions WHERE id_expansion IS NOT NULL")}
    n_scraped = 0
    for s in con.execute("SELECT code, name, cm_slug_source FROM sets").fetchall():
        if s["cm_slug_source"] == "manual":
            continue
        exp = votes[s["code"]].most_common(1)[0][0] if votes.get(s["code"]) else None
        if exp in scraped:
            slug, src = scraped[exp], "cardmarket"
            n_scraped += 1
        else:
            slug, src = slugify(s["name"]), "guess"
        con.execute("UPDATE sets SET cm_id_expansion=?, cm_slug=?, cm_slug_source=? WHERE code=?", (exp, slug, src, s["code"]))
    con.commit()
    print(f"  slugs : {n_scraped} confirmés par Cardmarket, le reste deviné depuis le nom Scryfall")


def run(con: sqlite3.Connection, skip_download: bool = False) -> None:
    print("Scryfall : éditions")
    import_sets(con)
    print("Scryfall : cartes")
    path = next(SCRYFALL_DIR.glob("all-cards*"), None) if skip_download else download_scryfall()
    import_scryfall(con, path)
    print("Cardmarket : catalogue et prix")
    import_cardmarket(con)
    print("Correspondance éditions -> Cardmarket")
    map_sets(con)
