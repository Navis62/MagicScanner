"""Données de référence : import (Scryfall, Cardmarket) et consultation."""
import logging
import sqlite3

from . import cardmarket, scryfall
from .lookup import Catalog, NameMatch

__all__ = ["Catalog", "NameMatch", "update"]

log = logging.getLogger(__name__)


def update(con: sqlite3.Connection, skip_download: bool = False) -> None:
    """Import complet : éditions, cartes, catalogue et prix Cardmarket, puis rattachement des éditions."""
    log.info("Scryfall : éditions")
    scryfall.import_sets(con)
    log.info("Scryfall : cartes")
    path = scryfall.latest_bulk() if skip_download else scryfall.download_bulk()
    if path is None:
        raise FileNotFoundError("aucun fichier Scryfall local : relancer sans --skip-download")
    scryfall.import_cards(con, path)
    log.info("Cardmarket : catalogue et prix")
    cardmarket.import_catalog(con)
    log.info("Correspondance éditions -> Cardmarket")
    cardmarket.map_sets(con)
    cardmarket.link_list_cards(con)
