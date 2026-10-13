from pathlib import Path

import pytest

from magicscanner import db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def con(tmp_path):
    """Base vide (schéma complet) avec un mini-référentiel : Gravecrawler (DKA) et trois Plains M15 (V.1 à V.3)."""
    c = db.connect(tmp_path / "test.db")
    c.executemany("INSERT INTO sets (code, name, cm_slug, cm_slug_source) VALUES (?,?,?,?)", [
        ("dka", "Dark Ascension", "Dark-Ascension", "cardmarket"),
        ("m15", "Magic 2015", "Magic-2015", "cardmarket"),
    ])
    c.executemany(
        "INSERT INTO cards (id, oracle_id, name, front_name, set_code, collector_number, rarity, cardmarket_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        [
            ("grave-dka", "o-grave", "Gravecrawler", "Gravecrawler", "dka", "59", "rare", 252482),
            ("plains-1", "o-plains", "Plains", "Plains", "m15", "250", "common", 267719),
            ("plains-2", "o-plains", "Plains", "Plains", "m15", "251", "common", 267720),
            ("plains-3", "o-plains", "Plains", "Plains", "m15", "252", "common", 267721),
        ],
    )
    c.executemany("INSERT INTO cm_products VALUES (?,?,?,?)", [
        (252482, "Gravecrawler", 1345, 1),
        (267719, "Plains", 1485, 2), (267720, "Plains", 1485, 2), (267721, "Plains", 1485, 2),
    ])
    c.executemany("INSERT INTO cm_expansions VALUES (?,?,?,?)", [
        (1345, "Dark-Ascension", "Dark Ascension", "DKA"),
        (1485, "Magic-2015", "Magic 2015", "M15"),
    ])
    c.commit()
    yield c
    c.close()
