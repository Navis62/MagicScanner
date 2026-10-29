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

from ..config import (
    LANGS,
    SCRYFALL_BULK_URL,
    SCRYFALL_DIR,
    SCRYFALL_HEADERS,
    SCRYFALL_SETS_URL,
)
from .download import download

log = logging.getLogger(__name__)

SKIP_LAYOUTS = {"vanguard", "planar", "scheme", "reversible_card"}
SAME_SIDE_LAYOUTS = {"split", "fuse", "aftermath", "flip"}
SKIP_SET_TYPES = {"memorabilia", "minigame", "alchemy", "vanguard", "treasure_chest"}
CARD_COLUMNS = ("id", "oracle_id", "name", "front_name", "set_code", "collector_number", "rarity", "cardmarket_id",
                "image_normal", "image_small", "released_at", "layout", "frame", "promo", "set_type",
                "finishes", "promo_types", "power", "toughness", "colors", "type_line", "artist")


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
        """INSERT INTO sets (code, name, released_at, set_type, card_count, printed_size, icon_svg, parent_set_code)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(code) DO UPDATE SET name=excluded.name, released_at=excluded.released_at,
             set_type=excluded.set_type, card_count=excluded.card_count,
             printed_size=excluded.printed_size, icon_svg=excluded.icon_svg,
             parent_set_code=excluded.parent_set_code""",
        [(s["code"], s["name"], s.get("released_at"), s.get("set_type"), s.get("card_count"),
          s.get("printed_size"), s.get("icon_svg_uri"), s.get("parent_set_code")) for s in data],
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


def _front_colors(card: dict) -> list[str]:
    faces = card.get("card_faces")
    return card.get("colors") or (faces[0].get("colors") if faces else None) or []


def _other_faces(card: dict, key: str) -> list[str]:
    """Noms des faces suivantes des cartes à deux moitiés imprimées sur la même face (split, fuse, aftermath, flip) :
    le nom lu peut être celui de n'importe quelle moitié."""
    if card.get("layout") not in SAME_SIDE_LAYOUTS:
        return []
    return [f[key] for f in (card.get("card_faces") or [])[1:] if f.get(key)]


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
        and (card.get("set_type") not in SKIP_SET_TYPES or card.get("layout") == "art_series")
    )


def _read_bulk(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip().rstrip(",")
            if line.startswith("{"):
                yield json.loads(line)


def _card_row(c: dict, oracle_id: str | None) -> tuple:
    return (
        c["id"], oracle_id, c["name"], _front(c, "name"), c["set"], c["collector_number"], c.get("rarity"),
        c.get("cardmarket_id"), _image(c, "normal"), _image(c, "small"), c.get("released_at"),
        c.get("layout"), c.get("frame"), int(bool(c.get("promo"))), c.get("set_type"),
        ",".join(c.get("finishes", [])), ",".join(c.get("promo_types", [])),
        _front(c, "power"), _front(c, "toughness"), ",".join(_front_colors(c)), _front(c, "type_line"), _front(c, "artist"),
    )


def _subtypes(type_line: str | None, sep: str) -> list[str]:
    """Sous-types d'une ligne de type (« Creature — Cat Spirit » -> [cat, spirit] ; « Créature : chat et esprit »)."""
    if not type_line or " // " in type_line or sep not in type_line:
        return []
    return type_line.split(sep, 1)[1].lower().replace(" et ", " ").split()


def _type_translations(pairs: list[tuple[str, list[str]]]) -> dict[tuple[str, str], str]:
    """Sous-types EN -> localisés, par vote sur les fiches traduites (les deux lignes de type listent les mêmes sous-types)."""
    votes: dict[tuple[str, str], dict[str, int]] = {}
    for lang, (en, loc) in pairs:
        if len(en) == len(loc):
            for a, b in zip(en, loc, strict=True):
                votes.setdefault((lang, a), {}).setdefault(b, 0)
                votes[(lang, a)][b] += 1
    return {k: max(v, key=v.get) for k, v in votes.items()}


def _token_names(cards: list[tuple], translations: dict[tuple[str, str], str], langs: set[str]) -> set[tuple]:
    """Scryfall ne traduit pas les tokens (aucune fiche VF) : le nom imprimé d'un token est son ou ses sous-types
    (« Oiseau », « Soldat kithkin »), qu'on déduit de la traduction des sous-types des cartes ordinaires."""
    i_layout, i_name, i_oracle = CARD_COLUMNS.index("layout"), CARD_COLUMNS.index("front_name"), CARD_COLUMNS.index("oracle_id")
    names = set()
    for row in cards:
        if row[i_layout] not in ("token", "double_faced_token") or not row[i_oracle]:
            continue
        words = row[i_name].lower().split()
        for lang in langs:
            loc = [translations.get((lang, w)) for w in words]
            if not all(loc):
                continue
            variants = {" ".join(loc), " ".join(reversed(loc)), " et ".join(loc), " et ".join(reversed(loc))}
            names.update((row[i_oracle], lang, v.capitalize()) for v in variants)
    return names


def import_cards(con: sqlite3.Connection, path: Path) -> None:
    cards, localized, names = [], [], set()
    type_pairs: list[tuple[str, tuple[list[str], list[str]]]] = []
    en_keys: set[tuple[str, str]] = set()
    fr_only: dict[tuple[str, str], tuple] = {}   # éditions sans fiche anglaise (ex. FBB) : la fiche FR sert d'impression
    for c in filter(_keep, _read_bulk(path)):
        oracle_id = c.get("oracle_id") or (c.get("card_faces") or [{}])[0].get("oracle_id")
        key = (c["set"], c["collector_number"])
        if c["lang"] == "en":
            cards.append(_card_row(c, oracle_id))
            en_keys.add(key)
            names.add((oracle_id, "en", _front(c, "name")))
            names.update((oracle_id, "en", n) for n in _other_faces(c, "name"))
        else:
            printed = c.get("printed_name") or " // ".join(f.get("printed_name", "") for f in c.get("card_faces", [])) or None
            front = _front(c, "printed_name")
            localized.append((c["id"], c["lang"], oracle_id, c["set"], c["collector_number"], printed, front, _image(c, "normal")))
            fr_only.setdefault(key, _card_row(c, oracle_id))
            type_pairs.append((c["lang"], (_subtypes(c.get("type_line"), " — "), _subtypes(c.get("printed_type_line"), " : ")
                                           or _subtypes(c.get("printed_type_line"), " — "))))
            if front:
                names.add((oracle_id, c["lang"], front))
            names.update((oracle_id, c["lang"], n) for n in _other_faces(c, "printed_name"))

    orphans = [row for key, row in fr_only.items() if key not in en_keys]
    cards += orphans
    names.update((row[1], "en", row[3]) for row in orphans)
    names |= _token_names(cards, _type_translations(type_pairs), {lang for lang, _ in type_pairs})
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
