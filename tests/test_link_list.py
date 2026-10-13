from magicscanner.catalog import cardmarket

THE_LIST, MYSTERY_BOOSTER, OTHER = 3494, 2874, 9999


def _plst(con, card_id, name, number, product=None):
    con.execute("INSERT OR IGNORE INTO sets (code, name) VALUES ('plst', 'The List')")
    con.execute("INSERT INTO cards (id, oracle_id, name, front_name, set_code, collector_number, rarity, cardmarket_id) "
                "VALUES (?,?,?,?,?,?,?,?)", (card_id, "o-" + name, name, name, "plst", number, "common", product))


def _product(con, id_product, name, expansion):
    con.execute("INSERT INTO cm_products VALUES (?,?,?,NULL)", (id_product, name, expansion))


def _linked(con, card_id):
    return con.execute("SELECT cardmarket_id FROM cards WHERE id=?", (card_id,)).fetchone()[0]


def test_unique_name_is_linked(con):
    _plst(con, "a", "Early Harvest", "MIR-213")
    _product(con, 1, "Early Harvest", THE_LIST)
    assert cardmarket.link_list_cards(con) == 1
    assert _linked(con, "a") == 1


def test_name_sold_in_two_expansions_is_left_alone(con):
    _plst(con, "a", "Early Harvest", "MIR-213")
    _product(con, 1, "Early Harvest", THE_LIST)
    _product(con, 2, "Early Harvest", MYSTERY_BOOSTER)
    assert cardmarket.link_list_cards(con) == 0
    assert _linked(con, "a") is None


def test_two_printings_without_id_are_left_alone(con):
    _plst(con, "a", "Extract from Darkness", "2X2-210")
    _plst(con, "b", "Extract from Darkness", "E01-84")
    _product(con, 1, "Extract from Darkness", MYSTERY_BOOSTER)
    assert cardmarket.link_list_cards(con) == 0


def test_product_already_taken_or_in_other_expansion_is_ignored(con):
    _plst(con, "known", "Early Harvest", "MIR-213", product=1)
    _plst(con, "a", "Early Harvest", "X-1")
    _plst(con, "b", "Renegade Map", "AER-173")
    _product(con, 1, "Early Harvest", THE_LIST)
    _product(con, 3, "Renegade Map", OTHER)
    assert cardmarket.link_list_cards(con) == 0
