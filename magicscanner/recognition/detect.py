"""Localisation de la carte dans l'image webcam et redressement (perspective) en 630x880."""
import cv2
import numpy as np

CARD_W, CARD_H = 630, 880
RATIO = 63 / 88


def _order(pts: np.ndarray) -> np.ndarray:
    """Coins dans l'ordre haut-gauche, haut-droit, bas-droit, bas-gauche."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def _score(quad: np.ndarray, frame_area: float) -> float | None:
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


def find_card(frame: np.ndarray) -> np.ndarray | None:
    """Retourne les 4 coins (ordonnés) du meilleur candidat carte, ou None."""
    h, w = frame.shape[:2]
    scale = 960 / max(h, w)
    small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame.copy()
    scale = min(scale, 1.0)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    best, best_score = None, 0.0
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
                    sc = _score(approx.reshape(4, 2), area)
                    if sc and sc > best_score:
                        best, best_score = approx.reshape(4, 2), sc
                    break
    if best is None:
        return None
    return _order(best / scale)


def warp(frame: np.ndarray, corners: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = corners
    # Carte posée en paysage : on la remet en portrait.
    if np.linalg.norm(tr - tl) > np.linalg.norm(bl - tl):
        corners = np.array([bl, tl, tr, br], dtype=np.float32)
    dst = np.array([[0, 0], [CARD_W - 1, 0], [CARD_W - 1, CARD_H - 1], [0, CARD_H - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(frame, m, (CARD_W, CARD_H))


def extract(frame: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
    corners = find_card(frame)
    if corners is None:
        return None, None
    return warp(frame, corners), corners
