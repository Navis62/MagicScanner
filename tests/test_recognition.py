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


def test_reference_images_are_cached_in_reduced_size(tmp_path):
    from magicscanner.recognition import visual

    big = np.random.default_rng(0).integers(0, 255, (680, 488, 3), dtype=np.uint8)
    path = tmp_path / "ref.jpg"
    small = visual._store(path, big)
    assert small.shape[1] == visual.STORED_WIDTH
    assert cv2.imread(str(path)).shape[1] == visual.STORED_WIDTH


# --- Carte collée à la paroi de la boîte (cas réel qui échouait : « Carte non détectée ») ----------------------------

STUCK_CARD = np.array([[1188, 80], [1890, 80], [1890, 985], [1188, 985]])


@pytest.mark.parametrize("name", ["borderless_spiderman_failed", "borderless_spiderman_weak_edge"])
def test_card_touching_the_box_wall_is_found(name):
    """Le contour de la carte fusionne avec la paroi ondulée et la pile de cartes ; le bord gauche est parfois à peine visible."""
    corners = detect.find_card(cv2.imread(str(FIXTURES / f"{name}.jpg")))
    assert corners is not None
    assert np.abs(corners - STUCK_CARD).max() < 30


def test_a_scene_without_a_whole_card_gives_nothing():
    frame = cv2.imread(str(FIXTURES / "borderless_spiderman_failed.jpg"))
    assert detect.find_card(frame[:, :1080]) is None          # clavier, tapis et cartes coupées par le bord de l'image
    assert detect.find_card(np.full((1080, 1920, 3), 40, np.uint8)) is None


def synthetic_scene(card_height=460, with_inner_frame=True):
    """Fond sombre, bords de carte fins, cadre intérieur plus net, et une paroi parallèle à gauche."""
    img = np.full((540, 960, 3), 25, np.uint8)
    w = int(card_height * 63 / 88)
    x, y = 420, 30
    cv2.rectangle(img, (x, y), (x + w, y + card_height), (90, 90, 90), 2)              # bord de la carte : peu contrasté
    if with_inner_frame:
        cv2.rectangle(img, (x + 25, y + 30), (x + w - 25, y + card_height - 70), (230, 230, 230), 2)   # cadre intérieur : net
    cv2.line(img, (x - 70, 0), (x - 70, 539), (200, 200, 200), 2)                      # paroi de la boîte
    cv2.line(img, (x - 40, 0), (x - 40, 539), (200, 200, 200), 2)
    return img, (x, y, x + w, y + card_height)


def test_the_whole_card_wins_over_its_inner_frame():
    from magicscanner.recognition import card_rect

    img, (x0, y0, x1, y1) = synthetic_scene()
    corners = card_rect.find_rect(img)
    assert corners is not None
    assert np.abs(corners - np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])).max() < 8


def test_a_small_rectangle_is_not_a_card():
    from magicscanner.recognition import card_rect

    img, _ = synthetic_scene(card_height=90, with_inner_frame=False)    # vignette de 90 px sur 540 : trop petite
    assert card_rect.find_rect(img) is None


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
def test_the_borderless_spiderman_is_identified():
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    con = db.connect()
    catalog = Catalog(con)
    rec = Recognizer(catalog).recognize(cv2.imread(str(FIXTURES / "borderless_spiderman_failed.jpg")))
    best = catalog.card_info(rec.best.card_id)
    assert rec.ok and (best["name"], best["set_code"], best["collector_number"]) == ("Spider-Man, To the Rescue", "msh", "335")
    con.close()
