"""python -m magicscanner <commande>"""
import argparse
import csv
import sys
import webbrowser

from . import db


def main() -> None:
    ap = argparse.ArgumentParser(prog="magicscanner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="télécharge/importe Scryfall + catalogue et prix Cardmarket")
    p.add_argument("--skip-download", action="store_true", help="réutilise le fichier Scryfall déjà téléchargé")
    sub.add_parser("sync-expansions", help="récupère les slugs officiels des extensions sur Cardmarket (Chrome)")
    sub.add_parser("login", help="ouvre le Chrome dédié pour se connecter à Cardmarket")
    p = sub.add_parser("serve", help="lance l'interface de scan")
    p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("list", help="met en vente sur Cardmarket ce qui n'est pas encore listé")
    p.add_argument("--submit", action="store_true", help="publie réellement (sinon dry-run)")
    p.add_argument("--confirm", action="store_true", help="demande confirmation pour chaque carte")
    p.add_argument("--limit", type=int)
    sub.add_parser("status", help="résumé de l'inventaire")
    p = sub.add_parser("export", help="exporte l'inventaire en CSV")
    p.add_argument("path", nargs="?", default="inventaire.csv")
    a = ap.parse_args()

    con = db.connect()
    db.init(con)

    if a.cmd == "import":
        from . import data_import
        data_import.run(con, skip_download=a.skip_download)
    elif a.cmd == "sync-expansions":
        from . import expansions
        expansions.sync(con)
    elif a.cmd == "login":
        from . import browser
        browser.ensure_chrome("https://www.cardmarket.com/fr/Magic/MainPage/Login")
        print("Connecte-toi dans la fenêtre Chrome ; la session est conservée dans data/chrome-profile.")
    elif a.cmd == "serve":
        import uvicorn
        url = f"http://127.0.0.1:{a.port}"
        print(f"Interface : {url}")
        webbrowser.open(url)
        uvicorn.run("magicscanner.server:app", host="127.0.0.1", port=a.port, log_level="warning")
    elif a.cmd == "list":
        from . import lister
        lister.run(con, submit=a.submit, confirm=a.confirm, limit=a.limit)
    elif a.cmd == "status":
        from . import inventory
        st = inventory.stats(con)
        print(f"{st['cards']} cartes ({st['lines']} lignes), {st['listed']} listées, {st['to_list']} à lister, "
              f"valeur {st['value']:.2f} €")
        for r in con.execute("SELECT list_error, COUNT(*) n FROM inventory WHERE list_error IS NOT NULL GROUP BY 1"):
            print(f"  erreur listing : {r['list_error']} ({r['n']})")
    elif a.cmd == "export":
        from . import cardmarket
        rows = con.execute(
            """SELECT i.*, c.name, c.set_code, c.collector_number, c.cardmarket_id, s.name AS set_name
               FROM inventory i JOIN cards c ON c.id=i.card_id JOIN sets s ON s.code=c.set_code ORDER BY s.name, c.name"""
        ).fetchall()
        with open(a.path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["nom", "edition", "code", "numero", "langue", "etat", "prix", "quantite", "listees", "id_cardmarket", "url"])
            for r in rows:
                w.writerow([r["name"], r["set_name"], r["set_code"], r["collector_number"], r["lang"], r["condition"],
                            r["price"], r["quantity"], r["listed_quantity"], r["cardmarket_id"],
                            cardmarket.product_url(con, r["card_id"])])
        print(f"{len(rows)} lignes -> {a.path}")


if __name__ == "__main__":
    sys.exit(main())
