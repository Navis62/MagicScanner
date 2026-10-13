"""Choix de l'impression : finitions et ambiguïté entre produits Cardmarket."""
import numpy as np
import pytest

from magicscanner.catalog import Catalog
from magicscanner.recognition import recognizer, scoring, visual
from magicscanner.recognition.ocr import CollectorInfo
from magicscanner.recognition.scoring import Candidate, Evidence, score_printing


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
