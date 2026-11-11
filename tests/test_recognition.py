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


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
def test_the_french_poison_counter_is_identified():
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    con = db.connect()
    catalog = Catalog(con)
    rec = Recognizer(catalog).recognize(cv2.imread(str(FIXTURES / "poison_counter_mbs_fr_failed.jpg")))
    best = catalog.card_info(rec.best.card_id)
    assert rec.ok and rec.lang == "fr" and (best["name"], best["set_code"]) == ("Poison Counter", "tmbs")
    con.close()


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
def test_a_sideways_card_cut_in_half_by_its_contour_is_found_by_its_text():
    """Carte noire couchée dans la boîte : le contour retenu s'arrête entre l'illustration et la boîte de texte. Le
    texte, vertical dans l'image, n'est lisible qu'une fois l'image remise droite."""
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    con = db.connect()
    catalog = Catalog(con)
    rec = Recognizer(catalog).recognize(cv2.imread(str(FIXTURES / "dirty_wererat_half_contour_failed.jpg")),
                                        orientation="landscape")
    assert rec.ok and catalog.card_info(rec.best.card_id)["name"] == "Dirty Wererat"
    con.close()


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
def test_a_flavor_line_read_as_title_does_not_name_the_card():
    """Photo webcam réelle : Éteigneur de réverbères (GRN 70, VF), carte noire couchée sur une pile dans la boîte. Le
    contour retenu laisse le bandeau du titre dehors : la première ligne lue est le texte d'ambiance (« des cabrioles à
    l'approche de la créature… »), qui ressemble vaguement à « Horror of Horrors ». Un nom aussi mal lu ne doit pas
    l'emporter sur le vrai titre, que la localisation par le texte retrouve."""
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    con = db.connect()
    catalog = Catalog(con)
    rec = Recognizer(catalog).recognize(cv2.imread(str(FIXTURES / "lamplighter_grn_fr_flavor_as_title.jpg")),
                                        orientation="landscape")
    best = catalog.card_info(rec.best.card_id)
    assert rec.ok and rec.lang == "fr"
    assert (best["name"], best["set_code"], best["collector_number"]) == ("Douser of Lights", "grn", "70")
    con.close()


# Carte du dessus d'une pile, couchée dans la boîte (bornes x0, y0, x1, y1 relevées sur la photo) : son bord noir se perd
# dans la tranche noire des cartes du dessous ; seul son cadre coloré, d'où dépasse la boîte de force / endurance, est net.
PILE_CARDS = {
    "mammoth_spider_dom_fr_box_pile_slow": ((715, 260, 1480, 880), ("Mammoth Spider", "dom", "171")),
    # x1 : coin bas-droit de la bordure noire (carte penchée), et non du cadre coloré seul comme relevé au départ.
    "nature_spiral_dom_fr_box_pile_slow": ((600, 280, 1395, 870), ("Nature's Spiral", "dom", "175")),
}


@pytest.mark.parametrize("name", PILE_CARDS)
def test_the_top_card_of_a_pile_is_found_rather_than_the_box(name):
    """Photo webcam réelle : carte couchée sur une pile, dans la boîte. Sans 4 coins nets, l'intérieur de la boîte (aux
    proportions d'une carte) était pris pour la carte, et elle n'était retrouvée que par son texte (+1,5 s)."""
    (x0, y0, x1, y1), _ = PILE_CARDS[name]
    corners = detect.find_card(cv2.imread(str(FIXTURES / f"{name}.jpg")), "landscape")
    assert corners is not None
    margin = 30
    assert (corners[:, 0] >= x0 - margin).all() and (corners[:, 0] <= x1 + margin).all()
    assert (corners[:, 1] >= y0 - margin).all() and (corners[:, 1] <= y1 + margin).all()
    assert cv2.contourArea(corners) > 0.7 * (x1 - x0) * (y1 - y0)


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
@pytest.mark.parametrize("name", PILE_CARDS)
def test_the_top_card_of_a_pile_is_identified_without_the_slow_fallback(name):
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    _, expected = PILE_CARDS[name]
    con = db.connect()
    catalog = Catalog(con)
    rec = Recognizer(catalog).recognize(cv2.imread(str(FIXTURES / f"{name}.jpg")), orientation="landscape")
    best = catalog.card_info(rec.best.card_id, rec.lang)
    assert rec.ok and rec.lang == "fr"
    assert (best["name"], best["set_code"], best["collector_number"]) == expected
    assert "texte" not in rec.timings   # trouvée par son contour, pas par la localisation par le texte
    con.close()


# Cadre moderne (M15 et après) couché sur une pile : le bord noir se perd dans la pile, et le cadre de l'illustration
# (1,36 de large pour 1 de haut), debout dans l'image, a les proportions d'une carte droite. Il était pris pour la
# carte : pas de titre, secours lent par le texte, ligne du bas (numéro, code d'édition) perdue, mauvaise impression.
ART_BOX_CARDS = {
    "sentinel_spider_ema_en_art_box": ((330, 250, 1020, 805), ("Sentinel Spider", "ema", "185")),
    "madcap_skills_mm3_en_art_box": ((345, 220, 1000, 762), ("Madcap Skills", "mm3", "99")),
    "opportunity_mm3_en_art_box": ((400, 230, 1050, 790), ("Opportunity", "mm3", "45")),
    "thrive_mm2_en_art_box": ((358, 185, 1030, 775), ("Thrive", "mm2", "166")),
}


@pytest.mark.parametrize("name", ART_BOX_CARDS)
def test_the_card_is_found_rather_than_its_illustration(name):
    """Photo webcam réelle : carte au cadre moderne couchée sur une pile, aperçu tourné à 90°."""
    (x0, y0, x1, y1), _ = ART_BOX_CARDS[name]
    corners = detect.find_card(cv2.imread(str(FIXTURES / f"{name}.jpg")), "landscape")
    assert corners is not None
    margin = 30
    assert (corners[:, 0] >= x0 - margin).all() and (corners[:, 0] <= x1 + margin).all()
    assert (corners[:, 1] >= y0 - margin).all() and (corners[:, 1] <= y1 + margin).all()
    assert cv2.contourArea(corners) > 0.7 * (x1 - x0) * (y1 - y0)


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
@pytest.mark.parametrize("name", ART_BOX_CARDS)
def test_a_modern_frame_card_on_a_pile_is_identified(name):
    """Photo webcam réelle : l'impression se joue sur la ligne du bas (numéro, code d'édition), qui doit être lue."""
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    _, expected = ART_BOX_CARDS[name]
    con = db.connect()
    catalog = Catalog(con)
    rec = Recognizer(catalog).recognize(cv2.imread(str(FIXTURES / f"{name}.jpg")), orientation="landscape")
    best = catalog.card_info(rec.best.card_id, rec.lang)
    assert rec.ok and rec.lang == "en"
    assert (best["name"], best["set_code"], best["collector_number"]) == expected
    assert "numéro lu" in rec.best.reasons
    con.close()


@pytest.mark.integration
@pytest.mark.skipif(not DB_PATH.exists(), reason="base non importée")
def test_a_set_code_misread_by_one_character_still_counts():
    """Photo webcam réelle : Chandra's Outrage MM3 lue « MMS·EN » et « 002/249 ». Le code exact ne correspondait à aucune
    impression et la réédition A25, au cadre identique, l'emportait."""
    from magicscanner import db
    from magicscanner.catalog import Catalog
    from magicscanner.recognition import Recognizer

    con = db.connect()
    catalog = Catalog(con)
    rec = Recognizer(catalog).recognize(cv2.imread(str(FIXTURES / "chandras_outrage_mm3_en_set_code_misread.jpg")),
                                        orientation="landscape")
    best = catalog.card_info(rec.best.card_id, rec.lang)
    assert (best["name"], best["set_code"], best["collector_number"]) == ("Chandra's Outrage", "mm3", "92")
    con.close()
