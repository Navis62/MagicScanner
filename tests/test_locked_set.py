"""Édition fixée : les noms (VO comme VF) sont cherchés parmi les cartes de l'édition, avec repli hors édition."""
import pytest

from magicscanner.catalog import Catalog
from magicscanner.recognition import Recognizer


@pytest.fixture
def recognizer(con):
    con.executemany("INSERT INTO names VALUES (?,?,?)", [
        ("o-grave", "en", "Gravecrawler"), ("o-grave", "fr", "Rampe-tombe"),
        ("o-plains", "en", "Plains"), ("o-plains", "fr", "Plaine"),
    ])
    con.commit()
    return Recognizer(Catalog(con), engine=object())


def test_names_restricted_to_locked_set_in_both_languages(recognizer):
    catalog = recognizer.catalog
    assert [m.name for m in catalog.match_names(["Plaine"], set_code="m15")] == ["Plaine"]
    assert [m.name for m in catalog.match_names(["Plains"], set_code="m15")] == ["Plains"]
    assert catalog.match_names(["Rampe-tombe"], set_code="m15") == []
    assert [m.lang for m in catalog.match_names(["Rampe tombe"], set_code="dka")] == ["fr"]


def test_card_from_another_set_is_still_found(recognizer):
    # Rien d'approchant dans M15 : la carte hors édition est retenue.
    assert [m.oracle_id for m in recognizer._match_names(["Rampe-tombe"], "m15")] == ["o-grave"]
    # Lecture approximative : l'édition fixée l'emporte tant que l'écart reste faible.
    assert recognizer._match_names(["Plaine"], "m15")[0].oracle_id == "o-plains"


def test_sets_and_search_put_locked_set_first(recognizer):
    assert {s["code"] for s in recognizer.catalog.sets()} == {"dka", "m15"}
    _, ids = recognizer.catalog.search("Plains", set_code="m15")
    assert set(ids) == {"plains-1", "plains-2", "plains-3"}
