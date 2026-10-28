"""Base SQLite unique : référentiel (Scryfall + Cardmarket) et inventaire."""
import json
import sqlite3
from pathlib import Path

from .config import CARDMARKET_DIR, DB_PATH

INVENTORY_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES cards(id),
    lang TEXT NOT NULL,
    condition TEXT NOT NULL DEFAULT 'NM',
    price REAL NOT NULL,
    foil INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL DEFAULT 0,
    listed_quantity INTEGER NOT NULL DEFAULT 0,      -- hérité de l'ancienne publication directe : plus utilisé
    exported_quantity INTEGER NOT NULL DEFAULT 0,   -- déjà passés dans un export CSV TCG Powertools
    list_error TEXT,                                 -- idem
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (card_id, lang, condition, price, foil)
);
"""

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
    set_type TEXT,
    finishes TEXT,        -- « nonfoil,foil » : une impression foil-only ne peut pas être une carte non-foil
    promo_types TEXT,     -- « surgefoil,universesbeyond »…
    power TEXT,           -- force / endurance de la première face (« * » possible) : distingue les tokens de même nom
    toughness TEXT,
    colors TEXT,          -- « G,R »
    type_line TEXT,
    artist TEXT
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
    parent_set_code TEXT,        -- édition annexe (tokens, art series…) -> édition principale
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
    trend REAL, avg REAL, low REAL, avg7 REAL, avg30 REAL, trend_foil REAL
);

CREATE TABLE IF NOT EXISTS cm_expansions (
    id_expansion INTEGER,
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sample_code TEXT
);

-- URLs produit validées sur Cardmarket (héritage de l'ancien lister : lues en priorité pour le lien Cardmarket).
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

{inventory}

-- Ancien journal des publications directes (carte, prix, quantité, date) : conservé comme historique, plus alimenté.
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL REFERENCES inventory(id),
    card_id TEXT NOT NULL REFERENCES cards(id),
    lang TEXT NOT NULL,
    condition TEXT NOT NULL,
    price REAL NOT NULL,
    foil INTEGER NOT NULL DEFAULT 0,
    amount INTEGER NOT NULL,
    url TEXT,
    listed_at TEXT DEFAULT CURRENT_TIMESTAMP
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


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Ouvre la base (et crée les tables manquantes). Utilisable depuis plusieurs threads :
    l'appelant sérialise les accès (cf. web.app)."""
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA.replace("{inventory}", INVENTORY_TABLE.format(name="inventory")))
    _migrate(con)
    con.commit()
    return con


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def _migrate(con: sqlite3.Connection) -> None:
    """Colonnes ajoutées après la création des bases existantes (CREATE TABLE IF NOT EXISTS ne les ajoute pas)."""
    for column in ("finishes", "promo_types", "power", "toughness", "colors", "type_line", "artist"):
        if column not in _columns(con, "cards"):
            con.execute(f"ALTER TABLE cards ADD COLUMN {column} TEXT")
    if "parent_set_code" not in _columns(con, "sets"):
        con.execute("ALTER TABLE sets ADD COLUMN parent_set_code TEXT")
    if "exported_quantity" not in _columns(con, "inventory"):
        con.execute("ALTER TABLE inventory ADD COLUMN exported_quantity INTEGER NOT NULL DEFAULT 0")
    if "trend_foil" not in _columns(con, "cm_prices"):
        con.execute("ALTER TABLE cm_prices ADD COLUMN trend_foil REAL")
        _backfill_trend_foil(con)
    if "foil" not in _columns(con, "listings"):
        con.execute("ALTER TABLE listings ADD COLUMN foil INTEGER NOT NULL DEFAULT 0")
    if "foil" not in _columns(con, "inventory"):
        _add_foil_to_inventory(con)


def _backfill_trend_foil(con: sqlite3.Connection) -> None:
    """Les prix foil viennent du même fichier que les autres : on relit celui déjà téléchargé (sans effet s'il manque,
    le prochain `import` les remplira)."""
    path = CARDMARKET_DIR / "price_guide.json"
    if not path.exists():
        return
    guides = json.loads(path.read_text(encoding="utf-8"))["priceGuides"]
    con.executemany("UPDATE cm_prices SET trend_foil=? WHERE id_product=?",
                    [(g.get("trend-foil"), g["idProduct"]) for g in guides])


def _add_foil_to_inventory(con: sqlite3.Connection) -> None:
    """La finition fait partie de l'identité d'une ligne (contrainte UNIQUE) : SQLite ne sait pas la modifier,
    on reconstruit la table en gardant les identifiants (scans et journal y font référence)."""
    con.commit()
    con.execute("PRAGMA foreign_keys=OFF")
    con.executescript(
        """BEGIN;
        """ + INVENTORY_TABLE.format(name="inventory_new") + """
        INSERT INTO inventory_new (id, card_id, lang, condition, price, quantity, listed_quantity, exported_quantity,
                               list_error, created_at, updated_at)
            SELECT id, card_id, lang, condition, price, quantity, listed_quantity, exported_quantity,
                   list_error, created_at, updated_at FROM inventory;
        DROP TABLE inventory;
        ALTER TABLE inventory_new RENAME TO inventory;
        COMMIT;"""
    )
    con.execute("PRAGMA foreign_keys=ON")

