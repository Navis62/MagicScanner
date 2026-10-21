"""Pipeline : détection de la carte -> OCR -> nom (VO/VF) -> impressions candidates -> score -> meilleure impression."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..catalog import Catalog, NameMatch
from . import detect, list_symbol, ocr
from .scoring import Candidate, Evidence, score_printing

NAME_TIE_MARGIN = 5     # noms gardés en lice s'ils sont à moins de 5 points du meilleur
MAX_ORACLES = 3
TITLE_FOUND = 92        # score minimal d'un nom lu dans l'image entière pour y repérer la carte
AMBIGUOUS_GAP = 0.15   # deux premières impressions plus proches que ça ET vendues dans des produits différents
OFF_SET_MARGIN = 8     # édition fixée : un nom hors édition ne l'emporte que s'il est lu nettement mieux


@dataclass
class Recognition:
    ok: bool
    error: str | None = None
    lang: str | None = None
    confidence: float = 0.0
    title: str | None = None
    lines: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)  # triés, le premier est retenu
    warped: np.ndarray | None = None
    corners: list | None = None
    list_symbol: float = 0.0   # confiance (0-1) que le symbole The List est présent
    ambiguous: bool = False    # le choix entre deux produits Cardmarket différents ne tient qu'à peu de chose
    off_set: bool = False      # une édition était fixée mais la carte n'en fait pas partie

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


def _confidence(name_score: float, candidates: list[Candidate]) -> float:
    """Confiance = qualité du nom × écart entre la 1re et la 2e impression."""
    second = candidates[1].score if len(candidates) > 1 else 0
    gap = candidates[0].score - second
    return round(min(1.0, (name_score / 100) * (0.5 + 2 * gap)), 3)


def _ambiguous(candidates: list[Candidate]) -> bool:
    """Se tromper entre deux impressions du même produit Cardmarket est sans conséquence ; entre deux produits
    différents, l'annonce serait créée sur la mauvaise page."""
    if len(candidates) < 2:
        return False
    first, second = candidates[0], candidates[1]
    return first.score - second.score < AMBIGUOUS_GAP and first.cardmarket_id != second.cardmarket_id


class Recognizer:
    def __init__(self, catalog: Catalog, engine: ocr.OcrEngine | None = None):
        self.catalog = catalog
        self.ocr = engine or ocr.OcrEngine()
        self._pool = ThreadPoolExecutor(8)  # téléchargement / comparaison des images candidates

    def _match_names(self, texts: list[str], locked_set: str | None) -> list[NameMatch]:
        """Noms correspondant aux textes lus. Édition fixée : on cherche d'abord parmi ses cartes (bien moins de
        confusions possibles) ; une carte d'une autre édition glissée dans le paquet n'est retenue que si son nom est
        lu nettement mieux que le meilleur nom de l'édition."""
        found = self.catalog.match_names(texts)
        if not locked_set:
            return found
        in_set = self.catalog.match_names(texts, set_code=locked_set)
        if in_set and (not found or in_set[0].score >= found[0].score - OFF_SET_MARGIN):
            return in_set
        return found

    def _read_card(self, card: np.ndarray, locked_set: str | None = None
                   ) -> tuple[np.ndarray, list[ocr.OcrLine], list[str], list[NameMatch]]:
        """OCR + nom ; si rien ne correspond, la carte est peut-être à l'envers : on retourne et on relit."""
        attempt = None
        for img in (card, cv2.rotate(card, cv2.ROTATE_180)):
            lines = self.ocr.read(img)
            titles = ocr.title_candidates(lines)
            matches = self._match_names(titles, locked_set) if titles else []
            attempt = attempt or (img, lines, titles, matches)
            if matches:
                return img, lines, titles, matches
        return attempt

    def _locate_by_text(self, frame: np.ndarray, locked_set: str | None = None):
        """Dernier recours : lit toute l'image, repère une ligne qui est un nom de carte (bandeau du titre) et déduit la
        position de la carte d'une ligne du bas. Quelle ligne est « le bas » est incertain (cartes à bascule : nom
        retourné, texte décalé) : on propose plusieurs positions, de la plus plausible à la moins plausible."""
        lines = self.ocr.read_pixels(frame)
        titles = [(m[0].score, -l.y, l) for l in lines
                  if len(l.text) >= 4 and (m := self._match_names([l.text], locked_set)) and m[0].score >= TITLE_FOUND]
        for _, _, title in sorted(titles, key=lambda t: t[:2], reverse=True):
            below = [l for l in lines if l.y > title.y + 6 * title.height]
            aligned = [l for l in below if abs(l.x - title.x) < 0.15 * (l.y - title.y)]
            others = [l for l in below if l not in aligned]
            for footer in (sorted(aligned, key=lambda l: -l.y) + sorted(others, key=lambda l: -l.y))[:4]:
                if (corners := ocr.card_from_title(title, footer)) is not None:
                    yield corners

    def recognize(self, frame: np.ndarray, previous_set: str | None = None, foil: bool = False,
                  locked_set: str | None = None) -> Recognition:
        """`locked_set` : édition fixée (paquet d'une seule édition) ; seules ses impressions sont envisagées, sauf si la
        carte n'en fait manifestement pas partie."""
        card, corners = detect.extract(frame)
        if card is not None:
            card, lines, titles, matches = self._read_card(card, locked_set)
        if card is None or not matches:
            # Contour introuvable ou mal choisi (bord noir dans l'ombre) : on retrouve la carte par son texte.
            first = None
            for located in self._locate_by_text(frame, locked_set):
                attempt = self._read_card(detect.warp(frame, located), locked_set)
                first = first or (attempt, located)
                if attempt[3]:
                    (card, lines, titles, matches), corners = attempt, located
                    break
            else:
                if first is not None and card is None:
                    (card, lines, titles, matches), corners = first
        if card is None:
            return Recognition(False, "Carte non détectée : vérifie le cadrage / l'éclairage")
        rec = Recognition(False, warped=card, corners=corners.tolist(), lines=[l.text for l in lines],
                          title=titles[0] if titles else None)
        if not matches:
            rec.error = f"Aucune carte ne correspond à « {titles[0]} »" if titles else "Nom illisible"
            return rec

        rec.list_symbol = round(list_symbol.symbol_score(card), 3)
        best_name = matches[0]
        rec.lang = ocr.detect_language(lines) or best_name.lang
        contenders = [m for m in matches if m.score >= best_name.score - NAME_TIE_MARGIN][:MAX_ORACLES]
        evidence = Evidence(
            lang=rec.lang,
            collector=ocr.collector_info(lines),
            name_scores={m.oracle_id: m.score for m in matches},
            fr_sets=self.catalog.fr_sets,
            previous_set=previous_set,
            foil=foil,
            list_symbol=list_symbol.evidence(rec.list_symbol),
        )
        printings = self.catalog.printings([m.oracle_id for m in contenders])
        if locked_set:
            in_set = [p for p in printings if p["set_code"] == locked_set]
            rec.off_set = not in_set
            printings = in_set or printings
        rec.candidates = sorted(self._pool.map(lambda p: score_printing(card, p, evidence), printings),
                                key=lambda c: -c.score)
        if rec.candidates:
            rec.ok = True
            rec.confidence = _confidence(best_name.score, rec.candidates)
            rec.ambiguous = _ambiguous(rec.candidates)
        return rec
