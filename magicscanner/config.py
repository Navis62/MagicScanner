"""Configuration centrale. Surcharge possible via variables d'environnement MS_*."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("MS_DATA", ROOT / "data"))
DB_PATH = DATA / "magicscanner.db"
SCRYFALL_DIR = DATA / "scryfall"
CARDMARKET_DIR = DATA / "cardmarket"
IMAGE_CACHE = DATA / "images"
SCANS_DIR = DATA / "scans"
CHROME_PROFILE = DATA / "chrome-profile"

CHROME_EXE = os.environ.get("MS_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CDP_PORT = int(os.environ.get("MS_CDP_PORT", "9222"))
# Fenêtre Chrome du lister : left, top, width, height.
WINDOW = tuple(int(v) for v in os.environ.get("MS_WINDOW", "40,40,1500,1000").split(","))

# Paramètres du POC : tout est NM, prix fixe.
DEFAULT_PRICE = float(os.environ.get("MS_PRICE", "0.20"))
DEFAULT_CONDITION = "NM"
LANGS = ("en", "fr")
# Au-delà de ce prix tendance Cardmarket, l'UI signale que la carte vaut plus que 20 ct.
PRICE_ALERT = float(os.environ.get("MS_PRICE_ALERT", "1.00"))

SCRYFALL_UA = {"User-Agent": "MagicScanner/0.1 (personal card scanner)", "Accept": "application/json"}
CM_PRODUCTS_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_1.json"
CM_PRICES_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"

for d in (DATA, SCRYFALL_DIR, CARDMARKET_DIR, IMAGE_CACHE, SCANS_DIR):
    d.mkdir(parents=True, exist_ok=True)
