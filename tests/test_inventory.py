import pytest

from magicscanner import db, inventory


def test_same_card_increments_quantity(con):
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    inventory.add_scan(con, "grave-dka", "en", 0.9, "")
    assert inventory.quantity(con, "grave-dka", "fr") == 2
    assert inventory.quantity(con, "grave-dka", "en") == 1
    assert inventory.stats(con)["cards"] == 3


def test_undo_decrements_once(con):
    scan_id = inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    assert inventory.undo_scan(con, scan_id)
    assert not inventory.undo_scan(con, scan_id)
    assert inventory.quantity(con, "grave-dka", "fr") == 0
    assert inventory.recent_scans(con, 10) == []


def test_reassign_moves_the_card(con):
    scan_id = inventory.add_scan(con, "plains-1", "fr", 0.4, "")
    assert inventory.reassign_scan(con, scan_id, "plains-2", "en")
    assert inventory.quantity(con, "plains-1", "fr") == 0
    assert inventory.quantity(con, "plains-2", "en") == 1
    assert inventory.stats(con)["lines"] == 1


def test_foil_and_regular_copies_are_separate_lines(con):
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    foil_scan = inventory.add_scan(con, "grave-dka", "fr", 0.9, "", foil=True)
    assert inventory.quantity(con, "grave-dka", "fr") == 1
    assert inventory.quantity(con, "grave-dka", "fr", foil=True) == 1
    assert inventory.reassign_scan(con, foil_scan, "grave-dka", "en")   # la finition suit le scan
    assert inventory.quantity(con, "grave-dka", "en", foil=True) == 1
    assert inventory.reassign_scan(con, foil_scan, "grave-dka", "en", foil=False)
    assert inventory.quantity(con, "grave-dka", "en") == 1


def test_old_databases_get_the_foil_column_without_losing_stock(tmp_path):
    path = tmp_path / "old.db"
    c = db.connect(path)
    c.execute("INSERT INTO sets (code, name) VALUES ('dka','Dark Ascension')")
    c.execute("INSERT INTO cards (id, name, front_name, set_code, collector_number) VALUES ('g','G','G','dka','1')")
    inventory.add_scan(c, "g", "fr", 0.9, "")
    c.execute("PRAGMA foreign_keys=OFF")   # simule une ancienne base : table recréée sans la colonne
    c.executescript("""
        CREATE TABLE inv_old AS SELECT id, card_id, lang, condition, price, quantity, listed_quantity, exported_quantity,
                                       list_error, created_at, updated_at FROM inventory;
        DROP TABLE inventory;
        ALTER TABLE inv_old RENAME TO inventory;
        CREATE UNIQUE INDEX old_key ON inventory(card_id, lang, condition, price);""")
    c.close()
    c = db.connect(path)
    assert inventory.quantity(c, "g", "fr") == 1
    assert inventory.quantity(c, "g", "fr", foil=True) == 0
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []


def test_different_prices_are_separate_lines_and_follow_the_scan(con):
    cheap = inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "", price=1.5)
    assert inventory.quantity(con, "grave-dka", "fr") == 1
    assert inventory.quantity(con, "grave-dka", "fr", price=1.5) == 1
    assert inventory.reassign_scan(con, cheap, "grave-dka", "fr", price=1.5)
    assert inventory.quantity(con, "grave-dka", "fr", price=1.5) == 2
    assert inventory.stats(con)["value"] == pytest.approx(3.0)
