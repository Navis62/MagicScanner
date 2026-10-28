"""Score d'une impression candidate : ressemblance visuelle + indices lus (numéro, code d'édition, symbole
The List) + vraisemblance."""
import sqlite3
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz

from ..catalog.lookup import normalize
from . import visual
from .ocr import CollectorInfo

LIST_SET = "plst"          # The List + Mystery Booster dans Scryfall : numéros « M20-4 » (édition d'origine - numéro)

# Poids de la ressemblance visuelle.
W_GLOBAL, W_SYMBOL, W_COLOR = 0.45, 0.45, 0.10
# Bonus / malus.
SET_CODE_READ = 0.50       # code d'édition lu en bas de carte (cadres récents)
NUMBER_SIMILAR = 0.25      # × similarité « numéro/total » lu vs attendu
NUMBER_EXACT = 0.15
NOT_PRINTED_IN_FR = -0.15  # carte lue en VF mais édition jamais imprimée en français (selon Scryfall)
COMMON_OR_UNCOMMON = 0.03  # le POC ne scanne que des communes / unco
PROMO = -0.08
SAME_SET_AS_PREVIOUS = 0.05  # les piles sont souvent triées par édition
NAME_WEIGHT = 0.20         # × (score du nom - 100 %)
PROMO_LIKE_SETS = {"sld", "prm", "mb2", "fmb1"}
# Étincelle (The List / Mystery Booster) : indice signé (+1 présente, -1 absente) × poids, réservé à l'édition plst. Le léger malus
# de départ la départage de l'original quand le symbole est douteux (les cartes ordinaires sont bien plus fréquentes).
LIST_WEIGHT = 0.60
LIST_PRIOR = -0.05
# Une impression qui n'existe pas dans la finition scannée (foil-only pour une carte non-foil : surge foil, etched… ;
# non-foil-only pour une carte foil) ne peut pas être la carte posée sous la caméra, même si son image est identique.
NOT_NONFOIL = -0.30

# Force / endurance lues : l'indice qui départage des tokens de même nom (une vingtaine d'« Elemental »).
PT_MATCH = 0.40
PT_MISMATCH = -0.40
ARTIST_MATCH = 0.10       # nom de l'illustrateur retrouvé dans le texte du bas de carte
TOKEN_LAYOUTS = {"token", "double_faced_token", "emblem"}
# Un token est une carte entièrement colorée : la couleur du cadre compte bien plus, et le symbole d'édition (petit) moins.
TOKEN_W_GLOBAL, TOKEN_W_SYMBOL, TOKEN_W_COLOR = 0.45, 0.15, 0.40


@dataclass(frozen=True)
class Evidence:
    """Ce qu'on sait de la carte scannée, commun à toutes les impressions candidates."""
    lang: str
    collector: CollectorInfo
    name_scores: dict[str, float]   # oracle_id -> score du nom (0-100)
    fr_sets: frozenset[str] | set[str]
    previous_set: str | None = None
    list_symbol: float = 0.0        # indice signé du symbole The List (cf. list_symbol.evidence)
    foil: bool = False              # case « foil » cochée au moment du scan
    power_toughness: tuple[str, str] | None = None   # force / endurance lues en bas à droite
    artist_text: str = ""           # texte lu en bas à gauche


@dataclass
class Candidate:
    card_id: str
    score: float
    visual: float
    reasons: list[str] = field(default_factory=list)
    cardmarket_id: int | None = None   # produit Cardmarket de l'impression (deux produits différents = annonces différentes)


def printed_identity(p: sqlite3.Row) -> tuple[str, str]:
    """(code d'édition, numéro) tels qu'imprimés sur la carte. Pour The List, c'est ceux de l'édition d'origine."""
    if p["set_code"] == LIST_SET and "-" in p["collector_number"]:
        code, number = p["collector_number"].split("-", 1)
        return code.lower(), number
    return p["set_code"], p["collector_number"]


def identity_score(p: sqlite3.Row, ev: Evidence) -> float:
    """Indices peu coûteux (pas d'image) : force/endurance et illustrateur. Sert aussi à écarter d'avance les candidats."""
    score = 0.0
    if ev.power_toughness and p["power"] is not None and p["toughness"] is not None:
        score += PT_MATCH if ev.power_toughness == (p["power"], p["toughness"]) else PT_MISMATCH
    if p["artist"] and len(p["artist"]) >= 5 and normalize(p["artist"]) in normalize(ev.artist_text):
        score += ARTIST_MATCH
    return score


def _best_visual(scan: np.ndarray, image_urls: list[str]) -> dict:
    best = {"score": 0.0, "global": 0.0, "symbol": 0.0, "color": 0.0}
    for url in image_urls:
        ref = visual.fetch_image(url)
        if ref is not None:
            sim = visual.similarity(scan, ref)
            if sim["score"] > best["score"]:
                best = sim
    return best


def score_printing(scan: np.ndarray, p: sqlite3.Row, ev: Evidence) -> Candidate:
    # Comparaison avec le scan Scryfall VF si dispo (même texte), sinon la VO.
    images = [u for u in ((p["fr_image"] if ev.lang == "fr" else None), p["image_normal"]) if u]
    vis = _best_visual(scan, images)
    if p["layout"] in TOKEN_LAYOUTS:
        score = TOKEN_W_GLOBAL * vis["global"] + TOKEN_W_SYMBOL * vis["symbol"] + TOKEN_W_COLOR * vis["color"]
    else:
        score = W_GLOBAL * vis["global"] + W_SYMBOL * vis["symbol"] + W_COLOR * vis["color"]
    score += identity_score(p, ev)
    reasons = []
    code, number = printed_identity(p)
    is_list = p["set_code"] == LIST_SET

    if ev.collector.set_code == code:
        score += SET_CODE_READ
        reasons.append("code édition lu")
    if ev.collector.number:
        if not is_list:   # pour The List on ne connaît pas le total imprimé (celui de l'édition d'origine)
            read = f"{ev.collector.number}/{ev.collector.total or ''}"
            expected = f"{number.lstrip('0')}/{p['set_size'] or ''}"
            score += NUMBER_SIMILAR * fuzz.ratio(read, expected) / 100
        if ev.collector.number == number.lstrip("0"):
            score += NUMBER_EXACT
            reasons.append("numéro lu")
    if is_list:
        score += LIST_WEIGHT * ev.list_symbol + LIST_PRIOR
        if ev.list_symbol > 0.5:
            reasons.append("étincelle The List / Mystery Booster")
    if p["finishes"] and not {"foil", "etched"} & set(p["finishes"].split(",")) if ev.foil             else p["finishes"] and "nonfoil" not in p["finishes"].split(","):
        score += NOT_NONFOIL
    if ev.lang == "fr" and p["set_code"] not in ev.fr_sets:
        score += NOT_PRINTED_IN_FR
    if p["rarity"] in ("common", "uncommon"):
        score += COMMON_OR_UNCOMMON
    if p["promo"] or p["set_code"] in PROMO_LIKE_SETS or p["set_type"] == "promo":
        score += PROMO
    if ev.previous_set and p["set_code"] == ev.previous_set:
        score += SAME_SET_AS_PREVIOUS
    score += NAME_WEIGHT * (ev.name_scores.get(p["oracle_id"], 0) / 100 - 1)

    return Candidate(p["id"], round(score, 4), round(vis["score"], 3), reasons, p["cardmarket_id"])
