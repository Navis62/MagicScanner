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
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m magicscanner import            # ~400 Mo Scryfall + catalogue Cardmarket (quelques minutes)
.\.venv\Scripts\python -m magicscanner login             # ouvre Chrome (profil data/chrome-profile) : se connecter à Cardmarket
.\.venv\Scripts\python -m magicscanner sync-expansions   # slugs officiels des extensions
```

Relancer `import` de temps en temps pour rafraîchir les prix et les nouvelles éditions
(puis `sync-expansions` si une extension est sortie).

## Scanner

```powershell
.\.venv\Scripts\python -m magicscanner serve
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

```powershell
.\.venv\Scripts\python -m magicscanner list                        # dry-run : ouvre chaque page, remplit, ne publie pas
.\.venv\Scripts\python -m magicscanner list --submit --confirm --limit 5   # premiers essais : confirmation carte par carte
.\.venv\Scripts\python -m magicscanner list --submit               # tout le reste
.\.venv\Scripts\python -m magicscanner status
.\.venv\Scripts\python -m magicscanner export inventaire.csv
```

L'URL est reconstruite (`/en/Magic/Products/Singles/<Extension>/<Carte>`) puis **vérifiée** : le formulaire de
vente contient l'idProduct, qui doit être égal au `cardmarket_id` Scryfall. Les slugs Cardmarket n'étant pas
réguliers (`Akroma-s-Memorial`, `LimDuls-Cohort`, `Plains-V-1`), plusieurs variantes sont essayées, puis une
recherche dans l'extension ; l'URL validée est mémorisée (table `cm_urls`). Seule la quantité pas encore
listée est publiée (`listed_quantity`), on peut donc relancer sans doublon.

## Configuration (variables d'environnement)

`MS_PRICE` (0.20), `MS_PRICE_ALERT` (1.00), `MS_CHROME` (chemin chrome.exe), `MS_CDP_PORT` (9222),
`MS_WINDOW` (`left,top,width,height` de la fenêtre Chrome, `40,40,1500,1000`), `MS_DATA` (dossier `data/`).

## Limites connues (POC)

- Rééditions à illustration et cadre identiques : départagées surtout par le symbole d'édition et le numéro
  de collection ; vérifier visuellement et corriger avec `1`–`9` si besoin.
- Cartes split / aventure / à faces multiples : le nom lu est celui de la première face.
- Foil non géré (toujours non-foil).
