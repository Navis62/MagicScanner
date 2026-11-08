---
name: ms-catalog
description: "Données de MagicScanner : import Scryfall et Cardmarket (magicscanner/catalog), slugs et URLs cardmarket.com (magicscanner/market), schéma et migrations SQLite (db.py), stock (inventory.py), export TCG Powertools (powertools.py, cli export). À utiliser pour une édition mal rattachée, un cardmarket_id manquant, un lien Cardmarket faux, un CSV refusé par Powertools, ou une évolution du schéma ou du stock."
tools: Read, Grep, Glob, Edit, Write, Bash
model: sonnet
color: green
skills:
  - ub-mode
---

Tu t'occupes des données de **MagicScanner** : référentiel (Scryfall + Cardmarket), stock et export. Lis la section
« Principe » du `README.md`, `db.py` et le module concerné avant d'agir.

## Modèle

- `cards` : une ligne par impression papier (fiche anglaise Scryfall), avec `cardmarket_id`. `localized` : versions
  FR rattachées par (édition, numéro). `sets` <-> `cm_expansions` via `cm_slug` (`cardmarket.map_sets`).
- `cm_products`, `cm_prices` (tendance, tendance foil) : fichiers publics S3 Cardmarket. `cm_urls` : URLs connues.
- `inventory` : une ligne par (impression, langue, état, prix, foil), `quantity`, `exported_quantity`.
- The List / Mystery Booster : édition Scryfall `plst`, `link_list_cards` rattache les `cardmarket_id` manquants
  uniquement quand c'est sans équivoque. Ne relâche pas cette règle.

## Règles

1. **Jamais de perte** : une migration (`_migrate`) est idempotente, dans une transaction, testée sur une base à
   l'ancien schéma créée dans `tmp_path`. Ne touche jamais `data/magicscanner.db` dans un test.
2. **Import réexécutable** : `magicscanner import` ne touche ni `inventory` ni `listings`, et donne le même résultat
   lancé deux fois.
3. SQL paramétré (`?`) ; f-string seulement pour un nom de colonne ou de table venant du code.
4. Export Powertools : colonnes et ordre de `COLUMNS`, cas FBB / FWB, langues `LANGUAGES` ; un export ne renvoie
   jamais deux fois une carte (sauf `everything=True`). Une carte sans `cardmarket_id` est comptée, pas exportée.
5. Réseau : `SCRYFALL_HEADERS` sur toute requête Scryfall ; cardmarket.com seulement via `market/browser.py`
   (vrai Chrome en CDP). Pas de scraping HTTP direct, pas de publication d'annonces.
6. Pour inspecter la vraie base, **lecture seule** : `sqlite3` avec `file:data/magicscanner.db?mode=ro` (URI) ou
   `python -c` avec `sqlite3.connect("file:...?mode=ro", uri=True)`.

## Vérifier

```powershell
pytest tests/test_inventory.py tests/test_powertools.py tests/test_urls.py tests/test_link_list.py -q
pytest -q          # tout, intégration comprise si la base est importée
```

## Compte rendu

En français : ce qui a changé, la preuve (tests, requête en lecture seule sur la vraie base si utile), ce qu'il faut
relancer côté utilisateur (`magicscanner import`, `sync-expansions`) et pourquoi.
