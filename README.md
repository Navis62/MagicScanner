# MagicScanner

Scanner webcam de cartes Magic (communes / unco, VO ou VF, NM) et mise en vente sur Cardmarket à prix fixe (0,20 €).

## Principe

| Étape | Outil |
|---|---|
| Capture | Webcam dans le navigateur (interface locale FastAPI) |
| Détection + redressement de la carte | OpenCV (contour du bord noir, perspective -> 630×880) |
| Lecture du nom / numéro / code d'édition | [RapidOCR](https://github.com/RapidAI/RapidOCR) (PaddleOCR en ONNX, gère les accents) |
| Identification | Recherche floue du nom VO **et** VF dans la base Scryfall (`all_cards`), puis choix de l'impression : symbole d'édition + cadre (comparaison avec les images Scryfall), numéro de collection, code d'édition (cadres récents), cohérence de langue |
| Référentiel Cardmarket | Fichiers publics `products_singles` et `price_guide` (S3 Cardmarket) + slugs officiels des extensions lus sur cardmarket.com |
| Mise en vente | Playwright rattaché en CDP à un **vrai Chrome** (Cloudflare bloque un navigateur lancé par Playwright) |

Une impression = la fiche anglaise Scryfall (qui porte le `cardmarket_id`). L'inventaire est une ligne par
(impression, langue, état, prix) avec une quantité : scanner deux fois la même carte incrémente la quantité.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
magicscanner import            # ~400 Mo Scryfall + catalogue Cardmarket (quelques minutes)
magicscanner login             # ouvre Chrome (profil data/chrome-profile) : se connecter à Cardmarket
magicscanner sync-expansions   # slugs officiels des extensions
```

Relancer `import` de temps en temps pour rafraîchir les prix et les nouvelles éditions
(puis `sync-expansions` si une extension est sortie).

## Scanner

```powershell
magicscanner serve
```

Ouvre http://127.0.0.1:8765. Choisir la webcam (la caméra virtuelle Elgato est écartée par défaut).

| Touche | Action |
|---|---|
| `Espace` | scanne la carte (elle est ajoutée au stock immédiatement) |
| `Échap` / `Retour arrière` | annule le dernier scan |
| `1`–`9` / clic | corrige : remplace par une autre impression proposée |
| `L` | bascule VO / VF |
| `/` | recherche manuelle par nom (VO ou VF) si la reconnaissance échoue |

Un cadre orange = confiance faible, à vérifier. Le prix tendance Cardmarket est affiché, avec une alerte
si la carte vaut plus de 1 € (`MS_PRICE_ALERT`).

## Mettre en vente

**Depuis l'interface** : le bouton « Publier N cartes sur Cardmarket » (en haut) met en vente tout ce qui ne l'est
pas encore, après confirmation. « Tester avec 1 » n'en publie qu'une, pour un premier essai. Un rapport s'affiche
à la fin (cartes publiées, erreurs) et « Arrêter » interrompt proprement après la carte en cours. Tu peux continuer
à scanner pendant la publication : les nouvelles cartes seront publiées au clic suivant.

**Exemplaires déjà publiés** : le stock distingue « en stock » et « déjà en vente ». Scanner un 2e exemplaire d'une
carte déjà publiée n'annonce que ce 2e exemplaire (l'écran de scan indique « dont 1 déjà en vente — 1 à publier »).
Un exemplaire déjà publié ne peut plus être annulé ni corrigé depuis l'outil : il faut retirer l'annonce sur Cardmarket.

**Sécurité** : une annonce n'est comptée comme publiée qu'après le bandeau de confirmation vert de Cardmarket. Si le
site ne confirme ni n'affiche d'erreur, tout s'arrête (capture dans `data/publish-debug/`) plutôt que de risquer des
doublons. Si tu n'es pas connecté à Cardmarket, rien n'est tenté.

**En ligne de commande** :

```powershell
magicscanner list                        # dry-run : ouvre chaque page, remplit, ne publie pas
magicscanner list --submit --confirm --limit 5   # premiers essais : confirmation carte par carte
magicscanner list --submit               # tout le reste
magicscanner status
magicscanner export inventaire.csv
```

L'URL est reconstruite (`/en/Magic/Products/Singles/<Extension>/<Carte>`) puis **vérifiée** : le formulaire de
vente contient l'idProduct, qui doit être égal au `cardmarket_id` Scryfall. Les slugs Cardmarket n'étant pas
réguliers (`Akroma-s-Memorial`, `LimDuls-Cohort`, `Plains-V-1`), plusieurs variantes sont essayées, puis une
recherche dans l'extension ; l'URL validée est mémorisée (table `cm_urls`). Seule la quantité pas encore
listée est publiée (`listed_quantity`), on peut donc relancer sans doublon.

## Organisation du code

```
magicscanner/
  cli.py              commandes (import, login, sync-expansions, serve, list, status, export)
  config.py           chemins, prix, Chrome, URLs des sources (surcharge MS_*)
  db.py               schéma SQLite et connexion
  inventory.py        stock : scans, annulation, correction, progression du listing
  catalog/            données de référence
    scryfall.py         import des éditions et des cartes (bulk all_cards, VO + VF)
    cardmarket.py       import du catalogue et des prix Cardmarket, rattachement éditions -> extensions
    lookup.py           Catalog : recherche floue des noms, impressions, fiche d'affichage
  recognition/        image webcam -> impression
    detect.py           localisation et redressement de la carte
    ocr.py              RapidOCR + extraction du titre, du numéro, du code d'édition, de la langue
    visual.py           comparaison avec les images Scryfall (cadre, symbole d'édition)
    scoring.py          score d'une impression candidate (poids réglables en tête de fichier)
    recognizer.py       pipeline complet
  market/             site cardmarket.com
    urls.py             variantes d'URL produit, URLs validées
    browser.py          Chrome réel piloté en CDP
    expansions.py       liste officielle des extensions
    lister.py           mise en vente
  web/                interface de scan
    app.py              API FastAPI
    static/             index.html, style.css, js/ (main, camera, preview, view, api, sound, dom)
tests/                pytest ; tests/fixtures contient une vraie photo webcam
```

## Tests

```powershell
pytest              # tout
pytest -m "not integration"   # sans la base importée
```

## Configuration (variables d'environnement)

`MS_PRICE` (0.20), `MS_PRICE_ALERT` (1.00), `MS_KEEP_SCANS` (`low` : photos gardées seulement pour les scans à vérifier ; `none` ou `all`), `MS_CHROME` (chemin chrome.exe), `MS_CDP_PORT` (9222),
`MS_WINDOW` (`left,top,width,height` de la fenêtre Chrome, `40,40,1500,1000`), `MS_DATA` (dossier `data/`).

## Limites connues (POC)

- Rééditions à illustration et cadre identiques : départagées surtout par le symbole d'édition et le numéro
  de collection ; vérifier visuellement et corriger avec `1`–`9` si besoin.
- Cartes split / aventure / à faces multiples : le nom lu est celui de la première face.
- Les images de référence Scryfall sont mises en cache en 366 px (~46 Ko) : suffisant pour départager les éditions.
- Foil non géré (toujours non-foil).
