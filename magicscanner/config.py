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
CHROME_PROFILE = DATA / "chrome-profile"

# --- Vente (POC : tout est NM, prix fixe) ---------------------------------------------------------------------
DEFAULT_PRICE = float(os.environ.get("MS_PRICE", "0.20"))
DEFAULT_CONDITION = "NM"
LANGS = ("en", "fr")
PRICE_ALERT = float(os.environ.get("MS_PRICE_ALERT", "1.00"))  # tendance au-delà de laquelle l'UI alerte

# --- Chrome piloté (Cardmarket) -------------------------------------------------------------------------------
CHROME_EXE = os.environ.get("MS_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CDP_PORT = int(os.environ.get("MS_CDP_PORT", "9222"))
WINDOW = tuple(int(v) for v in os.environ.get("MS_WINDOW", "40,40,1500,1000").split(","))  # left, top, width, height

# --- Sources de données ---------------------------------------------------------------------------------------
SCRYFALL_HEADERS = {"User-Agent": "MagicScanner/0.1 (personal card scanner)", "Accept": "application/json"}
SCRYFALL_BULK_URL = "https://api.scryfall.com/bulk-data/all-cards"
SCRYFALL_SETS_URL = "https://api.scryfall.com/sets"
CM_PRODUCTS_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_1.json"
CM_PRICES_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"
CM_HOME_URL = "https://www.cardmarket.com/en/Magic"
CM_EXPANSIONS_URL = "https://www.cardmarket.com/en/Magic/Expansions"
CM_SINGLES_URL = "https://www.cardmarket.com/en/Magic/Products/Singles"
CM_LOGIN_URL = "https://www.cardmarket.com/fr/Magic/MainPage/Login"


def ensure_dirs() -> None:
    for d in (DATA, SCRYFALL_DIR, CARDMARKET_DIR, IMAGE_CACHE, SCANS_DIR):
        d.mkdir(parents=True, exist_ok=True)
