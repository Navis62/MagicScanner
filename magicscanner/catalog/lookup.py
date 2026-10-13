"""Lecture du référentiel : recherche floue des noms (VO/VF), impressions d'une carte, fiche d'affichage."""
import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from ..config import PRICE_ALERT
from ..market import urls

PRINTING_SQL = """
    SELECT c.*, s.name AS set_name, s.icon_svg, s.released_at AS set_date,
           COALESCE(s.printed_size, s.card_count) AS set_size,
           l.printed_name AS fr_name, l.image_normal AS fr_image,
           pr.trend
    FROM cards c
    JOIN sets s ON s.code = c.set_code
    LEFT JOIN localized l ON l.set_code = c.set_code AND l.collector_number = c.collector_number AND l.lang = 'fr'
    LEFT JOIN cm_prices pr ON pr.id_product = c.cardmarket_id
"""


def normalize(s: str) -> str:
    """Minuscules, sans accents ni ponctuation : robuste aux approximations de l'OCR."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


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
        self.fr_sets = {r[0] for r in con.execute("SELECT DISTINCT set_code FROM localized WHERE lang='fr'")}

    def match_names(self, texts: list[str], min_score: float = 70) -> list[NameMatch]:
        """Meilleure correspondance par carte (oracle), tous textes confondus, triée par score."""
        best: dict[str, NameMatch] = {}
        for text in texts:
            for _, score, idx in process.extract(normalize(text), self._names, scorer=fuzz.ratio, limit=8):
                oracle_id, lang, name = self._meta[idx]
                if score >= min_score and (oracle_id not in best or score > best[oracle_id].score):
                    best[oracle_id] = NameMatch(oracle_id, lang, name, score)
        return sorted(best.values(), key=lambda m: -m.score)

    def printings(self, oracle_ids: list[str]) -> list[sqlite3.Row]:
        if not oracle_ids:
            return []
        marks = ",".join("?" * len(oracle_ids))
        return self.con.execute(f"{PRINTING_SQL} WHERE c.oracle_id IN ({marks})", oracle_ids).fetchall()

    def search(self, query: str, limit: int = 40) -> tuple[str | None, list[str]]:
        """Recherche manuelle : (langue du nom trouvé, impressions les plus récentes d'abord)."""
        matches = self.match_names([query])[:3]
        if not matches:
            return None, []
        rows = sorted(self.printings([m.oracle_id for m in matches]), key=lambda p: p["released_at"] or "", reverse=True)
        return matches[0].lang, [p["id"] for p in rows[:limit]]

    def card_info(self, card_id: str, lang: str | None = None) -> dict:
        """Fiche d'affichage d'une impression (image VF si la langue est fr et qu'un scan VF existe)."""
        c = self.con.execute(f"{PRINTING_SQL} WHERE c.id = ?", (card_id,)).fetchone()
        fr_name = c["fr_name"]
        if not fr_name:  # pas de fiche VF pour cette édition : nom VF connu via une autre édition
            r = self.con.execute("SELECT name FROM names WHERE oracle_id=? AND lang='fr' LIMIT 1", (c["oracle_id"],)).fetchone()
            fr_name = r["name"] if r else None
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
            "cardmarket_id": c["cardmarket_id"],
            "cardmarket_url": urls.product_url(self.con, card_id),
            "trend": c["trend"],
            "price_alert": bool(c["trend"] and c["trend"] >= PRICE_ALERT),
        }
