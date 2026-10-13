"""Détection du symbole « The List » : l'étincelle de Planeswalker, dans la bordure noire en bas à gauche.

Les cartes The List sont identiques à leur impression d'origine (même cadre, même numéro, même code d'édition)
sauf pour ce petit symbole, au même endroit quelle que soit l'époque du cadre. C'est donc le seul indice visuel
qui les distingue de l'original (extension Cardmarket et prix différents).

Gabarit : assets/list_symbol.png, recadré sur l'étincelle d'une image Scryfall « large » de The List
(Angel of Vitality, M20-4), ramené à 630×880 comme nos cartes redressées.
"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from .detect import CARD_H, CARD_W

TEMPLATE_PATH = Path(__file__).parent / "assets" / "list_symbol.png"

# Zone de recherche (en pixels d'une carte 630×880) : bordure noire en bas à gauche, hors du coin arrondi blanc
# (en dessous) et du début du numéro de collection (à droite).
ROI = (10, 48, 814, 858)           # x0, x1, y0, y1
SCALES = (0.85, 1.0, 1.18)         # tolère une carte un peu plus loin / plus près que prévu
MIN_CONTRAST = 45.0                # écart de gris attendu entre l'étincelle et la bordure (sur 255)

# Seuils mesurés sur 240 paires « The List / impression d'origine » dégradées comme une webcam (flou, bruit,
# compression, luminosité, décalage de ±5 px du redressement) : à 0,70, 99 % des cartes The List sont détectées
# pour 0 % de fausses alertes ; en dessous de 0,45 on est quasi certain qu'il n'y a pas de symbole.
PRESENT = 0.70
ABSENT = 0.45


@lru_cache(maxsize=1)
def _template() -> np.ndarray:
    tpl = cv2.imread(str(TEMPLATE_PATH), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        raise FileNotFoundError(TEMPLATE_PATH)
    return tpl


def _as_seen_by_webcam(tpl: np.ndarray) -> np.ndarray:
    """Le gabarit vient d'une image nette ; la carte scannée a été réduite par la caméra puis agrandie au
    redressement (≈ ×1,8). On applique le même flou au gabarit pour que les deux se ressemblent."""
    small = cv2.resize(tpl, None, fx=0.55, fy=0.55, interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(cv2.resize(small, tpl.shape[::-1], interpolation=cv2.INTER_LINEAR), (3, 3), 0)


def _match(zone: np.ndarray) -> tuple[float, float]:
    """(corrélation, contraste) au meilleur emplacement : le contraste est l'écart de luminosité entre l'étincelle
    (zone claire du gabarit) et son entourage, en niveaux de gris."""
    tpl = _as_seen_by_webcam(_template())
    best_corr, best_contrast = -1.0, 0.0
    for s in SCALES:
        t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        if t.shape[0] >= zone.shape[0] or t.shape[1] >= zone.shape[1]:
            continue
        res = cv2.matchTemplate(zone, t, cv2.TM_CCOEFF_NORMED)
        _, corr, _, (x, y) = cv2.minMaxLoc(res)
        if corr > best_corr:
            patch = zone[y:y + t.shape[0], x:x + t.shape[1]].astype(np.float32)
            bright = t > 0.5 * float(t.max())
            best_corr = float(corr)
            best_contrast = float(patch[bright].mean() - patch[~bright].mean()) if bright.any() and (~bright).any() else 0.0
    return best_corr, best_contrast


def symbol_score(card: np.ndarray) -> float:
    """Confiance (0-1) que l'étincelle The List est présente : corrélation de forme, ramenée vers 0 quand le
    contraste est trop faible pour être une étincelle blanche sur la bordure noire (simple bruit ou reflet)."""
    if card.shape[:2] != (CARD_H, CARD_W):
        card = cv2.resize(card, (CARD_W, CARD_H))
    x0, x1, y0, y1 = ROI
    gray = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY) if card.ndim == 3 else card
    corr, contrast = _match(gray[y0:y1, x0:x1])
    return max(corr, 0.0) * min(1.0, max(contrast, 0.0) / MIN_CONTRAST)


def evidence(score: float) -> float:
    """Score -> indice signé : +1 symbole présent, -1 absent, entre les deux interpolé (cas douteux)."""
    return max(-1.0, min(1.0, (score - (PRESENT + ABSENT) / 2) / ((PRESENT - ABSENT) / 2)))
