"""Import Scryfall : éditions et cartes (fichier bulk all_cards, filtré sur le papier en VO/VF).

Une impression = sa fiche anglaise (qui porte le cardmarket_id). Les fiches françaises sont rangées à part
(table localized) et rattachées par (édition, numéro de collection).
"""
import gzip
import json
import logging
import sqlite3
from pathlib import Path

import httpx

from ..config import LANGS, SCRYFALL_BULK_URL, SCRYFALL_DIR, SCRYFALL_HEADERS, SCRYFALL_SETS_URL
from .download import download

log = logging.getLogger(__name__)

SKIP_LAYOUTS = {"token", "double_faced_token", "emblem", "art_series", "vanguard", "planar", "scheme", "reversible_card"}
SKIP_SET_TYPES = {"token", "memorabilia", "minigame", "alchemy", "vanguard", "treasure_chest"}
CARD_COLUMNS = ("id", "oracle_id", "name", "front_name", "set_code", "collector_number", "rarity", "cardmarket_id",
                "image_normal", "image_small", "released_at", "layout", "frame", "promo", "set_type")


def download_bulk(force: bool = False) -> Path:
    info = httpx.get(SCRYFALL_BULK_URL, headers=SCRYFALL_HEADERS).json()
    url = info.get("jsonl_download_uri") or info["download_uri"]
    dest = SCRYFALL_DIR / url.rsplit("/", 1)[-1]
    if dest.exists() and not force:
        log.info("déjà présent : %s", dest.name)
        return dest
    for old in SCRYFALL_DIR.glob("all-cards*"):
        old.unlink()
    return download(url, dest)


def latest_bulk() -> Path | None:
    return next(iter(sorted(SCRYFALL_DIR.glob("all-cards*"), reverse=True)), None)


def import_sets(con: sqlite3.Connection) -> None:
    data = httpx.get(SCRYFALL_SETS_URL, headers=SCRYFALL_HEADERS, timeout=60).json()["data"]
    con.executemany(
        """INSERT INTO sets (code, name, released_at, set_type, card_count, printed_size, icon_svg)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(code) DO UPDATE SET name=excluded.name, released_at=excluded.released_at,
             set_type=excluded.set_type, card_count=excluded.card_count,
             printed_size=excluded.printed_size, icon_svg=excluded.icon_svg""",
        [(s["code"], s["name"], s.get("released_at"), s.get("set_type"), s.get("card_count"),
          s.get("printed_size"), s.get("icon_svg_uri")) for s in data],
    )
    con.commit()
    log.info("%d éditions", len(data))


def _front(card: dict, key: str) -> str | None:
    """Valeur de la première face (nom imprimé en titre pour les cartes à plusieurs faces)."""
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


def _keep(card: dict) -> bool:
    return (
        card.get("lang") in LANGS
        and "paper" in card.get("games", [])
        and not card.get("oversized")
        and card.get("layout") not in SKIP_LAYOUTS
        and card.get("set_type") not in SKIP_SET_TYPES
    )


def _read_bulk(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip().rstrip(",")
            if line.startswith("{"):
                yield json.loads(line)


def import_cards(con: sqlite3.Connection, path: Path) -> None:
    cards, localized, names = [], [], set()
    for c in filter(_keep, _read_bulk(path)):
        oracle_id = c.get("oracle_id") or (c.get("card_faces") or [{}])[0].get("oracle_id")
        if c["lang"] == "en":
            cards.append((
                c["id"], oracle_id, c["name"], _front(c, "name"), c["set"], c["collector_number"], c.get("rarity"),
                c.get("cardmarket_id"), _image(c, "normal"), _image(c, "small"), c.get("released_at"),
                c.get("layout"), c.get("frame"), int(bool(c.get("promo"))), c.get("set_type"),
            ))
            names.add((oracle_id, "en", _front(c, "name")))
        else:
            printed = c.get("printed_name") or " // ".join(f.get("printed_name", "") for f in c.get("card_faces", [])) or None
            front = _front(c, "printed_name")
            localized.append((c["id"], c["lang"], oracle_id, c["set"], c["collector_number"], printed, front, _image(c, "normal")))
            if front:
                names.add((oracle_id, c["lang"], front))

    # cards est référencée par l'inventaire : mise à jour en place, jamais de DELETE.
    con.executemany(
        f"""INSERT INTO cards ({", ".join(CARD_COLUMNS)}) VALUES ({", ".join("?" * len(CARD_COLUMNS))})
            ON CONFLICT(id) DO UPDATE SET {", ".join(f"{c}=excluded.{c}" for c in CARD_COLUMNS[1:])}""",
        cards,
    )
    con.execute("DELETE FROM localized")
    con.execute("DELETE FROM names")
    con.executemany("INSERT OR REPLACE INTO localized VALUES (?,?,?,?,?,?,?,?)", localized)
    con.executemany("INSERT OR IGNORE INTO names VALUES (?,?,?)", [n for n in names if n[0] and n[2]])
    con.commit()
    log.info("%d impressions VO, %d fiches localisées, %d noms", len(cards), len(localized), len(names))
