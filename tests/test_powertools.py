import csv
import io

from magicscanner import inventory, powertools


def _rows(content):
    return list(csv.DictReader(io.StringIO(content)))


def test_export_only_contains_new_cards(con):
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    inventory.add_scan(con, "plains-1", "en", 0.9, "")
    content, lines, skipped = powertools.build(con)
    rows = _rows(content)
    assert (lines, skipped) == (2, 0)
    assert rows[0] == {"cardmarketId": "252482", "quantity": "2", "name": "Gravecrawler", "set": "Dark Ascension",
                       "condition": "NM", "language": "French", "isSigned": "false", "price": "0.20", "comment": "",
                       "finishType": "Regular", "buyPrice": ""}
    assert rows[1]["language"] == "English"
    assert inventory.stats(con)["to_export"] == 0

    assert powertools.build(con)[1] == 0
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    again = _rows(powertools.build(con)[0])
    assert [(r["name"], r["quantity"]) for r in again] == [("Gravecrawler", "1")]


def test_export_everything_does_not_mark_and_skips_unknown_ids(con):
    con.execute("UPDATE cards SET cardmarket_id = NULL WHERE id='plains-1'")
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    inventory.add_scan(con, "plains-1", "en", 0.9, "")
    content, lines, skipped = powertools.build(con, everything=True)
    assert (lines, skipped) == (1, 1)
    assert inventory.stats(con)["to_export"] == 2


def test_foil_copies_are_exported_as_foil(con):
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "", foil=True)
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    assert sorted(r["finishType"] for r in _rows(powertools.build(con)[0])) == ["Foil", "Regular"]
