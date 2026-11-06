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


EXPAND_REACH = 0.3   # recherche du bord extérieur jusqu'à 30 % du petit côté (bandeau du titre compris)
EXPAND_JUMP = 35     # saut de luminosité (sur 4 px) entre la bordure noire et le fond clair
EXPAND_DARK = 90     # luminosité moyenne maximale de la bande traversée (bordure / cadre noir)
EXPAND_LIGHT = 30    # au-delà du saut, le fond reste plus clair que la bande d'au moins ça (pas une lettre du titre)
EXPAND_SAMPLES = 31  # points de mesure le long de chaque côté
EXPAND_MIN_HITS = 0.4  # part des points où le bord est trouvé pour que le côté compte
EXPAND_RATIO = 0.06  # tolérance sur les proportions du quadrilatère agrandi


def _outer_edge(gray: np.ndarray, a: np.ndarray, b: np.ndarray, n: np.ndarray, reach: int):
    """Bord de la carte au-delà du côté a-b (vers l'extérieur `n`) : en chaque point de mesure, le premier passage
    d'une bande sombre (bordure, cadre noir) à un fond clair qui le reste ; une droite est ajustée sur ces points.
    Renvoie (point, direction) ou None si le bord n'est pas net (côté collé à la paroi ombrée, à la pile de cartes)."""
    offs = np.arange(0, reach + 12)
    base = a + np.outer(np.linspace(0.1, 0.9, EXPAND_SAMPLES), b - a)
    pts = (base[:, None] + offs[None, :, None] * n).astype(np.float32)          # (points, décalages, 2)
    prof = cv2.remap(gray, pts[..., 0], pts[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    hits = []
    for i, row in enumerate(prof):
        dark = np.cumsum(row) / np.arange(1, len(row) + 1)                       # moyenne de la bande [0, j]
        for j in range(2, reach):
            if (row[j + 2] - row[j - 2] >= EXPAND_JUMP and dark[j] <= EXPAND_DARK
                    and row[j + 3:j + 11].min() >= dark[j] + EXPAND_LIGHT):
                hits.append(base[i] + j * n)
                break
    if len(hits) < EXPAND_MIN_HITS * EXPAND_SAMPLES:
        return None
    vx, vy, x0, y0 = cv2.fitLine(np.float32(hits), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    return np.float32([x0, y0]), np.float32([vx, vy])


def _intersect(l1, l2) -> np.ndarray | None:
    (p1, d1), (p2, d2) = l1, l2
    m = np.array([d1, -d2], np.float32).T
    if abs(np.linalg.det(m)) < 1e-6:
        return None
    return p1 + np.linalg.solve(m, p2 - p1)[0] * d1


def _expand(gray: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Agrandit le quadrilatère jusqu'au bord extérieur de la carte. Sur une carte noire, le cadre se confond avec la
    bordure : le contour le plus net est souvent l'intérieur du cadre (illustration + boîte de texte), aux proportions
    voisines d'une carte, et le titre reste dehors. Si l'extérieur est déjà le fond clair, le bord est trouvé tout de
    suite et rien ne change. Un côté sans bord net est placé d'après les proportions d'une carte."""
    q = _order(quad)
    center = q.mean(0)
    short = min(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[3] - q[0]))
    reach = int(EXPAND_REACH * short)
    normals, lines = [], []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        t = (b - a) / np.linalg.norm(b - a)
        n = np.array([-t[1], t[0]], np.float32)
        if np.dot(n, (a + b) / 2 - center) < 0:
            n = -n
        normals.append(n)
        lines.append(_outer_edge(gray, a, b, n, reach))
    grown = _grown(gray, q, lines)
    if grown is None:
        grown = _symmetric(gray, q, normals, lines)
    if grown is None:
        grown = _one_missing(gray, q, normals, lines)
    return quad if grown is None else grown


def _check(gray: np.ndarray, q: np.ndarray, lines) -> np.ndarray | None:
    """Quadrilatère formé par les quatre droites, s'il a les proportions d'une carte et contient la zone de départ."""
    corners = [_intersect(lines[i - 1], lines[i]) for i in range(4)]
    if any(c is None for c in corners):
        return None
    grown = _order(np.float32(corners))
    w, h = sorted(cv2.minAreaRect(grown)[1])
    if (h == 0 or abs(w / h - RATIO) / RATIO > EXPAND_RATIO or _score(grown, gray.shape[:2]) is None
            or cv2.contourArea(grown) < 0.9 * cv2.contourArea(q)):
        return None
    return grown


def _grown(gray, q, lines):
    """Les quatre bords trouvés."""
    return None if any(l is None for l in lines) else _check(gray, q, lines)


def _symmetric(gray, q, normals, lines):
    """Bords trouvés au-delà de la carte (pile de cartes noires, paroi dans l'ombre : du sombre continue après la
    bordure) : on garde le haut et le bas de la carte (petits côtés) et on place les grands côtés symétriquement autour
    de l'axe de la zone de départ, l'illustration et la boîte de texte étant centrées en largeur sur la carte."""
    long0 = np.linalg.norm(q[1] - q[0]) > np.linalg.norm(q[2] - q[1])   # côtés 0 et 2 = grands côtés ?
    short_ids, long_ids = ((1, 3), (0, 2)) if long0 else ((0, 2), (1, 3))
    if any(lines[i] is None for i in short_ids):
        return None
    l1, l3 = lines[short_ids[0]], lines[short_ids[1]]
    axis_dir = q[(long_ids[0] + 1) % 4] - q[long_ids[0]]                  # direction des grands côtés
    mid = q.mean(0)
    a, b = _intersect(l1, (mid, axis_dir)), _intersect(l3, (mid, axis_dir))
    if a is None or b is None:
        return None
    half = float(np.linalg.norm(a - b)) * RATIO / 2
    out = list(lines)
    for i in long_ids:
        out[i] = (mid + half * normals[i], axis_dir)
    return _check(gray, q, out)


def _one_missing(gray, q, normals, lines):
    """Un seul côté sans bord net : parallèle à l'opposé, à la distance que donnent les proportions d'une carte."""
    missing = [i for i, l in enumerate(lines) if l is None]
    if len(missing) != 1:
        return None
    i = missing[0]
    opp, s1, s3 = lines[(i + 2) % 4], lines[(i + 1) % 4], lines[(i + 3) % 4]
    c1, c3 = _intersect(s1, opp), _intersect(s3, opp)
    if c1 is None or c3 is None:
        return None
    along = float(np.linalg.norm(c1 - c3))                                      # longueur du côté opposé
    long_side = np.linalg.norm(q[(i + 1) % 4] - q[i]) > np.linalg.norm(q[(i + 2) % 4] - q[(i + 1) % 4])
    gap = along * RATIO if long_side else along / RATIO
    lines = list(lines)
    lines[i] = ((c1 + c3) / 2 - gap * normals[(i + 2) % 4], opp[1])
    return _check(gray, q, lines)


def find_card(frame: np.ndarray, orientation: str | None = None) -> np.ndarray | None:
    """Retourne les 4 coins (ordonnés) du meilleur candidat carte, ou None. `orientation` ("portrait", "landscape" ou
    None) : sens de la carte dans l'image, pour la recherche de secours."""
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
        best = card_rect.find_rect(small, orientation)
        if best is None or not _has_detail(small, best):
            return None
    return _order(_expand(gray, best.astype(np.float32)) / scale)


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


def _target(height: int) -> tuple[np.ndarray, int]:
    """Coins et largeur de la carte redressée en portrait, `height` pixels de haut."""
    width = round(height * CARD_W / CARD_H)
    return np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32), width


def warp(frame: np.ndarray, corners: np.ndarray, height: int = CARD_H) -> np.ndarray:
    """Carte redressée en portrait, `height` pixels de haut (630x880 par défaut)."""
    dst, width = _target(height)
    m = cv2.getPerspectiveTransform(_portrait(corners), dst)
    return cv2.warpPerspective(frame, m, (width, height))


def unwarp(corners: np.ndarray, height: int, points: np.ndarray) -> np.ndarray:
    """Points de la carte redressée par `warp(frame, corners, height)` -> points de l'image d'origine."""
    m = cv2.getPerspectiveTransform(_target(height)[0], _portrait(corners))
    return cv2.perspectiveTransform(np.float32(points).reshape(-1, 1, 2), m).reshape(-1, 2)


def extract(frame: np.ndarray, orientation: str | None = None) -> tuple[np.ndarray | None, np.ndarray | None]:
    corners = find_card(frame, orientation)
    if corners is None:
        return None, None
    return warp(frame, corners), corners
