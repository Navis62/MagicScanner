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

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


def _confidence(name_score: float, candidates: list[Candidate]) -> float:
    """Confiance = qualité du nom × écart entre la 1re et la 2e impression."""
    second = candidates[1].score if len(candidates) > 1 else 0
    gap = candidates[0].score - second
    return round(min(1.0, (name_score / 100) * (0.5 + 2 * gap)), 3)


class Recognizer:
    def __init__(self, catalog: Catalog, engine: ocr.OcrEngine | None = None):
        self.catalog = catalog
        self.ocr = engine or ocr.OcrEngine()
        self._pool = ThreadPoolExecutor(8)  # téléchargement / comparaison des images candidates

    def _read_card(self, card: np.ndarray) -> tuple[np.ndarray, list[ocr.OcrLine], list[str], list[NameMatch]]:
        """OCR + nom ; si rien ne correspond, la carte est peut-être à l'envers : on retourne et on relit."""
        attempt = None
        for img in (card, cv2.rotate(card, cv2.ROTATE_180)):
            lines = self.ocr.read(img)
            titles = ocr.title_candidates(lines)
            matches = self.catalog.match_names(titles) if titles else []
            attempt = attempt or (img, lines, titles, matches)
            if matches:
                return img, lines, titles, matches
        return attempt

    def recognize(self, frame: np.ndarray, previous_set: str | None = None) -> Recognition:
        card, corners = detect.extract(frame)
        if card is None:
            return Recognition(False, "Carte non détectée : vérifie le cadrage / l'éclairage")

        card, lines, titles, matches = self._read_card(card)
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
            list_symbol=list_symbol.evidence(rec.list_symbol),
        )
        printings = self.catalog.printings([m.oracle_id for m in contenders])
        rec.candidates = sorted(self._pool.map(lambda p: score_printing(card, p, evidence), printings),
                                key=lambda c: -c.score)
        if rec.candidates:
            rec.ok = True
            rec.confidence = _confidence(best_name.score, rec.candidates)
        return rec
