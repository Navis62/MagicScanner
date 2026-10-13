"""Mise en vente sur Cardmarket via Playwright (Chrome réel rattaché en CDP, session déjà connectée).

Pour chaque ligne d'inventaire non encore listée :
  1. reconstruit l'URL produit (variantes de slug, puis recherche dans l'extension en dernier recours) ;
  2. vérifie que la page est la bonne : le champ caché idAddProduct du formulaire = cardmarket_id Scryfall ;
  3. remplit quantité / langue / état / prix et clique « Put for sale ».
"""
import random
import sqlite3

from playwright.sync_api import Page

from . import browser, cardmarket
from .cardmarket import CM_CONDITION, CM_LANGUAGE_ID

MAX_AMOUNT = 30  # limite du formulaire Cardmarket


def _form_product_id(page: Page) -> int | None:
    el = page.locator("#ListProductForm input[name=idAddProduct]")
    if el.count() == 0:
        return None
    v = el.first.get_attribute("value")
    return int(v) if v and v.isdigit() else None


def resolve_url(con: sqlite3.Connection, page: Page, card_id: str, id_product: int) -> str | None:
    cached = con.execute("SELECT url FROM cm_urls WHERE id_product=?", (id_product,)).fetchone()
    tried = [cached["url"]] if cached else []
    tried += [u for u in cardmarket.candidate_urls(con, card_id) if u not in tried]
    for url in tried:
        browser.goto(page, url)
        if _form_product_id(page) == id_product:
            break
    else:
        url = _search_fallback(con, page, card_id, id_product)
        if url is None:
            return None
    con.execute("INSERT OR REPLACE INTO cm_urls VALUES (?,?)", (id_product, url))
    con.commit()
    return url


def _search_fallback(con: sqlite3.Connection, page: Page, card_id: str, id_product: int) -> str | None:
    """Recherche par nom dans la page de l'extension, puis ouvre chaque résultat jusqu'au bon idProduct."""
    urls = cardmarket.candidate_urls(con, card_id)
    label = cardmarket.product_label(con, card_id)
    if not urls or not label:
        return None
    exp_url = urls[0].rsplit("/", 1)[0]
    browser.goto(page, f"{exp_url}?searchString={label[0].split(' / ')[0]}")
    links = page.eval_on_selector_all(
        "a[href*='/Products/Singles/']",
        "els => [...new Set(els.map(e => e.href.split('?')[0]).filter(h => h.split('/').length > 8))]",
    )
    for link in links[:8]:
        browser.goto(page, link)
        if _form_product_id(page) == id_product:
            return link
    return None


def _flash_message(page: Page) -> tuple[bool, str]:
    ok = page.locator(".alert-success")
    if ok.count():
        return True, ok.first.inner_text().strip()
    err = page.locator(".alert-danger, .alert-warning")
    if err.count():
        return False, err.first.inner_text().strip()
    return True, ""


def list_one(page: Page, amount: int, lang: str, condition: str, price: float, submit: bool) -> tuple[bool, str]:
    form = "#ListProductForm"
    values = {
        "amount": str(amount),
        "idLanguage": str(CM_LANGUAGE_ID[lang]),
        "idCondition": str(CM_CONDITION[condition]),
        "price": f"{price:.2f}",
    }
    # Le formulaire peut être replié : on renseigne les champs en JS (mêmes événements qu'une saisie).
    page.evaluate(
        """([sel, values]) => {
            const f = document.querySelector(sel);
            for (const [name, v] of Object.entries(values)) {
                const el = f.elements[name];
                el.value = v;
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }
            for (const name of ['isFoil', 'isSigned', 'isAltered']) if (f.elements[name]) f.elements[name].checked = false;
        }""",
        [form, values],
    )
    if not submit:
        return True, f"dry-run : {values}"
    with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        page.evaluate("sel => document.querySelector(sel).requestSubmit()", form)
    browser.wait_cloudflare(page)
    return _flash_message(page)


def run(con: sqlite3.Connection, submit: bool = False, confirm: bool = False, limit: int | None = None) -> None:
    rows = con.execute(
        """SELECT i.*, c.cardmarket_id, c.name, c.set_code, c.collector_number
           FROM inventory i JOIN cards c ON c.id = i.card_id
           WHERE i.quantity > i.listed_quantity ORDER BY i.id"""
    ).fetchall()
    if limit:
        rows = rows[:limit]
    print(f"{len(rows)} lignes à lister ({'RÉEL' if submit else 'dry-run, rien ne sera publié'})")
    done = errors = 0
    with browser.cardmarket_page() as page:
        for r in rows:
            label = f"{r['name']} [{r['set_code'].upper()} #{r['collector_number']}] {r['lang'].upper()} x{r['quantity'] - r['listed_quantity']}"
            if not r["cardmarket_id"]:
                _error(con, r["id"], "pas de cardmarket_id Scryfall")
                print(f"  ✗ {label} : pas d'identifiant Cardmarket")
                errors += 1
                continue
            url = resolve_url(con, page, r["card_id"], r["cardmarket_id"])
            if url is None:
                _error(con, r["id"], "page produit introuvable")
                print(f"  ✗ {label} : page produit introuvable")
                errors += 1
                continue
            if confirm and input(f"  Lister {label} -> {url} ? [O/n] ").strip().lower() in ("n", "non"):
                continue
            remaining = r["quantity"] - r["listed_quantity"]
            while remaining > 0:
                amount = min(remaining, MAX_AMOUNT)
                if page.url.split("?")[0] != url:
                    browser.goto(page, url)
                ok, msg = list_one(page, amount, r["lang"], r["condition"], r["price"], submit)
                if not ok:
                    _error(con, r["id"], msg)
                    print(f"  ✗ {label} : {msg}")
                    errors += 1
                    break
                if submit:
                    con.execute(
                        "UPDATE inventory SET listed_quantity = listed_quantity + ?, list_error = NULL, updated_at = CURRENT_TIMESTAMP WHERE id=?",
                        (amount, r["id"]),
                    )
                    con.commit()
                remaining -= amount
                print(f"  ✓ {label} -> {url}  {msg}")
                page.wait_for_timeout(random.randint(1200, 2500))
            else:
                done += 1
    print(f"Terminé : {done} OK, {errors} erreurs")


def _error(con: sqlite3.Connection, inv_id: int, msg: str) -> None:
    con.execute("UPDATE inventory SET list_error=? WHERE id=?", (msg[:300], inv_id))
    con.commit()
