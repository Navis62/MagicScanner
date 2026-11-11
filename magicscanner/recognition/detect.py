"""Localisation de la carte dans l'image webcam et redressement (perspective) en 630x880."""
import cv2
import numpy as np

from . import card_rect

CARD_W, CARD_H = 630, 880
RATIO = 63 / 88
MIN_DETAIL = 0.03  # part de pixels de contour à l'intérieur : une carte (illustration, texte) en a 13 % et plus,
                   # un rectangle uni (panneau de carton de la boîte, aux proportions d'une carte) presque 0
EDGE_MARGIN = 3   # pixels (image réduite) : un quadrilatère qui touche le bord de l'image n'est pas la carte
RATIO_TOL = 0.16  # écart de proportions admis : caméra en biais au-dessus de la boîte, la carte couchée apparaît en
                  # trapèze dont le rectangle englobant s'écarte de 13 à 14 % des proportions d'une carte
NESTED_MAX = 0.8  # rectangle de secours qui contient un cadre de carte plus petit que ça (en surface) : c'est
                  # l'intérieur de la boîte autour de la carte (photos de pile : ~0,5 ; une carte et son cadre : ~1)
# Cadre de l'illustration dans la carte (gauche, haut, droite, bas en fractions), le même à ~1 % près de 8th Edition aux
# cadres M15 (mesuré sur les images Scryfall de 10E, RAV, M10, M14, KTK, MM2, EMA).
ART_BOX = (0.08, 0.114, 0.922, 0.557)


def order(pts: np.ndarray) -> np.ndarray:
    """Coins dans l'ordre haut-gauche, haut-droit, bas-droit, bas-gauche."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype=np.float32)


def _inside(quad: np.ndarray, frame_shape: tuple[int, int]) -> bool:
    """Le quadrilatère ne touche pas le bord de l'image."""
    frame_h, frame_w = frame_shape
    xs, ys = quad[:, 0], quad[:, 1]
    return (xs.min() >= EDGE_MARGIN and ys.min() >= EDGE_MARGIN
            and xs.max() <= frame_w - 1 - EDGE_MARGIN and ys.max() <= frame_h - 1 - EDGE_MARGIN)


def _score(quad: np.ndarray, frame_shape: tuple[int, int]) -> float | None:
    frame_h, frame_w = frame_shape
    frame_area = frame_h * frame_w
    # Contour coupé par le bord de l'image (fond, tapis, boîte entière) : il peut avoir par hasard les proportions d'une
    # carte et, plus grand qu'elle, l'emporter sur la vraie carte posée dans la boîte.
    if not _inside(quad, frame_shape):
        return None
    rect = cv2.minAreaRect(quad.astype(np.float32))
    w, h = sorted(rect[1])
    if h == 0:
        return None
    area = w * h
    if not 0.02 * frame_area < area < 0.9 * frame_area:
        return None
    ratio_err = abs(w / h - RATIO) / RATIO
    if ratio_err > RATIO_TOL:
        return None
    # Rectangularité : le contour doit remplir son rectangle englobant.
    fill = cv2.contourArea(quad.astype(np.float32)) / area
    if fill < 0.85:
        return None
    return area * (1 - ratio_err) * fill


def _oriented(quad: np.ndarray, orientation: str | None) -> bool:
    """Le quadrilatère est-il couché dans le sens attendu de la carte ? Le cadre de l'illustration (1,36 de large pour 1
    de haut) a, tourné d'un quart de tour, les proportions d'une carte : quand le bord de la carte se perd dans la pile,
    c'est lui qui l'emportait. Il est perpendiculaire à la carte : un contour dans l'autre sens n'est pas elle."""
    if orientation is None:
        return True
    q = order(quad)
    across = np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])
    down = np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])
    return (across > down) == (orientation == "landscape")


def _card_around_art(art: np.ndarray, orientation: str) -> np.ndarray:
    """Coins de la carte déduits du cadre de son illustration (titre à gauche de l'image si elle est couchée)."""
    q = order(art)
    in_card = q[[3, 0, 1, 2]] if orientation == "landscape" else q   # coins de l'illustration dans l'ordre de la carte
    x0, y0, x1, y1 = ART_BOX
    m = cv2.getPerspectiveTransform(np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]), in_card)
    return order(cv2.perspectiveTransform(np.float32([[[0, 0]], [[1, 0]], [[1, 1]], [[0, 1]]]), m).reshape(4, 2))


def _has_detail(small: np.ndarray, quad: np.ndarray) -> bool:
    """La surface délimitée contient-elle un contenu de carte (et pas un fond uni) ?"""
    gray = cv2.cvtColor(warp(small, order(quad), 176), cv2.COLOR_BGR2GRAY)
    inner = gray[18:-18, 13:-13]   # sans la bordure
    return (cv2.Canny(cv2.GaussianBlur(inner, (3, 3), 0), 40, 120) > 0).mean() >= MIN_DETAIL


def _nested(inner: np.ndarray, outer: np.ndarray) -> bool:
    """`inner` est-il dans `outer` (son centre ; il peut déborder un peu sur une paroi) et nettement plus petit ?"""
    poly = order(outer).reshape(-1, 1, 2)
    cx, cy = inner.reshape(4, 2).mean(0)
    return (cv2.pointPolygonTest(poly, (float(cx), float(cy)), False) >= 0
            and cv2.contourArea(order(inner)) < NESTED_MAX * cv2.contourArea(poly))


EXPAND_REACH = 0.3   # recherche du bord extérieur jusqu'à 30 % du petit côté (bandeau du titre compris)
EXPAND_JUMP = 35     # saut de luminosité (sur 4 px) entre la bordure noire et le fond clair
EXPAND_DARK = 90     # luminosité moyenne maximale de la bande traversée (bordure / cadre noir)
EXPAND_LIGHT = 30    # au-delà du saut, le fond reste plus clair que la bande d'au moins ça (pas une lettre du titre)
EXPAND_SAMPLES = 31  # points de mesure le long de chaque côté
EXPAND_MIN_HITS = 0.4  # part des points où le bord est trouvé pour que le côté compte
EXPAND_RATIO = 0.10  # tolérance sur les proportions du quadrilatère agrandi quand un côté est déduit des proportions
                     # (quatre bords réellement trouvés : RATIO_TOL, la caméra en biais en fait un trapèze)


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
    q = order(quad)
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


def _check(gray: np.ndarray, q: np.ndarray, lines, tol: float = EXPAND_RATIO) -> np.ndarray | None:
    """Quadrilatère formé par les quatre droites, s'il a les proportions d'une carte et contient la zone de départ."""
    corners = [_intersect(lines[i - 1], lines[i]) for i in range(4)]
    if any(c is None for c in corners):
        return None
    grown = order(np.float32(corners))
    w, h = sorted(cv2.minAreaRect(grown)[1])
    if (h == 0 or abs(w / h - RATIO) / RATIO > tol or _score(grown, gray.shape[:2]) is None
            or cv2.contourArea(grown) < 0.9 * cv2.contourArea(q)):
        return None
    return grown


def _grown(gray, q, lines):
    """Les quatre bords trouvés."""
    return None if any(l is None for l in lines) else _check(gray, q, lines, RATIO_TOL)


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


def _quad(shape: np.ndarray) -> np.ndarray | None:
    """Quadrilatère convexe approchant le contour (4 coins), ou None."""
    peri = cv2.arcLength(shape, True)
    for eps in (0.02, 0.04):
        approx = cv2.approxPolyDP(shape, eps * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return approx.reshape(4, 2)
    return None


def find_card(frame: np.ndarray, orientation: str | None = None) -> np.ndarray | None:
    """Retourne les 4 coins (ordonnés) du meilleur candidat carte, ou None. `orientation` ("portrait", "landscape" ou
    None) : sens de la carte dans l'image, pour la recherche de secours."""
    h, w = frame.shape[:2]
    scale = 960 / max(h, w)
    small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame.copy()
    scale = min(scale, 1.0)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    candidates, hulls, arts = [], [], []
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
            quad, found = _quad(c), candidates
            if quad is None:
                # Pas 4 coins nets : le cadre coloré d'une carte posée sur une pile (son bord noir se perd dans la
                # tranche noire des cartes du dessous), d'où dépasse la boîte de force / endurance. Son enveloppe
                # convexe en a 4 ; elle ne sert qu'à défaut d'un vrai contour (moins précise), `_expand` l'agrandit
                # ensuite jusqu'au bord de la carte.
                quad, found = _quad(cv2.convexHull(c)), hulls
            if quad is not None and (sc := _score(quad, small.shape[:2])):
                (found if _oriented(quad, orientation) else arts).append((sc, quad))
    best = next((q for _, q in sorted(candidates, key=lambda c: -c[0]) if _has_detail(small, q)), None)
    if best is None and orientation is not None:
        # Contour dans l'autre sens que la carte : le cadre de son illustration. La carte est autour ; ses proportions
        # sont justes par construction (une caméra en biais en fait un trapèze que `_score` refuserait).
        around = (_card_around_art(q, orientation) for _, q in sorted(arts, key=lambda c: -c[0]))
        best = next((c for c in around if _inside(c, small.shape[:2]) and _has_detail(small, c)), None)
    if best is None:
        # Contours fusionnés avec la boîte ou la pile de cartes : on cherche plutôt un rectangle bien soutenu par des
        # bords. S'il contient le cadre coloré d'une carte (enveloppe convexe) bien plus petit que lui, c'est l'intérieur
        # de la boîte autour d'elle : la carte est ce cadre.
        rect = card_rect.find_rect(small, orientation)
        hull = next((q for _, q in sorted(hulls, key=lambda c: -c[0]) if _has_detail(small, q)), None)
        best = hull if hull is not None and (rect is None or _nested(hull, rect)) else rect
        if best is None or not _has_detail(small, best):
            return None
    return order(_expand(gray, best.astype(np.float32)) / scale)


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
