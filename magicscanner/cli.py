"""Ligne de commande : python -m magicscanner <commande> (ou `magicscanner <commande>` une fois installé)."""
import argparse
import csv
import logging
import webbrowser

from . import db, inventory
from .config import CM_LOGIN_URL, ensure_dirs


def cmd_import(con, args) -> None:
    from . import catalog
    catalog.update(con, skip_download=args.skip_download)


def cmd_sync_expansions(con, args) -> None:
    from .market import expansions
    expansions.sync(con)


def cmd_login(con, args) -> None:
    from .market import browser
    browser.ensure_chrome(CM_LOGIN_URL)
    print("Connecte-toi dans la fenêtre Chrome ; la session est conservée dans data/chrome-profile.")


def cmd_serve(con, args) -> None:
    import uvicorn
    url = f"http://127.0.0.1:{args.port}"
    print(f"Interface : {url}")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run("magicscanner.web.app:app", host="127.0.0.1", port=args.port, log_level="warning")


def cmd_list(con, args) -> None:
    from .market import lister
    lister.run(con, submit=args.submit, confirm=args.confirm, limit=args.limit)


def cmd_status(con, args) -> None:
    st = inventory.stats(con)
    print(f"{st['cards']} cartes ({st['lines']} lignes), {st['listed']} listées, {st['to_list']} à lister, "
          f"valeur {st['value']:.2f} €")
    for r in inventory.list_errors(con):
        print(f"  erreur de listing : {r['list_error']} ({r['n']})")


def cmd_history(con, args) -> None:
    rows = inventory.listings(con, args.limit)
    for r in reversed(rows):
        print(f"{r['listed_local']}  {r['name']} [{r['set_code'].upper()} #{r['collector_number']}] "
              f"{r['lang'].upper()} {r['condition']}  x{r['amount']} à {r['price']:.2f} €")
    print(f"{len(rows)} mises en vente affichées")


def cmd_export(con, args) -> None:
    from .market import urls
    rows = inventory.export_rows(con)
    with open(args.path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["nom", "edition", "code", "numero", "langue", "etat", "prix", "quantite", "listees", "id_cardmarket", "url"])
        for r in rows:
            w.writerow([r["name"], r["set_name"], r["set_code"], r["collector_number"], r["lang"], r["condition"],
                        r["price"], r["quantity"], r["listed_quantity"], r["cardmarket_id"],
                        urls.product_url(con, r["card_id"])])
    print(f"{len(rows)} lignes -> {args.path}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="magicscanner")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="télécharge/importe Scryfall + catalogue et prix Cardmarket")
    p.add_argument("--skip-download", action="store_true", help="réutilise le fichier Scryfall déjà téléchargé")
    p.set_defaults(func=cmd_import)

    sub.add_parser("sync-expansions", help="récupère les slugs officiels des extensions (Chrome)").set_defaults(func=cmd_sync_expansions)
    sub.add_parser("login", help="ouvre le Chrome dédié pour se connecter à Cardmarket").set_defaults(func=cmd_login)

    p = sub.add_parser("serve", help="lance l'interface de scan")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="n'ouvre pas le navigateur")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("list", help="met en vente sur Cardmarket ce qui n'est pas encore listé")
    p.add_argument("--submit", action="store_true", help="publie réellement (sinon dry-run)")
    p.add_argument("--confirm", action="store_true", help="demande confirmation pour chaque carte")
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_list)

    sub.add_parser("status", help="résumé de l'inventaire").set_defaults(func=cmd_status)

    p = sub.add_parser("history", help="journal des mises en vente (carte, prix, quantité, date)")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("export", help="exporte l'inventaire en CSV")
    p.add_argument("path", nargs="?", default="inventaire.csv")
    p.set_defaults(func=cmd_export)
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    for noisy in ("httpx", "RapidOCR"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ensure_dirs()
    con = db.connect()
    try:
        args.func(con, args)
    finally:
        con.close()
