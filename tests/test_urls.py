import pytest

from magicscanner.market import urls

BASE = "https://www.cardmarket.com/en/Magic/Products/Singles"


# Slugs réels relevés sur cardmarket.com.
@pytest.mark.parametrize("name, version, expected", [
    ("Gravecrawler", None, "Gravecrawler"),
    ("Akroma's Memorial", None, "Akroma-s-Memorial"),
    ("Lim-Dûl's Cohort", None, "LimDuls-Cohort"),
    ("Jace, the Mind Sculptor", None, "Jace-the-Mind-Sculptor"),
    ("Delver of Secrets / Insectile Aberration", None, "Delver-of-Secrets-Insectile-Aberration"),
    ("Fire // Ice", None, "Fire-Ice"),
    ("Plains", 1, "Plains-V-1"),
    ("Aether Hub", None, "Aether-Hub"),
])
def test_real_slug_is_among_variants(name, version, expected):
    assert expected in urls.slug_variants(name, version)


def test_slugify_strips_accents_and_ligatures():
    assert urls.slugify("Ætherize") == "Aetherize"
    assert urls.slugify("Junún Efreet") == "Junun-Efreet"


def test_candidate_urls_simple(con):
    assert urls.candidate_urls(con, "grave-dka")[0] == f"{BASE}/Dark-Ascension/Gravecrawler"


def test_candidate_urls_versions_follow_product_ids(con):
    assert urls.product_url(con, "plains-1") == f"{BASE}/Magic-2015/Plains-V-1"
    assert urls.product_url(con, "plains-3") == f"{BASE}/Magic-2015/Plains-V-3"


def test_remembered_url_comes_first(con):
    urls.remember_url(con, 252482, f"{BASE}/Dark-Ascension/Gravecrawler-custom")
    assert urls.candidate_urls(con, "grave-dka")[0].endswith("Gravecrawler-custom")


def test_unknown_card_has_no_url(con):
    assert urls.candidate_urls(con, "nope") == []
