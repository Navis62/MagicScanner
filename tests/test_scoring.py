"""Choix de l'impression : finitions et ambiguïté entre produits Cardmarket."""
import cv2
import numpy as np
import pytest

from magicscanner.catalog import Catalog
from magicscanner.recognition import recognizer, scoring, visual
from magicscanner.recognition.ocr import CollectorInfo, OcrLine
from magicscanner.recognition.scoring import Candidate, Evidence, score_printing

from .conftest import FIXTURES


@pytest.fixture
def same_frame_printings(con, monkeypatch):
    """Speed, Young Avenger : #152 (nonfoil + foil) et #448 (surge foil uniquement), image identique."""
    monkeypatch.setattr(visual, "fetch_image", lambda url: np.full((880, 630, 3), 90, np.uint8))
    con.executemany(
        "INSERT INTO cards (id, oracle_id, name, front_name, set_code, collector_number, rarity, image_normal, finishes, cardmarket_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [("normal", "o-speed", "Speed", "Speed", "dka", "152", "uncommon", "img", "nonfoil,foil", 1),
         ("surge", "o-speed", "Speed", "Speed", "dka", "448", "uncommon", "img", "foil", 2)],
    )
    con.commit()
    rows = {r["id"]: r for r in Catalog(con).printings(["o-speed"])}
    evidence = Evidence(lang="en", collector=CollectorInfo(), name_scores={"o-speed": 100}, fr_sets=set())
    return rows, evidence


def test_a_foil_only_printing_is_never_preferred_over_the_regular_one(same_frame_printings):
    rows, evidence = same_frame_printings
    scan = np.full((880, 630, 3), 90, np.uint8)
    normal, surge = score_printing(scan, rows["normal"], evidence), score_printing(scan, rows["surge"], evidence)
    assert normal.score - surge.score == pytest.approx(-scoring.NOT_NONFOIL)


def test_the_printed_number_cannot_override_the_foil_penalty_alone(same_frame_printings):
    """Même si l'OCR lit « 448 » (pour une carte qui est pourtant en non-foil), l'écart reste raisonnable : la
    carte est signalée à vérifier plutôt que choisie silencieusement."""
    rows, _ = same_frame_printings
    scan = np.full((880, 630, 3), 90, np.uint8)
    ev = Evidence(lang="en", collector=CollectorInfo(number="448"), name_scores={"o-speed": 100}, fr_sets=set())
    surge, normal = score_printing(scan, rows["surge"], ev), score_printing(scan, rows["normal"], ev)
    assert abs(surge.score - normal.score) < 0.5


def candidate(score, product):
    return Candidate("x", score, 0, [], product)


def test_close_candidates_in_different_products_are_ambiguous():
    assert recognizer._ambiguous([candidate(1.0, 1), candidate(0.95, 2)])


def test_close_candidates_in_the_same_product_are_not():
    assert not recognizer._ambiguous([candidate(1.0, 1), candidate(0.95, 1)])


def test_a_clear_winner_is_not_ambiguous():
    assert not recognizer._ambiguous([candidate(1.0, 1), candidate(0.6, 2)])
    assert not recognizer._ambiguous([candidate(1.0, 1)])


class _FixedOcr:
    """OCR factice : la carte redressée se lit toujours de la même façon."""

    def __init__(self, lines):
        self.lines = lines

    def read(self, card):
        return self.lines

    def read_pixels(self, frame):
        return []


@pytest.fixture
def neighbouring_sets(con, monkeypatch):
    """Chandra's Outrage dans MM3 et MM2 (codes à un caractère l'un de l'autre), image identique : seul le code lu
    les départage. Renvoie une fonction : ligne du bas lue -> candidats par impression."""
    monkeypatch.setattr(visual, "fetch_image", lambda url: np.full((880, 630, 3), 90, np.uint8))
    con.executemany("INSERT INTO sets (code, name) VALUES (?,?)", [("mm3", "Modern Masters 2017"), ("mm2", "Modern Masters 2015")])
    con.executemany(
        "INSERT INTO cards (id, oracle_id, name, front_name, set_code, collector_number, rarity, image_normal, finishes, cardmarket_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [("mm3", "o-outrage", "Chandra's Outrage", "Chandra's Outrage", "mm3", "92", "common", "img", "nonfoil,foil", 1),
         ("mm2", "o-outrage", "Chandra's Outrage", "Chandra's Outrage", "mm2", "114", "common", "img", "nonfoil,foil", 2)],
    )
    con.execute("INSERT INTO names VALUES ('o-outrage', 'en', 'Chandra''s Outrage')")
    con.commit()
    frame = cv2.imread(str(FIXTURES / "gargantua_c13_fr.jpg"))   # une vraie carte à trouver ; seule la lecture est factice

    def recognize(footer):
        lines = [OcrLine("Chandra's Outrage", 1.0, 0.08, 0.05), OcrLine(footer, 1.0, 0.08, 0.95)]
        rec = recognizer.Recognizer(Catalog(con), engine=_FixedOcr(lines)).recognize(frame)
        return {c.card_id: c for c in rec.candidates}
    return recognize


def test_a_set_code_read_exactly_gives_nothing_to_a_neighbouring_set(neighbouring_sets):
    """« MM3 » lu tel quel : MM2, à un caractère, n'est pas un code « approchant » (il gardait la moitié du bonus)."""
    found = neighbouring_sets("MM3·EN CHRISTOPHER MOELLER")
    assert "code édition approchant" not in found["mm2"].reasons
    assert found["mm3"].score - found["mm2"].score == pytest.approx(scoring.SET_CODE_READ)


def test_a_set_code_misread_by_one_character_still_counts(neighbouring_sets):
    """« MMS » (lu pour MM3) ne correspond exactement à aucune impression : les codes à un caractère près comptent."""
    found = neighbouring_sets("MMS·EN CHRISTOPHER MOELLER")
    assert "code édition approchant" in found["mm3"].reasons


def test_a_foil_scan_prefers_a_printing_that_exists_in_foil(same_frame_printings):
    rows, _ = same_frame_printings
    scan = np.full((880, 630, 3), 90, np.uint8)
    foil = Evidence(lang="en", collector=CollectorInfo(), name_scores={"o-speed": 100}, fr_sets=set(), foil=True)
    assert score_printing(scan, rows["surge"], foil).score == score_printing(scan, rows["normal"], foil).score
