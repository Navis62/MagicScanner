"""Lecture du référentiel : recherche floue des noms (VO/VF), impressions d'une carte, fiche d'affichage."""
import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from ..market import urls

PRINTING_SQL = """
    SELECT c.*, s.name AS set_name, s.icon_svg, s.released_at AS set_date,
           COALESCE(s.printed_size, s.card_count) AS set_size,
           l.printed_name AS fr_name, l.image_normal AS fr_image,
           pr.trend, pr.trend_foil
    FROM cards c
    JOIN sets s ON s.code = c.set_code
    LEFT JOIN localized l ON l.set_code = c.set_code AND l.collector_number = c.collector_number AND l.lang = 'fr'
    LEFT JOIN cm_prices pr ON pr.id_product = c.cardmarket_id
"""


# Nom anglais (première face) -> nom français imprimé, pour les cartes sans fiche française chez Scryfall.
MISSING_FR_NAMES = {"Initiate of Blood": "Adepte de sang"}


def normalize(s: str) -> str:
    """Minuscules, sans accents ni ponctuation : robuste aux approximations de l'OCR."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def list_label(cm_expansion: str | None) -> str:
    """Nom à afficher pour une carte à l'étincelle (édition « plst » de Scryfall). Scryfall y regroupe The List et
    Mystery Booster : c'est l'extension Cardmarket de la carte qui dit laquelle des deux (ou Mystery Booster 2…)."""
    if not cm_expansion:
        return "The List / Mystery Booster"
    return "Mystery Booster 2" if cm_expansion.startswith("Mystery Booster 2") else cm_expansion


@dataclass(frozen=True)
class NameMatch:
    oracle_id: str
    lang: str      # langue du nom reconnu
    name: str
    score: float   # 0-100


class Catalog:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        rows = con.execute("SELECT oracle_id, lang, name FROM names").fetchall()
        self._names = [normalize(r["name"]) for r in rows]
        self._meta = [(r["oracle_id"], r["lang"], r["name"]) for r in rows]
        self._add_missing_names()
        self.fr_sets = {r[0] for r in con.execute("SELECT DISTINCT set_code FROM localized WHERE lang='fr'")}
        self._by_set: dict[str, tuple[list[str], list[tuple]]] = {}

    def _add_missing_names(self) -> None:
        """Noms VF absents de Scryfall (aucune fiche française pour la carte) : sans eux, la carte est confondue avec
        le nom le plus proche (« Adepte de sang » lu comme « Orateur de sang »)."""
        by_en = {m[2]: m[0] for m in self._meta if m[1] == "en"}
        for en_name, fr_name in MISSING_FR_NAMES.items():
            if oracle_id := by_en.get(en_name):
                self._names.append(normalize(fr_name))
                self._meta.append((oracle_id, "fr", fr_name))

    def _names_in_set(self, set_code: str) -> tuple[list[str], list[tuple]]:
        """Noms (toutes langues) des cartes imprimées dans une édition : la liste de recherche quand l'édition est fixée."""
        if set_code not in self._by_set:
            oracles = {r[0] for r in self.con.execute("SELECT DISTINCT oracle_id FROM cards WHERE set_code = ?", (set_code,))}
            keep = [i for i, meta in enumerate(self._meta) if meta[0] in oracles]
            self._by_set[set_code] = [self._names[i] for i in keep], [self._meta[i] for i in keep]
        return self._by_set[set_code]

    def match_names(self, texts: list[str], min_score: float = 70, set_code: str | None = None) -> list[NameMatch]:
        """Meilleure correspondance par carte (oracle), tous textes confondus, triée par score. Avec `set_code`, seules
        les cartes de cette édition sont envisagées."""
        names, metas = self._names_in_set(set_code) if set_code else (self._names, self._meta)
        best: dict[str, NameMatch] = {}
        for text in texts:
            for _, score, idx in process.extract(normalize(text), names, scorer=fuzz.ratio, limit=8):
                oracle_id, lang, name = metas[idx]
                if score >= min_score and (oracle_id not in best or score > best[oracle_id].score):
                    best[oracle_id] = NameMatch(oracle_id, lang, name, score)
        return sorted(best.values(), key=lambda m: -m.score)

    def printings(self, oracle_ids: list[str]) -> list[sqlite3.Row]:
        if not oracle_ids:
            return []
        marks = ",".join("?" * len(oracle_ids))
        return self.con.execute(f"{PRINTING_SQL} WHERE c.oracle_id IN ({marks})", oracle_ids).fetchall()

    def sets(self) -> list[dict]:
        """Éditions qui ont des cartes, les plus récentes d'abord (choix de l'édition fixée)."""
        rows = self.con.execute(
            """SELECT s.code, s.name, s.released_at FROM sets s
               WHERE EXISTS (SELECT 1 FROM cards c WHERE c.set_code = s.code)
               ORDER BY s.released_at DESC, s.name""").fetchall()
        return [dict(r) for r in rows]

    def search(self, query: str, limit: int = 40, set_code: str | None = None) -> tuple[str | None, list[str]]:
        """Recherche manuelle : (langue du nom trouvé, impressions de `set_code` puis les plus récentes d'abord)."""
        matches = self.match_names([query])[:3]
        if not matches:
            return None, []
        rows = sorted(self.printings([m.oracle_id for m in matches]), key=lambda p: p["released_at"] or "", reverse=True)
        rows.sort(key=lambda p: p["set_code"] != set_code)   # tri stable : l'édition fixée en tête
        return matches[0].lang, [p["id"] for p in rows[:limit]]

    def card_info(self, card_id: str, lang: str | None = None, foil: bool = False) -> dict:
        """Fiche d'affichage d'une impression (image VF si la langue est fr et qu'un scan VF existe)."""
        c = self.con.execute(f"{PRINTING_SQL} WHERE c.id = ?", (card_id,)).fetchone()
        fr_name = c["fr_name"]
        if not fr_name:  # pas de fiche VF pour cette édition : nom VF connu via une autre édition
            r = self.con.execute("SELECT name FROM names WHERE oracle_id=? AND lang='fr' LIMIT 1", (c["oracle_id"],)).fetchone()
            fr_name = r["name"] if r else None
        expansion = self.con.execute(
            "SELECT e.name FROM cm_products p JOIN cm_expansions e ON e.id_expansion = p.id_expansion WHERE p.id_product = ?",
            (c["cardmarket_id"],),
        ).fetchone()
        trend = c["trend_foil"] if foil else c["trend"]
        return {
            "card_id": card_id,
            "name": c["name"],
            "fr_name": fr_name,
            "set_code": c["set_code"],
            "set_name": c["set_name"],
            "set_icon": c["icon_svg"],
            "set_date": c["set_date"],
            "collector_number": c["collector_number"],
            "rarity": c["rarity"],
            "image": c["fr_image"] if lang == "fr" and c["fr_image"] else c["image_normal"],
            "image_small": c["image_small"],
            "is_list": c["set_code"] == "plst",
            "list_label": list_label(expansion["name"] if expansion else None) if c["set_code"] == "plst" else None,
            "cm_expansion": expansion["name"] if expansion else None,
            "cardmarket_id": c["cardmarket_id"],
            "cardmarket_url": urls.browse_url(urls.product_url(self.con, card_id)),
            "trend": trend,
        }
