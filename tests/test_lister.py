import pytest

from magicscanner import inventory
from magicscanner.market import lister


class FakeLocator:
    def __init__(self, texts):
        self.texts = texts

    def count(self):
        return len(self.texts)

    @property
    def first(self):
        return self

    def inner_text(self):
        return self.texts[0]


class FakePage:
    """Page Cardmarket après l'envoi du formulaire : bandeaux présents selon le sélecteur."""
    url = "https://www.cardmarket.com/en/Magic/Products/Singles/Dark-Ascension/Gravecrawler"

    def __init__(self, success=(), failure=()):
        self.banners = {".alert-success": list(success), ".alert-danger, .alert-warning": list(failure)}

    def locator(self, selector):
        return FakeLocator(self.banners.get(selector, []))

    def screenshot(self, path):
        pass

    def content(self):
        return "<html></html>"


def test_pending_is_the_difference_with_what_is_already_published(con):
    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")
    inventory.mark_listed(con, con.execute("SELECT id FROM inventory").fetchone()["id"], 1)
    assert lister.pending(con) == []

    inventory.add_scan(con, "grave-dka", "fr", 0.9, "")   # 2e exemplaire d'une carte déjà publiée
    inventory.add_scan(con, "plains-1", "en", 0.9, "")
    items = {i.card_id: i for i in lister.pending(con)}
    assert items["grave-dka"].remaining == 1          # uniquement le nouvel exemplaire
    assert items["plains-1"].remaining == 1
    assert len(items) == 2


def test_pending_limit(con):
    for card in ("grave-dka", "plains-1", "plains-2"):
        inventory.add_scan(con, card, "en", 0.9, "")
    assert len(lister.pending(con, limit=2)) == 2


def test_green_banner_confirms_the_listing():
    assert lister._confirm_published(FakePage(success=["Article put for sale"])) == "Article put for sale"


def test_error_banner_skips_only_this_card():
    with pytest.raises(lister.ListingError, match="price too low"):
        lister._confirm_published(FakePage(failure=["price too low"]))


def test_no_banner_stops_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(lister, "DATA", tmp_path)
    with pytest.raises(lister.Unconfirmed):
        lister._confirm_published(FakePage())
