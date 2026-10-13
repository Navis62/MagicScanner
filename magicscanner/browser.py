"""Pilotage d'un vrai Chrome via CDP.

Cardmarket est derrière Cloudflare : un navigateur lancé par Playwright est bloqué, alors qu'un Chrome
lancé normalement (profil dédié, session Cardmarket mémorisée) puis rattaché via CDP passe.
"""
import socket
import subprocess
import time
from contextlib import contextmanager

from playwright.sync_api import Page, sync_playwright

from .config import CDP_PORT, CHROME_EXE, CHROME_PROFILE, WINDOW


def _port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", CDP_PORT)) == 0


def ensure_chrome(url: str = "about:blank") -> None:
    if _port_open():
        return
    subprocess.Popen([
        CHROME_EXE, f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={CHROME_PROFILE}",
        "--no-first-run", "--no-default-browser-check",
        f"--window-position={WINDOW[0]},{WINDOW[1]}", f"--window-size={WINDOW[2]},{WINDOW[3]}", url,
    ])
    for _ in range(40):
        if _port_open():
            return
        time.sleep(0.25)
    raise RuntimeError("Chrome ne répond pas sur le port CDP")


def wait_cloudflare(page: Page, timeout_s: int = 60) -> None:
    """Attend la fin d'un éventuel challenge Cloudflare (« Just a moment... »)."""
    for _ in range(timeout_s * 2):
        title = page.title().lower()
        if "moment" not in title and "instant" not in title:
            break
        page.wait_for_timeout(500)
    page.wait_for_load_state("domcontentloaded")


def _resize(ctx, page: Page) -> None:
    """Fenêtre assez grande pour suivre la mise en ligne, et au premier plan."""
    try:
        cdp = ctx.new_cdp_session(page)
        wid = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {
            "left": WINDOW[0], "top": WINDOW[1], "width": WINDOW[2], "height": WINDOW[3]}})
        page.bring_to_front()
    except Exception as e:  # confort uniquement
        print(f"  (redimensionnement Chrome impossible : {e})")


@contextmanager
def cardmarket_page():
    ensure_chrome()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
        ctx = browser.contexts[0]
        page = ctx.new_page()
        _resize(ctx, page)
        try:
            yield page
        finally:
            page.close()
            browser.close()  # se détache seulement, Chrome reste ouvert


def goto(page: Page, url: str) -> int | None:
    resp = page.goto(url, wait_until="domcontentloaded")
    wait_cloudflare(page)
    return resp.status if resp else None
