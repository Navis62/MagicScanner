"""Mise en vente sur Cardmarket (Chrome réel rattaché en CDP, session déjà connectée).

Pour chaque ligne d'inventaire dont une partie du stock n'est pas encore en vente :
  1. trouve la page produit (variantes d'URL, puis recherche dans l'extension) ;
  2. vérifie que c'est la bonne : le champ caché idAddProduct du formulaire = cardmarket_id Scryfall ;
  3. remplit quantité / langue / état / prix, clique « Put for sale » et attend la confirmation de Cardmarket.

Seule la différence (quantité - déjà publiée) est mise en vente : scanner un 2e exemplaire d'une carte déjà
publiée n'annonce que ce 2e exemplaire.
"""
import logging
import random
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from playwright.sync_api import Page

from .. import inventory
from ..config import CM_HOME_URL, DATA
from . import browser, urls

log = logging.getLogger(__name__)

FORM = "#ListProductForm"
MAX_AMOUNT = 30  # limite du champ quantité Cardmarket
LANGUAGE_ID = {"en": 1, "fr": 2, "de": 3, "es": 4, "it": 5, "zhs": 6, "ja": 7, "pt": 8, "ru": 9, "ko": 10, "zht": 11}
CONDITION_ID = {"MT": 1, "NM": 2, "EX": 3, "GD": 4, "LP": 5, "PL": 6, "PO": 7}

JS_FILL = """([sel, values]) => {
    const f = document.querySelector(sel);
    for (const [name, v] of Object.entries(values)) {
        const el = f.elements[name];
        el.value = v;
        el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
    }
    for (const name of ['isFoil', 'isSigned', 'isAltered']) if (f.elements[name]) f.elements[name].checked = false;
}"""


@dataclass
class Listing:
    inventory_id: int
    card_id: str
    cardmarket_id: int | None
    label: str
    lang: str
    condition: str
    price: float
    remaining: int


@dataclass
class Summary:
    published: int = 0            # exemplaires mis en vente
    errors: int = 0
    stopped: str | None = None    # raison d'un arrêt anticipé


class ListingError(Exception):
    """Échec propre à une carte : on note l'erreur et on passe à la suivante."""


class Unconfirmed(Exception):
    """Résultat de la mise en vente impossible à interpréter : on arrête tout plutôt que risquer des doublons."""


class NotLoggedIn(Exception):
    pass


Report = Callable[[dict], None]


# --- Page produit -------------------------------------------------------------------------------------------

def _form_product_id(page: Page) -> int | None:
    field = page.locator(f"{FORM} input[name=idAddProduct]")
    value = field.first.get_attribute("value") if field.count() else None
    return int(value) if value and value.isdigit() else None


def _open_product(page: Page, url: str, id_product: int) -> bool:
    browser.goto(page, url)
    return _form_product_id(page) == id_product


def find_product_page(con: sqlite3.Connection, page: Page, card_id: str, id_product: int) -> str | None:
    """Ouvre la page produit et renvoie son URL (mémorisée pour les fois suivantes)."""
    candidates = urls.candidate_urls(con, card_id)
    url = next((u for u in candidates if _open_product(page, u, id_product)), None)
    if url is None and candidates:
        url = _search_in_expansion(con, page, card_id, candidates[-1].rsplit("/", 1)[0], id_product)
    if url:
        urls.remember_url(con, id_product, url)
    return url


def _search_in_expansion(con: sqlite3.Connection, page: Page, card_id: str, expansion_url: str, id_product: int) -> str | None:
    """Dernier recours : recherche par nom dans l'extension, puis ouverture des résultats."""
    name = (urls.product_name(con, card_id) or "").split(" / ")[0]
    browser.goto(page, f"{expansion_url}?searchString={name}")
    links = page.eval_on_selector_all(
        "a[href*='/Products/Singles/']",
        "els => [...new Set(els.map(e => e.href.split('?')[0]).filter(h => h.split('/').length > 8))]",
    )
    return next((link for link in links[:8] if _open_product(page, link, id_product)), None)


# --- Mise en vente ------------------------------------------------------------------------------------------

def _debug_snapshot(page: Page) -> str:
    folder = DATA / "publish-debug"
    folder.mkdir(parents=True, exist_ok=True)
    stem = folder / time.strftime("%Y%m%d-%H%M%S")
    try:
        page.screenshot(path=f"{stem}.png")
        stem.with_suffix(".html").write_text(page.content(), encoding="utf-8")
    except Exception:  # simple aide au diagnostic
        pass
    return str(stem)


def _confirm_published(page: Page) -> str:
    """Succès = bandeau vert de Cardmarket. Une erreur affichée par le site -> ListingError (carte suivante).
    Ni l'un ni l'autre -> Unconfirmed : on ne sait pas si l'annonce existe, arrêt complet."""
    success = page.locator(".alert-success")
    if success.count():
        return success.first.inner_text().strip()
    failure = page.locator(".alert-danger, .alert-warning")
    if failure.count():
        raise ListingError(failure.first.inner_text().strip())
    raise Unconfirmed(f"Cardmarket n'a pas confirmé la mise en vente (capture : {_debug_snapshot(page)}.png)")


def put_for_sale(page: Page, item: Listing, amount: int, submit: bool) -> str:
    values = {
        "amount": str(amount),
        "idLanguage": str(LANGUAGE_ID[item.lang]),
        "idCondition": str(CONDITION_ID[item.condition]),
        "price": f"{item.price:.2f}",
    }
    # Le formulaire peut être replié : champs renseignés en JS (mêmes événements qu'une saisie).
    page.evaluate(JS_FILL, [FORM, values])
    if not submit:
        return f"dry-run {values}"
    with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        page.evaluate("sel => document.querySelector(sel).requestSubmit()", FORM)
    browser.wait_cloudflare(page)
    return _confirm_published(page)


def pending(con: sqlite3.Connection, limit: int | None = None) -> list[Listing]:
    rows = con.execute(
        """SELECT i.*, c.cardmarket_id, c.name, c.set_code, c.collector_number
           FROM inventory i JOIN cards c ON c.id = i.card_id
           WHERE i.quantity > i.listed_quantity ORDER BY i.id"""
    ).fetchall()
    return [
        Listing(r["id"], r["card_id"], r["cardmarket_id"],
                f"{r['name']} [{r['set_code'].upper()} #{r['collector_number']}] {r['lang'].upper()}",
                r["lang"], r["condition"], r["price"], r["quantity"] - r["listed_quantity"])
        for r in rows[:limit]
    ]


def _ensure_logged_in(page: Page) -> None:
    browser.goto(page, CM_HOME_URL)
    if page.locator("input[name=userPassword]").count():   # le formulaire de connexion n'existe que déconnecté
        raise NotLoggedIn("Pas connecté à Cardmarket : lance « magicscanner login », connecte-toi, puis réessaie.")


def _list_item(con: sqlite3.Connection, page: Page, item: Listing, submit: bool, confirm: bool,
               report: Report, cancel: threading.Event | None) -> int:
    """Publie la ligne ; renvoie le nombre d'exemplaires mis en vente (partiel si annulé)."""
    if not item.cardmarket_id:
        raise ListingError("pas d'identifiant Cardmarket (Scryfall)")
    url = find_product_page(con, page, item.card_id, item.cardmarket_id)
    if url is None:
        raise ListingError("page produit introuvable")
    if confirm and input(f"  Lister {item.label} x{item.remaining} -> {url} ? [O/n] ").strip().lower() in ("n", "non"):
        return 0
    published = 0
    while item.remaining > 0 and not (cancel and cancel.is_set()):
        amount = min(item.remaining, MAX_AMOUNT)
        if page.url.split("?")[0] != url:
            browser.goto(page, url)
        message = put_for_sale(page, item, amount, submit)
        if submit:
            inventory.mark_listed(con, item.inventory_id, amount)
        item.remaining -= amount
        published += amount
        log.info("✓ %s x%d -> %s %s", item.label, amount, url, message)
        report({"event": "published", "label": item.label, "amount": amount, "url": url})
        page.wait_for_timeout(random.randint(1200, 2500))
    return published


def run(con: sqlite3.Connection, submit: bool = False, confirm: bool = False, limit: int | None = None,
        report: Report | None = None, cancel: threading.Event | None = None) -> Summary:
    """Met en vente le stock non encore publié. `report` reçoit les événements de progression,
    `cancel` demande un arrêt propre entre deux cartes."""
    report = report or (lambda _event: None)
    items = pending(con, limit)
    cards = sum(i.remaining for i in items)
    log.info("%d lignes (%d exemplaires) à lister (%s)", len(items), cards,
             "RÉEL" if submit else "dry-run, rien ne sera publié")
    report({"event": "start", "lines": len(items), "cards": cards})
    summary = Summary()
    try:
        with browser.cardmarket_page() as page:
            _ensure_logged_in(page)
            for item in items:
                if cancel and cancel.is_set():
                    summary.stopped = "arrêté à ta demande"
                    break
                try:
                    summary.published += _list_item(con, page, item, submit, confirm, report, cancel)
                except ListingError as e:
                    summary.errors += 1
                    inventory.mark_list_error(con, item.inventory_id, str(e))
                    log.error("✗ %s : %s", item.label, e)
                    report({"event": "error", "label": item.label, "message": str(e)})
    except (Unconfirmed, NotLoggedIn) as e:
        summary.stopped = str(e)
        log.error("%s", e)
    log.info("Terminé : %d exemplaires publiés, %d erreurs%s", summary.published, summary.errors,
             f" — {summary.stopped}" if summary.stopped else "")
    report({"event": "end", "published": summary.published, "errors": summary.errors, "stopped": summary.stopped})
    return summary
