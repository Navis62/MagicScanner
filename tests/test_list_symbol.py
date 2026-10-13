"""Symbole « The List » (étincelle de Planeswalker en bas à gauche)."""
import cv2
import numpy as np
import pytest

from magicscanner.config import DB_PATH
from magicscanner.recognition import detect, list_symbol
from magicscanner.recognition.scoring import printed_identity

from .conftest import FIXTURES


@pytest.fixture(scope="module")
def real_card():
    """Vraie photo webcam redressée (Gargantua phyrexian, aucun symbole The List)."""
    card, _ = detect.extract(cv2.imread(str(FIXTURES / "gargantua_c13_fr.jpg")))
    return card


def with_symbol(card: np.ndarray, dx: int = 0, dy: int = 0) -> np.ndarray:
    """La même carte, avec l'étincelle collée là où Scryfall la place (position décalée de dx, dy pour simuler
    un redressement approximatif)."""
    out = card.copy()
    glyph = list_symbol._as_seen_by_webcam(list_symbol._template())
    h, w = glyph.shape
    x, y = 17 + dx, 823 + dy                      # coin haut-gauche du gabarit sur une carte 630×880
    region = out[y:y + h, x:x + w].astype(np.float32)
    out[y:y + h, x:x + w] = np.maximum(region, glyph[..., None]).astype(np.uint8)
    return out


def test_no_symbol_on_a_real_card(real_card):
    assert list_symbol.symbol_score(real_card) < list_symbol.ABSENT


def test_symbol_is_found_where_scryfall_puts_it(real_card):
    assert list_symbol.symbol_score(with_symbol(real_card)) >= list_symbol.PRESENT


@pytest.mark.parametrize("dx, dy", [(-5, 0), (5, 0), (0, -5), (0, 5), (4, 4), (-4, -4)])
def test_symbol_is_found_despite_a_misaligned_warp(real_card, dx, dy):
    assert list_symbol.symbol_score(with_symbol(real_card, dx, dy)) >= list_symbol.PRESENT


def test_evidence_is_signed_and_clamped():
    assert list_symbol.evidence(0.0) == -1.0
    assert list_symbol.evidence(list_symbol.ABSENT) == pytest.approx(-1.0)
    assert list_symbol.evidence(list_symbol.PRESENT) == pytest.approx(1.0)
    assert list_symbol.evidence(1.0) == 1.0
    assert list_symbol.evidence((list_symbol.PRESENT + list_symbol.ABSENT) / 2) == pytest.approx(0.0)


def test_the_list_card_is_identified_by_its_original_set_and_number(con):
    con.executemany(
        "INSERT INTO cards (id, oracle_id, name, front_name, set_code, collector_number) VALUES (?,?,?,?,?,?)",
        [("list-1", "o-angel", "Angel of Vitality", "Angel of Vitality", "plst", "M20-4"),
         ("orig-1", "o-angel", "Angel of Vitality", "Angel of Vitality", "m20", "4")],
    )
    rows = {r["id"]: r for r in con.execute("SELECT * FROM cards WHERE id IN ('list-1', 'orig-1')")}
    assert printed_identity(rows["list-1"]) == ("m20", "4")
    assert printed_identity(rows["orig-1"]) == ("m20", "4")


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
def test_the_list_print_wins_over_the_original_only_with_the_symbol():
    """Même carte (Angel of Vitality, M20 n°4) : avec le symbole -> The List, sans -> l'impression d'origine."""
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer, visual

    con = db.connect()
    catalog = Catalog(con)
    recognizer = Recognizer(catalog)
    urls = {r["set_code"]: r["image_normal"] for r in con.execute(
        "SELECT set_code, image_normal FROM cards WHERE name='Angel of Vitality' AND set_code IN ('plst', 'm20')")}

    def seen_by_webcam(url):
        card = cv2.resize(visual.fetch_image(url), (350, 488), interpolation=cv2.INTER_AREA)
        frame = np.full((1080, 1920, 3), (95, 140, 175), np.uint8)
        frame[300:788, 800:1150] = card
        return cv2.GaussianBlur(frame, (0, 0), 0.7)

    on_list = recognizer.recognize(seen_by_webcam(urls["plst"]))
    original = recognizer.recognize(seen_by_webcam(urls["m20"]))
    assert catalog.card_info(on_list.best.card_id)["set_code"] == "plst"
    assert catalog.card_info(original.best.card_id)["set_code"] == "m20"
    assert on_list.list_symbol >= list_symbol.PRESENT > list_symbol.ABSENT > original.list_symbol
    con.close()
