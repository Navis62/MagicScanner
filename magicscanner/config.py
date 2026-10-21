"""Configuration centrale. Chaque valeur peut être surchargée par une variable d'environnement MS_*."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- Emplacements ---------------------------------------------------------------------------------------------
DATA = Path(os.environ.get("MS_DATA", ROOT / "data"))
DB_PATH = DATA / "magicscanner.db"
SCRYFALL_DIR = DATA / "scryfall"
CARDMARKET_DIR = DATA / "cardmarket"
IMAGE_CACHE = DATA / "images"
SCANS_DIR = DATA / "scans"
# Photos des scans conservées pour contrôle : "none", "low" (confiance faible seulement) ou "all" (~80 Ko chacune).
KEEP_SCANS = os.environ.get("MS_KEEP_SCANS", "low")
LOW_CONFIDENCE = 0.5   # en dessous, l'interface demande de vérifier la carte

# --- Stock (POC : tout est NM, prix par défaut fixe) ---------------------------------------------------------------------
DEFAULT_PRICE = float(os.environ.get("MS_PRICE", "0.18"))
DEFAULT_CONDITION = "NM"
MIN_PRICE = 0.02   # prix minimum accepté par Cardmarket
LANGS = ("en", "fr")

# --- Chrome piloté (lecture des slugs d'extensions sur cardmarket.com) -------------------------------------------------------------------------------
CHROME_PROFILE = DATA / "chrome-profile"
CHROME_EXE = os.environ.get("MS_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CDP_PORT = int(os.environ.get("MS_CDP_PORT", "9222"))
WINDOW = tuple(int(v) for v in os.environ.get("MS_WINDOW", "40,40,1500,1000").split(","))  # left, top, width, height

# --- Sources de données ---------------------------------------------------------------------------------------
SCRYFALL_HEADERS = {"User-Agent": "MagicScanner/0.1 (personal card scanner)", "Accept": "application/json"}
SCRYFALL_BULK_URL = "https://api.scryfall.com/bulk-data/all-cards"
SCRYFALL_SETS_URL = "https://api.scryfall.com/sets"
CM_PRODUCTS_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_1.json"
CM_PRICES_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"
CM_EXPANSIONS_URL = "https://www.cardmarket.com/en/Magic/Expansions"
CM_SINGLES_URL = "https://www.cardmarket.com/en/Magic/Products/Singles"
# Filtres de la page produit ouverte depuis l'appli : vendeurs d'Europe, réputation, langues FR/EN, état minimum.
CM_BROWSE_QUERY = ("sellerCountry=1,2,3,33,35,5,6,8,9,11,12,7,14,15,37,16,17,36,21,18,19,20,22,23,25,26,27,29,31,30,10,28"
                   "&sellerReputation=1&language=1,2&minCondition=2")


def ensure_dirs() -> None:
    for d in (DATA, SCRYFALL_DIR, CARDMARKET_DIR, IMAGE_CACHE, SCANS_DIR):
        d.mkdir(parents=True, exist_ok=True)
