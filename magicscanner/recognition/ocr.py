"""Lecture du texte de la carte redressée (RapidOCR) et extraction des indices utiles :
nom (bandeau du haut), numéro de collection / code d'édition (bas de carte), langue du texte."""
import re
from dataclasses import dataclass

import numpy as np
from rapidocr import RapidOCR

from .detect import CARD_H, CARD_W

FR_WORDS = {"le", "la", "les", "de", "des", "du", "vous", "une", "un", "et", "chaque", "cible", "carte", "créature",
            "éphémère", "rituel", "terrain", "enchantement", "artefact", "jusqu'à", "contrôlez", "champ", "bataille"}
EN_WORDS = {"the", "you", "of", "a", "an", "and", "each", "target", "card", "creature", "instant", "sorcery", "land",
            "enchantment", "artifact", "until", "control", "battlefield", "your", "when", "draw"}
FR_ACCENTS = "éèêàçû"


@dataclass(frozen=True)
class OcrLine:
    text: str
    score: float
    x: float  # coin haut-gauche, en fraction de la carte
    y: float


@dataclass(frozen=True)
class CollectorInfo:
    number: str | None = None   # « 87 » (sans zéros de tête)
    total: str | None = None    # « 356 » (taille de l'édition, anciens cadres)
    set_code: str | None = None  # « c13 » (cadres récents : « C13 • FR »)


class OcrEngine:
    def __init__(self):
        self._engine = RapidOCR()

    def read(self, card: np.ndarray) -> list[OcrLine]:
        res = self._engine(card)
        if res.txts is None:
            return []
        return [OcrLine(t, float(s), float(b[0][0]) / CARD_W, float(b[0][1]) / CARD_H)
                for b, t, s in zip(res.boxes, res.txts, res.scores)]


def title_candidates(lines: list[OcrLine]) -> list[str]:
    """Textes du bandeau de titre (haut-gauche), du plus haut au plus bas."""
    top = sorted((l for l in lines if l.y < 0.13 and l.x < 0.6 and len(l.text) >= 3), key=lambda l: (l.y, l.x))
    return [l.text for l in top[:3]]


def _strip_zeros(n: str) -> str:
    return n.lstrip("0") or "0"


def collector_info(lines: list[OcrLine]) -> CollectorInfo:
    number = total = set_code = None
    for text in (l.text for l in lines if l.y > 0.88):
        if number is None and (m := re.search(r"(\d{1,4})\s*/\s*(\d{2,4})", text)):
            number, total = _strip_zeros(m.group(1)), _strip_zeros(m.group(2))
        if set_code is None and (m := re.search(r"\b([A-Z0-9]{3,5})\s*[•·.*\-]\s*(EN|FR)\b", text.upper())):
            set_code = m.group(1).lower()
        if number is None and (m := re.match(r"^\s*(\d{3,4})\s*[CURMLST]?\s*$", text)):
            number = _strip_zeros(m.group(1))  # cadre récent : « 0087 U »
    return CollectorInfo(number, total, set_code)


def detect_language(lines: list[OcrLine]) -> str | None:
    """'fr' / 'en' d'après les mots courants et les accents du texte, None si trop peu d'indices."""
    words = re.findall(r"[a-zA-Zàâçéèêëîïôûùüÿœ']+", " ".join(l.text for l in lines).lower())
    fr = sum(w in FR_WORDS for w in words) + 2 * sum(any(c in w for c in FR_ACCENTS) for w in words)
    en = sum(w in EN_WORDS for w in words)
    if fr + en < 2:
        return None
    return "fr" if fr > en else "en"
