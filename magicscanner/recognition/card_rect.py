"""Recherche d'une carte par le soutien de ses bords : méthode de secours quand les contours ne donnent pas un
quadrilatère propre (carte collée à la paroi de la boîte, cartes empilées dont les bords débordent, bord noir qui
se fond dans l'ombre).

On cherche le rectangle aux proportions d'une carte dont les quatre côtés sont le mieux couverts par des bords
visibles (Canny). Ça ne dépend pas de la forme globale des contours, donc des objets voisins qui fusionnent avec elle.
Pour tenir compte d'une carte penchée, l'image de bords est testée sous quelques rotations.
"""
import cv2
import numpy as np

RATIO = 63 / 88          # largeur / hauteur d'une carte
DELTA = 0.09             # tolérance sur les proportions (perspective, léger penchement)
TOL = 2                  # un bord compte s'il est à ±2 px de la ligne testée (image réduite)
ANGLES = range(-12, 13, 3)
PEAKS = 14               # lignes les plus marquées retenues par axe
MIN_HEIGHT = 0.25        # la carte fait au moins le quart de la hauteur de l'image (sinon : un bout de texte, une vignette…)
MIN_SCORE = 0.60         # soutien (mélange moyenne / pire côté) pour qu'un rectangle soit retenu
MIN_SIDE = 0.45          # chaque côté doit être soutenu au moins aux deux cinquièmes
CANNY = (40, 120)


def _peaks(profile: np.ndarray, count: int, min_dist: int = 6) -> list[int]:
    p = cv2.GaussianBlur(profile.astype(np.float32).reshape(-1, 1), (1, 5), 0).ravel()
    out = []
    for _ in range(count):
        i = int(p.argmax())
        if p[i] <= 0:
            break
        out.append(i)
        p[max(0, i - min_dist):i + min_dist + 1] = 0
    return out


class _Support:
    """Soutien des côtés d'un rectangle aligné sur les axes, en O(1) grâce aux sommes cumulées."""

    def __init__(self, edges: np.ndarray):
        e = edges > 0
        vertical = np.maximum.reduce([np.roll(e, s, axis=1) for s in range(-TOL, TOL + 1)]).astype(np.int32)
        horizontal = np.maximum.reduce([np.roll(e, s, axis=0) for s in range(-TOL, TOL + 1)]).astype(np.int32)
        h, w = e.shape
        self.edges = e
        self.down = np.zeros((h + 1, w), np.int32)      # down[y, x] : bords verticaux de la colonne x au-dessus de y
        self.down[1:] = np.cumsum(vertical, axis=0)
        self.right = np.zeros((h, w + 1), np.int32)     # right[y, x] : bords horizontaux de la ligne y à gauche de x
        self.right[:, 1:] = np.cumsum(horizontal, axis=1)

    def sides(self, xa, xb, y1, y2) -> np.ndarray:
        """(4, n) : gauche, droite, haut, bas ; part de chaque côté couverte par des bords (0-1)."""
        height, width = (y2 - y1).astype(np.float32), (xb - xa).astype(np.float32)
        return np.stack([
            (self.down[y2, xa] - self.down[y1, xa]) / height, (self.down[y2, xb] - self.down[y1, xb]) / height,
            (self.right[y1, xb] - self.right[y1, xa]) / width, (self.right[y2, xb] - self.right[y2, xa]) / width,
        ])


def _score(sides: np.ndarray) -> np.ndarray:
    return 0.5 * sides.min(0) + 0.5 * sides.mean(0)


def _best_aligned(edges: np.ndarray):
    """Rectangle aux proportions de carte, côtés alignés sur les axes, qui maximise soutien × surface parmi ceux dont
    les quatre côtés sont assez soutenus : le cadre de l'illustration est souvent mieux dessiné que le bord noir de
    la carte, mais la carte est le plus grand rectangle de ses proportions qui reste bien dessiné.
    Renvoie (objectif, (xa, y1, xb, y2), côtés)."""
    h, w = edges.shape
    support = _Support(edges)
    best = (0.0, None, None)

    def consider(xa, xb, y1, y2):
        """Teste des rectangles (tableaux de même longueur) et retient le mieux soutenu."""
        nonlocal best
        if len(y1) == 0:
            return
        sides = support.sides(xa, xb, y1, y2)
        score = _score(sides)
        area = (xb - xa) * (y2 - y1) / float(w * h)
        objective = np.where((score >= MIN_SCORE) & (sides.min(0) >= MIN_SIDE), score * area, 0.0)
        i = int(objective.argmax())
        if objective[i] > best[0]:
            best = (float(objective[i]), (int(xa[i]), int(y1[i]), int(xb[i]), int(y2[i])), sides[:, i])

    e = edges > 0
    cols, rows = _peaks(e.sum(0), PEAKS), _peaks(e.sum(1), PEAKS)
    # Deux colonnes marquées -> le haut est testé à toutes les hauteurs, le bas se déduit des proportions.
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            xa, xb = sorted((a, b))
            width = xb - xa
            heights = np.arange(max(int(width / RATIO * (1 - DELTA)), int(MIN_HEIGHT * h)), int(width / RATIO * (1 + DELTA)) + 1)
            if len(heights) == 0:
                continue
            y1 = np.repeat(np.arange(h), len(heights))
            y2 = y1 + np.tile(heights, h)
            ok = y2 < h
            consider(np.full(ok.sum(), xa), np.full(ok.sum(), xb), y1[ok], y2[ok])
    # Deux lignes marquées -> la gauche est testée partout, la droite se déduit des proportions.
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            y1, y2 = sorted((a, b))
            height = y2 - y1
            if height < MIN_HEIGHT * h:
                continue
            for width in range(int(height * RATIO * (1 - DELTA)), int(height * RATIO * (1 + DELTA)) + 1, 2):
                xa = np.arange(0, w - width)
                if len(xa) == 0:
                    continue
                consider(xa, xa + width, np.full(len(xa), y1), np.full(len(xa), y2))
    return best


def find_rect(small_bgr: np.ndarray) -> np.ndarray | None:
    """Coins (haut-gauche, haut-droit, bas-droit, bas-gauche) de la carte dans l'image réduite, ou None."""
    gray = cv2.GaussianBlur(cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.Canny(gray, *CANNY)
    h, w = edges.shape
    best = (0.0, None, None, 0)
    for angle in ANGLES:
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rotated = cv2.warpAffine(edges, m, (w, h), flags=cv2.INTER_NEAREST)
        score, rect, sides = _best_aligned(rotated)
        if score > best[0]:
            best = (score, rect, sides, angle)
    _, rect, _, angle = best
    if rect is None:
        return None
    xa, y1, xb, y2 = rect
    back = cv2.invertAffineTransform(cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0))
    corners = np.float32([[xa, y1], [xb, y1], [xb, y2], [xa, y2]])
    return (np.hstack([corners, np.ones((4, 1), np.float32)]) @ back.T).astype(np.float32)
