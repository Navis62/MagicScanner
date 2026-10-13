import pytest

from magicscanner.recognition.ocr import CollectorInfo, OcrLine, collector_info, detect_language, title_candidates


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
