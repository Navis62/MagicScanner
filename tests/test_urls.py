import pytest

from magicscanner.market import urls

BASE = "https://www.cardmarket.com/en/Magic/Products/Singles"


# Slugs réels relevés sur cardmarket.com.
@pytest.mark.parametrize("name, version, expected", [
    ("Gravecrawler", None, "Gravecrawler"),
    ("Akroma's Memorial", None, "Akroma-s-Memorial"),
    ("Lim-Dûl's Cohort", None, "LimDuls-Cohort"),
    ("Loran's Escape", None, "Lorans-Escape"),       # même apostrophe, autre forme (The Brothers' War, 2022)
    ("Jace, the Mind Sculptor", None, "Jace-the-Mind-Sculptor"),
    ("Delver of Secrets / Insectile Aberration", None, "Delver-of-Secrets-Insectile-Aberration"),
    ("Fire // Ice", None, "Fire-Ice"),
    ("Plains", 1, "Plains-V-1"),
    ("Aether Hub", None, "Aether-Hub"),
    ("Ogre Token (Red 3/3)", None, "Ogre-Token-Red-33"),
])
def test_real_slug_is_among_variants(name, version, expected):
    assert expected in urls.slug_variants(name, version)


def test_slugify_strips_accents_and_ligatures():
    assert urls.slugify("Ætherize") == "Aetherize"
    assert urls.slugify("Junún Efreet") == "Junun-Efreet"


def test_candidate_urls_simple(con):
    assert urls.candidate_urls(con, "grave-dka")[0] == f"{BASE}/Dark-Ascension/Gravecrawler"


def test_candidate_urls_versions_follow_product_ids(con):
    assert urls.candidate_urls(con, "plains-1")[0] == f"{BASE}/Magic-2015/Plains-V-1"
    assert urls.candidate_urls(con, "plains-3")[0] == f"{BASE}/Magic-2015/Plains-V-3"


def test_a_card_with_a_cardmarket_id_is_linked_by_id(con):
    """« Loran's Escape » est en ligne sous Lorans-Escape, « Akroma's Memorial » sous Akroma-s-Memorial, sans règle de date
    (Ravnica Allegiance a l'ancienne forme, Core 2019 la nouvelle) : l'adresse par idProduct, que Cardmarket redirige
    vers la vraie fiche, ne devine rien."""
    assert urls.product_url(con, "grave-dka") == "https://www.cardmarket.com/en/Magic/Products?idProduct=252482"


def test_a_validated_url_beats_the_id(con):
    con.execute("INSERT INTO cm_urls VALUES (?,?)", (252482, f"{BASE}/Dark-Ascension/Gravecrawler-custom"))
    assert urls.product_url(con, "grave-dka") == f"{BASE}/Dark-Ascension/Gravecrawler-custom"


def test_without_a_cardmarket_id_the_slug_is_guessed(con):
    con.execute("INSERT INTO cards (id, oracle_id, name, front_name, set_code, collector_number) "
                "SELECT 'grave-noid', oracle_id, name, front_name, set_code, '99' FROM cards WHERE id='grave-dka'")
    assert urls.product_url(con, "grave-noid") == f"{BASE}/Dark-Ascension/Gravecrawler"


def test_browse_filters_are_appended_to_the_id_address():
    url = urls.browse_url("https://www.cardmarket.com/en/Magic/Products?idProduct=683456")
    assert url.startswith("https://www.cardmarket.com/fr/Magic/Products?idProduct=683456&sellerCountry=")


def test_remembered_url_comes_first(con):
    con.execute("INSERT INTO cm_urls VALUES (?,?)", (252482, f"{BASE}/Dark-Ascension/Gravecrawler-custom"))
    assert urls.candidate_urls(con, "grave-dka")[0].endswith("Gravecrawler-custom")


def test_unknown_card_has_no_url(con):
    assert urls.candidate_urls(con, "nope") == []


def test_plst_never_gets_a_set_level_guess(con):
    """The List / Mystery Booster : sans idProduct, aucune adresse (celle de l'autre version serait fausse)."""
    from magicscanner.catalog import cardmarket

    con.execute("INSERT INTO sets (code, name, cm_slug, cm_slug_source) VALUES ('plst', 'The List', 'Mystery-Booster', 'cardmarket')")
    con.executemany(
        "INSERT INTO cards (id, oracle_id, name, front_name, set_code, collector_number, cardmarket_id) VALUES (?,?,?,?,?,?,?)",
        [("efd-mb", "o-efd", "Extract from Darkness", "Extract from Darkness", "plst", "E01-84", 252482),
         ("efd-list", "o-efd", "Extract from Darkness", "Extract from Darkness", "plst", "2X2-210", None)],
    )
    cardmarket.map_sets(con)
    assert urls.candidate_urls(con, "efd-list") == []                  # pas de produit connu -> pas de lien trompeur
    # Avec un produit connu, l'adresse vient de l'extension de ce produit (ici celle du produit 252482), pas de l'édition.
    assert urls.candidate_urls(con, "efd-mb")[0].startswith(f"{BASE}/Dark-Ascension/")
    assert con.execute("SELECT cm_slug FROM sets WHERE code='plst'").fetchone()[0] is None
