from magicscanner import inventory


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


def test_listing_progress(con):
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    line_id = con.execute("SELECT id FROM inventory").fetchone()["id"]
    inventory.mark_list_error(con, line_id, "page produit introuvable")
    assert inventory.list_errors(con)[0]["n"] == 1
    inventory.mark_listed(con, line_id, 2)
    st = inventory.stats(con)
    assert (st["listed"], st["to_list"]) == (2, 0)
    assert inventory.list_errors(con) == []
