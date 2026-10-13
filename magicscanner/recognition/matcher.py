"""Comparaison visuelle entre la carte scannée (redressée) et les images Scryfall des impressions candidates.

Les rééditions partagent souvent l'illustration : ce qui les distingue, c'est le cadre (couleurs, mise en page)
et le symbole d'édition. On combine donc une corrélation globale basse résolution (cadre) et une recherche
du symbole d'édition par template matching.
"""
import hashlib
from pathlib import Path

import cv2
import httpx
import numpy as np

from ..config import IMAGE_CACHE, SCRYFALL_UA
from .detect import CARD_H, CARD_W

_client = httpx.Client(headers=SCRYFALL_UA, timeout=20, follow_redirects=True)


def fetch_image(url: str) -> np.ndarray | None:
    path = IMAGE_CACHE / (hashlib.sha1(url.split("?")[0].encode()).hexdigest() + ".jpg")
    if not path.exists():
        try:
            r = _client.get(url)
            r.raise_for_status()
        except httpx.HTTPError:
            return None
        path.write_bytes(r.content)
    img = cv2.imread(str(path))
    if img is None:
        return None
    # Les images Scryfall ont des coins arrondis et une marge de bordure proche de nos cartes redressées.
    return cv2.resize(img, (CARD_W, CARD_H), interpolation=cv2.INTER_AREA)


def _norm_gray(img: np.ndarray, size=(126, 176)) -> np.ndarray:
    g = cv2.cvtColor(cv2.resize(img, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(g)
    g = cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32)
    return (g - g.mean()) / (g.std() + 1e-6)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    return float((a * b).mean())


def _hue_hist(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(cv2.resize(img, (126, 176)), cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], None, [18, 8], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


# Zone du symbole d'édition (à droite de la ligne de type), en fraction de la carte, élargie pour tous les cadres.
SYMBOL_ZONE = (0.52, 0.66, 0.78, 0.98)  # y0, y1, x0, x1


def _symbol_score(scan: np.ndarray, ref: np.ndarray) -> float:
    y0, y1, x0, x1 = SYMBOL_ZONE
    zone = scan[int(y0 * CARD_H):int(y1 * CARD_H), int(x0 * CARD_W):int(x1 * CARD_W)]
    # Le template : symbole de la référence, recadré plus serré, cherché dans la zone du scan (tolère le décalage).
    ref_zone = ref[int(y0 * CARD_H):int(y1 * CARD_H), int(x0 * CARD_W):int(x1 * CARD_W)]
    g_ref = cv2.cvtColor(ref_zone, cv2.COLOR_BGR2GRAY)
    # Localise le symbole dans la référence : région la plus contrastée.
    edges = cv2.Canny(g_ref, 50, 150)
    ys, xs = np.nonzero(edges)
    if len(xs) < 20:
        return 0.0
    cx, cy = int(np.median(xs)), int(np.median(ys))
    r = 26
    tpl = g_ref[max(cy - r, 0):cy + r, max(cx - r, 0):cx + r]
    g_scan = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
    if tpl.shape[0] > g_scan.shape[0] or tpl.shape[1] > g_scan.shape[1] or tpl.size == 0:
        return 0.0
    best = 0.0
    for scale in (0.9, 1.0, 1.1):
        t = cv2.resize(tpl, None, fx=scale, fy=scale)
        if t.shape[0] >= g_scan.shape[0] or t.shape[1] >= g_scan.shape[1]:
            continue
        res = cv2.matchTemplate(g_scan, t, cv2.TM_CCOEFF_NORMED)
        best = max(best, float(res.max()))
    return best


def similarity(scan: np.ndarray, ref: np.ndarray) -> dict:
    glob = _corr(_norm_gray(scan), _norm_gray(ref))
    color = float(cv2.compareHist(_hue_hist(scan), _hue_hist(ref), cv2.HISTCMP_CORREL))
    sym = _symbol_score(scan, ref)
    return {"global": glob, "color": color, "symbol": sym, "score": 0.5 * glob + 0.2 * color + 0.3 * sym}
