"""Localisation de la carte dans l'image webcam et redressement (perspective) en 630x880."""
import cv2
import numpy as np

from . import card_rect

CARD_W, CARD_H = 630, 880
RATIO = 63 / 88
MIN_DETAIL = 0.03  # part de pixels de contour à l'intérieur : une carte (illustration, texte) en a 13 % et plus,
                   # un rectangle uni (panneau de carton de la boîte, aux proportions d'une carte) presque 0
EDGE_MARGIN = 3   # pixels (image réduite) : un quadrilatère qui touche le bord de l'image n'est pas la carte


def _order(pts: np.ndarray) -> np.ndarray:
    """Coins dans l'ordre haut-gauche, haut-droit, bas-droit, bas-gauche."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def _score(quad: np.ndarray, frame_shape: tuple[int, int]) -> float | None:
    frame_h, frame_w = frame_shape
    frame_area = frame_h * frame_w
    # Contour coupé par le bord de l'image (fond, tapis, boîte entière) : il peut avoir par hasard les proportions d'une
    # carte et, plus grand qu'elle, l'emporter sur la vraie carte posée dans la boîte.
    xs, ys = quad[:, 0], quad[:, 1]
    if (xs.min() < EDGE_MARGIN or ys.min() < EDGE_MARGIN
            or xs.max() > frame_w - 1 - EDGE_MARGIN or ys.max() > frame_h - 1 - EDGE_MARGIN):
        return None
    rect = cv2.minAreaRect(quad.astype(np.float32))
    w, h = sorted(rect[1])
    if h == 0:
        return None
    area = w * h
    if not 0.02 * frame_area < area < 0.9 * frame_area:
        return None
    ratio_err = abs(w / h - RATIO) / RATIO
    if ratio_err > 0.12:
        return None
    # Rectangularité : le contour doit remplir son rectangle englobant.
    fill = cv2.contourArea(quad.astype(np.float32)) / area
    if fill < 0.85:
        return None
    return area * (1 - ratio_err) * fill


def _has_detail(small: np.ndarray, quad: np.ndarray) -> bool:
    """La surface délimitée contient-elle un contenu de carte (et pas un fond uni) ?"""
    gray = cv2.cvtColor(warp(small, _order(quad), 176), cv2.COLOR_BGR2GRAY)
    inner = gray[18:-18, 13:-13]   # sans la bordure
    return (cv2.Canny(cv2.GaussianBlur(inner, (3, 3), 0), 40, 120) > 0).mean() >= MIN_DETAIL


def find_card(frame: np.ndarray) -> np.ndarray | None:
    """Retourne les 4 coins (ordonnés) du meilleur candidat carte, ou None."""
    h, w = frame.shape[:2]
    scale = 960 / max(h, w)
    small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame.copy()
    scale = min(scale, 1.0)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    candidates = []
    area = small.shape[0] * small.shape[1]
    edges_list = [cv2.Canny(gray, lo, hi) for lo, hi in ((30, 90), (60, 180))]
    # Bords sombres de la carte : seuillage adaptatif en complément de Canny.
    edges_list.append(cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 10))
    for edges in edges_list:
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            if cv2.contourArea(c) < 0.02 * area:
                continue
            peri = cv2.arcLength(c, True)
            for eps in (0.02, 0.04):
                approx = cv2.approxPolyDP(c, eps * peri, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    sc = _score(approx.reshape(4, 2), small.shape[:2])
                    if sc:
                        candidates.append((sc, approx.reshape(4, 2)))
                    break
    best = next((q for _, q in sorted(candidates, key=lambda c: -c[0]) if _has_detail(small, q)), None)
    if best is None:
        # Contours fusionnés avec la boîte ou la pile de cartes : on cherche plutôt un rectangle bien soutenu par des bords.
        rect = card_rect.find_rect(small)
        return None if rect is None or not _has_detail(small, rect) else _order(rect / scale)
    return _order(best / scale)


def _portrait(corners: np.ndarray) -> np.ndarray:
    """Coins dans l'ordre de la carte remise en portrait. Carte posée en paysage : son haut (le titre) est supposé
    tourné vers la gauche de l'image ; dans l'autre sens, la relecture à 180° la rattrape (une lecture OCR de plus)."""
    tl, tr, br, bl = corners
    if np.linalg.norm(tr - tl) > np.linalg.norm(bl - tl):
        return np.array([bl, tl, tr, br], dtype=np.float32)
    return np.asarray(corners, dtype=np.float32)


def native_height(corners: np.ndarray) -> int:
    """Hauteur de la carte dans l'image source (pixels), pour la redresser sans perdre de détail."""
    tl, tr, br, bl = _portrait(corners)
    return int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))


def warp(frame: np.ndarray, corners: np.ndarray, height: int = CARD_H) -> np.ndarray:
    """Carte redressée en portrait, `height` pixels de haut (630x880 par défaut)."""
    width = round(height * CARD_W / CARD_H)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(_portrait(corners), dst)
    return cv2.warpPerspective(frame, m, (width, height))


def extract(frame: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
    corners = find_card(frame)
    if corners is None:
        return None, None
    return warp(frame, corners), corners
