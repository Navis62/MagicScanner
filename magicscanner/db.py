"""Accès SQLite. Une seule base : référentiel (Scryfall + Cardmarket) + inventaire."""
import sqlite3
import threading
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
-- Impressions papier (fiche anglaise Scryfall = identité d'une impression).
CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    oracle_id TEXT,
    name TEXT NOT NULL,
    front_name TEXT NOT NULL,
    set_code TEXT NOT NULL,
    collector_number TEXT NOT NULL,
    rarity TEXT,
    cardmarket_id INTEGER,
    image_normal TEXT,
    image_small TEXT,
    released_at TEXT,
    layout TEXT,
    frame TEXT,
    promo INTEGER DEFAULT 0,
    set_type TEXT
);
CREATE INDEX IF NOT EXISTS idx_cards_oracle ON cards(oracle_id);
CREATE INDEX IF NOT EXISTS idx_cards_set_num ON cards(set_code, collector_number);

-- Versions localisées (FR) connues de Scryfall, rattachées par (set, numéro).
CREATE TABLE IF NOT EXISTS localized (
    id TEXT PRIMARY KEY,
    lang TEXT NOT NULL,
    oracle_id TEXT,
    set_code TEXT NOT NULL,
    collector_number TEXT NOT NULL,
    printed_name TEXT,
    front_printed_name TEXT,
    image_normal TEXT
);
CREATE INDEX IF NOT EXISTS idx_loc_set_num ON localized(set_code, collector_number, lang);
CREATE INDEX IF NOT EXISTS idx_loc_oracle ON localized(oracle_id, lang);

CREATE TABLE IF NOT EXISTS sets (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    released_at TEXT,
    set_type TEXT,
    card_count INTEGER,
    printed_size INTEGER,
    icon_svg TEXT,
    cm_id_expansion INTEGER,
    cm_slug TEXT,
    cm_slug_source TEXT          -- 'cardmarket' (scrapé) | 'guess' (dérivé du nom) | 'manual'
);

CREATE TABLE IF NOT EXISTS cm_products (
    id_product INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    id_expansion INTEGER,
    id_metacard INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cmp_exp ON cm_products(id_expansion);

CREATE TABLE IF NOT EXISTS cm_prices (
    id_product INTEGER PRIMARY KEY,
    trend REAL, avg REAL, low REAL, avg7 REAL, avg30 REAL
);

CREATE TABLE IF NOT EXISTS cm_expansions (
    id_expansion INTEGER,
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sample_code TEXT
);

-- URLs produit validées sur Cardmarket (cache du lister).
CREATE TABLE IF NOT EXISTS cm_urls (
    id_product INTEGER PRIMARY KEY,
    url TEXT NOT NULL
);

-- Noms (VO et VF) pour la recherche floue après OCR.
CREATE TABLE IF NOT EXISTS names (
    oracle_id TEXT NOT NULL,
    lang TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (oracle_id, lang, name)
);

CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES cards(id),
    lang TEXT NOT NULL,
    condition TEXT NOT NULL DEFAULT 'NM',
    price REAL NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    listed_quantity INTEGER NOT NULL DEFAULT 0,
    list_error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (card_id, lang, condition, price)
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER REFERENCES inventory(id),
    card_id TEXT,
    lang TEXT,
    confidence REAL,
    ocr_text TEXT,
    image_path TEXT,
    undone INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_lock = threading.RLock()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()


_shared: sqlite3.Connection | None = None


@contextmanager
def shared():
    """Connexion partagée (serveur web), protégée par un verrou."""
    global _shared
    with _lock:
        if _shared is None:
            _shared = connect()
            init(_shared)
        yield _shared
