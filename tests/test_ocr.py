import pytest

from magicscanner.recognition import ocr
from magicscanner.recognition.ocr import (
    CollectorInfo,
    OcrLine,
    collector_info,
    detect_language,
    title_candidates,
)


def line(text, y, x=0.08):
    return OcrLine(text, 1.0, x, y)


def test_title_is_top_left_text():
    lines = [line("4BB", 0.05, x=0.78), line("Gargantua phyrexian", 0.05), line("Créature : horreur", 0.57)]
    assert title_candidates(lines) == ["Gargantua phyrexian"]


def test_collector_number_old_frame():
    assert collector_info([line("™ & © 2013 Wizards 87/356", 0.95)]) == CollectorInfo("87", "356", None)


def test_collector_number_and_set_code_new_frame():
    info = collector_info([line("0087 U", 0.94), line("C13 • FR", 0.96)])
    assert info == CollectorInfo("87", None, "c13")


def test_collector_ignores_text_outside_bottom():
    assert collector_info([line("4/4", 0.5)]) == CollectorInfo()


def test_language_detection():
    fr = [line("Quand le Gargantua phyrexian arrive sur le champ de bataille, vous piochez deux cartes", 0.65)]
    en = [line("When Phyrexian Gargantua enters the battlefield, you draw two cards and you lose 2 life", 0.65)]
    assert detect_language(fr) == "fr"
    assert detect_language(en) == "en"
    assert detect_language([line("4/4", 0.9)]) is None


@pytest.mark.parametrize("text, number", [("0087 U", "87"), ("C 0126", "126"), ("R 0096", "96"), ("U0247", "247"), ("0004", "4")])
def test_recent_frame_numbers_with_the_rarity_before_or_after(text, number):
    assert collector_info([line(text, 0.94)]).number == number


@pytest.mark.parametrize("text", ["4/4", "2/2", "Illus. Dave Dorman", "MSH • EN"])
def test_other_bottom_lines_are_not_taken_for_a_number(text):
    assert collector_info([line(text, 0.95)]).number is None


def test_card_position_is_deduced_from_the_title_and_the_footer_lines():
    """Carte de 480×670 px dont le coin haut-gauche est en (1000, 400) : titre et ligne du bas à leur place."""
    top, height = 400, 670
    left = 1000
    title = ocr.PixelLine("Critique terminale", left + ocr.TEXT_INSET * height * 63 / 88, top + 0.06 * height - 10, 20)
    footer = ocr.PixelLine("FRA • FR", title.x, top + 0.945 * height - 6, 12)
    corners = ocr.card_from_title(title, footer)
    assert corners[0] == pytest.approx([left, top], abs=1)
    assert corners[2] == pytest.approx([left + height * 63 / 88, top + height], abs=1)


def test_title_and_footer_too_close_give_no_card():
    line = ocr.PixelLine("x", 0, 100, 10)
    assert ocr.card_from_title(line, ocr.PixelLine("y", 0, 150, 10)) is None


def test_sideways_titles_keep_short_lines_only():
    lines = [line("Error", 0.30), line("Counter target multicolored spell, then draw a card", 0.5), line("Trial", 0.1)]
    assert ocr.sideways_titles(lines) == ["Trial", "Error"]
