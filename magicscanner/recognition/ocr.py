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
class PixelLine:
    """Ligne lue dans l'image entière (coordonnées en pixels : coin haut-gauche et hauteur)."""
    text: str
    x: float
    y: float
    height: float


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
                for b, t, s in zip(res.boxes, res.txts, res.scores, strict=True)]

    def read_pixels(self, frame: np.ndarray) -> list[PixelLine]:
        """Lit une image entière (la carte n'y est pas encore localisée) : positions en pixels."""
        res = self._engine(frame)
        if res.txts is None:
            return []
        return [PixelLine(t, float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 1].max() - b[:, 1].min()))
                for b, t in zip(res.boxes, res.txts, strict=True)]


# Position des repères sur une carte (fractions de sa hauteur) : centre du titre, ligne la plus basse à gauche
# (code d'édition / langue), et retrait du texte par rapport au bord gauche (fraction de sa largeur).
TITLE_CENTER, FOOTER_CENTER, TEXT_INSET = 0.060, 0.945, 0.095


def card_from_title(title: PixelLine, footer: PixelLine) -> np.ndarray | None:
    """Coins (haut-gauche, haut-droit, bas-droit, bas-gauche) d'une carte droite, déduits de sa ligne de titre et de la
    ligne du bas : sert quand le bord noir de la carte se fond dans l'ombre et que la détection des contours échoue."""
    title_y, footer_y = title.y + title.height / 2, footer.y + footer.height / 2
    height = (footer_y - title_y) / (FOOTER_CENTER - TITLE_CENTER)
    if height < 100:
        return None
    width = height * 63 / 88
    left, top = title.x - TEXT_INSET * width, title_y - TITLE_CENTER * height
    return np.float32([[left, top], [left + width, top], [left + width, top + height], [left, top + height]])


def title_candidates(lines: list[OcrLine]) -> list[str]:
    """Textes du bandeau de titre (haut-gauche), du plus haut au plus bas."""
    top = sorted((l for l in lines if l.y < 0.13 and l.x < 0.6 and len(l.text) >= 3), key=lambda l: (l.y, l.x))
    return [l.text for l in top[:3]]


def sideways_titles(lines: list[OcrLine]) -> list[str]:
    """Cartes à deux moitiés (split, aftermath…) : les noms sont imprimés tournés à 90° et n'importe où sur la carte.
    Sur l'image remise à l'endroit, on prend toutes les lignes courtes, de haut en bas."""
    short = sorted((l for l in lines if 3 <= len(l.text) <= 25 and l.score >= 0.5), key=lambda l: (l.y, l.x))
    return [l.text for l in short[:12]]


def _strip_zeros(n: str) -> str:
    return n.lstrip("0") or "0"


# Numéro sans total, rareté avant ou après : « 0087 U » (Commander 2013…) ou « C 0126 » (Marvel Super Heroes…).
RECENT_NUMBER = re.compile(r"^\s*(?:(\d{3,4})\s*[CURMLST]?|[CURMLST]\s*(\d{3,4}))\s*$")


def collector_info(lines: list[OcrLine]) -> CollectorInfo:
    number = total = set_code = None
    for text in (l.text for l in lines if l.y > 0.88):
        if number is None and (m := re.search(r"(\d{1,4})\s*/\s*(\d{2,4})", text)):
            number, total = _strip_zeros(m.group(1)), _strip_zeros(m.group(2))
        if set_code is None and (m := re.search(r"\b([A-Z0-9]{3,5})\s*[•·.*\-]\s*(EN|FR)\b", text.upper())):
            set_code = m.group(1).lower()
        if number is None and (m := RECENT_NUMBER.match(text)):
            number = _strip_zeros(m.group(1) or m.group(2))  # cadre récent : « 0087 U » ou, selon l'édition, « C 0126 »
    return CollectorInfo(number, total, set_code)


# Force / endurance (« 4/4 », « */3 ») : cadre en bas à droite, au-dessus de la ligne du copyright.
PT = re.compile(r"^\s*(\d{1,2}|\*)\s*/\s*(\d{1,2}|\*)\s*$")


def power_toughness(lines: list[OcrLine]) -> tuple[str, str] | None:
    for l in lines:
        if l.y > 0.80 and l.x > 0.55 and (m := PT.match(l.text)):
            return m.group(1), m.group(2)
    return None


def artist_text(lines: list[OcrLine]) -> str:
    """Texte du bas gauche de la carte (nom de l'illustrateur, après « Illus. » ou la brosse)."""
    return " ".join(l.text for l in lines if l.y > 0.88 and l.x < 0.5)


def detect_language(lines: list[OcrLine]) -> str | None:
    """'fr' / 'en' d'après les mots courants et les accents du texte, None si trop peu d'indices."""
    words = re.findall(r"[a-zA-Zàâçéèêëîïôûùüÿœ']+", " ".join(l.text for l in lines).lower())
    fr = sum(w in FR_WORDS for w in words) + 2 * sum(any(c in w for c in FR_ACCENTS) for w in words)
    en = sum(w in EN_WORDS for w in words)
    if fr + en < 2:
        return None
    return "fr" if fr > en else "en"
