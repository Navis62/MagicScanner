"""Photo webcam réelle : Gargantua phyrexian, Commander 2013 n°87, VF, posée dans la boîte."""
import cv2
import numpy as np
import pytest

from magicscanner.config import DB_PATH
from magicscanner.recognition import detect

from .conftest import FIXTURES

PHOTO = FIXTURES / "gargantua_c13_fr.jpg"


@pytest.fixture(scope="module")
def frame():
    return cv2.imread(str(PHOTO))


def test_detects_and_straightens_card(frame):
    card, corners = detect.extract(frame)
    assert card.shape == (detect.CARD_H, detect.CARD_W, 3)
    # Coins attendus autour de (954,206) (1304,182) (1312,658) (970,680).
    expected = np.array([[954, 206], [1304, 182], [1312, 658], [970, 680]])
    assert np.abs(corners - expected).max() < 25


def test_no_card_in_blank_frame():
    assert detect.find_card(np.full((1080, 1920, 3), 40, np.uint8)) is None


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
def test_recognizes_printing_and_language(frame):
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    con = db.connect()
    catalog = Catalog(con)
    rec = Recognizer(catalog).recognize(frame)
    best = catalog.card_info(rec.best.card_id, rec.lang)
    assert rec.ok and rec.lang == "fr"
    assert (best["name"], best["set_code"], best["collector_number"]) == ("Phyrexian Gargantua", "c13", "87")
    assert best["fr_name"] == "Gargantua phyrexian"
    assert rec.confidence > 0.5
    con.close()
