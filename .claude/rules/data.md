---
paths:
  - "magicscanner/db.py"
  - "magicscanner/inventory.py"
  - "magicscanner/powertools.py"
  - "magicscanner/catalog/**"
  - "magicscanner/market/**"
---

# Données, stock, export

- Une impression = la fiche anglaise Scryfall (`cards.id`), qui porte le `cardmarket_id`. Les versions FR sont dans
  `localized`, rattachées par (édition, numéro).
- Ligne de stock = (impression, langue, état, prix, foil) avec une quantité (`UNIQUE` dans `INVENTORY_TABLE`).
  Le prix fait partie de la clé : des prix différents par carte sont prévus, ne le retire pas de la clé.
- `exported_quantity` suit ce qui est déjà parti dans un CSV Powertools : un export ne doit jamais renvoyer deux fois
  la même carte, sauf `everything=True`.
- Schéma : `CREATE TABLE IF NOT EXISTS` + `_migrate` (colonnes ajoutées, tables reconstruites en transaction).
  Une migration est idempotente et testée sur une base à l'ancien schéma.
- Import (`magicscanner import`) : réexécutable sans effet de bord, ne touche jamais `inventory` ni `listings`.
- Format Powertools : colonnes `COLUMNS` de `powertools.py`, cas FBB / FWB inclus. Ne change pas l'ordre des colonnes.
- Réseau : en-têtes `SCRYFALL_HEADERS` pour Scryfall (exigés par leur API). Les tests ne font pas d'appel réseau
  hors marqueur `integration`.
- cardmarket.com se lit seulement via le vrai Chrome en CDP (`market/browser.py`) : pas de scraping HTTP direct,
  pas de publication automatique d'annonces (retirée volontairement).
