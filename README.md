# MagicScanner

Scanner webcam de cartes Magic (communes / unco, VO ou VF, foil ou non, NM) puis export du stock vers TCG Powertools, qui met les cartes en vente sur Cardmarket (0,18 € par défaut, prix modifiable au scan).

## Principe

| Étape | Outil |
|---|---|
| Capture | Webcam dans le navigateur (interface locale FastAPI) |
| Détection + redressement de la carte | OpenCV (contour du bord noir, perspective -> 630×880) ; si le bord se fond dans l'ombre, la carte est retrouvée par son texte (titre + ligne du bas lus sur l'image entière) |
| Lecture du nom / numéro / code d'édition | [RapidOCR](https://github.com/RapidAI/RapidOCR) (PaddleOCR en ONNX, gère les accents) |
| Identification | Recherche floue du nom VO **et** VF dans la base Scryfall (`all_cards`), puis choix de l'impression : symbole d'édition + cadre (comparaison avec les images Scryfall), numéro de collection, code d'édition (cadres récents), cohérence de langue |
| Référentiel Cardmarket | Fichiers publics `products_singles` et `price_guide` (S3 Cardmarket) + slugs officiels des extensions lus sur cardmarket.com |
| Mise en vente | Export CSV vers **TCG Powertools** (aucune publication directe) |

Une impression = la fiche anglaise Scryfall (qui porte le `cardmarket_id`). L'inventaire est une ligne par
(impression, langue, état, prix, foil) avec une quantité : scanner deux fois la même carte incrémente la quantité.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
magicscanner import            # ~400 Mo Scryfall + catalogue Cardmarket (quelques minutes)
magicscanner sync-expansions   # slugs officiels des extensions (ouvre Chrome, sert aux liens Cardmarket)
```

Relancer `import` de temps en temps pour les nouvelles éditions (puis `sync-expansions` si une extension est sortie).
Les prix tendance se mettent à jour à part, depuis l'interface (bouton « Prix tendance ↻ »).

## Scanner

```powershell
magicscanner serve
```

Ouvre http://127.0.0.1:8765. Choisir la webcam (la caméra virtuelle Elgato est écartée par défaut).
Sous l'aperçu : zoom, « Cadrer », « Autofocus » (relance la mise au point), « Figer le focus » (la verrouille) et « Relancer » (le flux).

| Touche | Action |
|---|---|
| `Espace` | scanne la carte (elle est ajoutée au stock immédiatement) |
| `Échap` / `Retour arrière` | annule le dernier scan ; chaque appui remonte d'un scan |
| `+` / « Encore une » | ajoute un exemplaire de plus de la dernière carte (même impression, langue, finition, prix) sans la scanner |
| `1`–`9` / clic | corrige : remplace par une autre impression proposée |
| `L` | bascule VO / VF |
| `F` | coche / décoche « Foil » |
| `/` | recherche manuelle par nom (VO ou VF) si la reconnaissance échoue (barre en haut de page) |

**Foil et prix** : la case « Foil » et le champ « Prix » (0,18 € par défaut, `MS_PRICE`) s'appliquent aux scans suivants,
et à la dernière carte scannée si on les change juste après. Un foil, ou une carte à un autre prix, forme sa propre ligne
de stock. Une impression qui n'existe pas dans la finition scannée n'est jamais choisie (foil-only pour une carte non-foil
et inversement).

**Édition fixée** : pour un paquet d'une seule édition, le champ « Édition » (touche `E`, nom ou code de l'édition) limite
la reconnaissance aux cartes de cette édition, avec leurs noms VO comme VF. C'est plus rapide (seules ses impressions sont comparées)
et il y a moins de confusions possibles. Une carte d'une autre édition glissée dans le paquet est quand même reconnue si son nom est lu nettement
mieux, mais elle est signalée en orange (« hors de l'édition fixée »). Le choix est mémorisé ; ✕ revient à toutes les éditions.

Un cadre orange = confiance faible ou choix ambigu entre deux impressions (autre produit Cardmarket) : à vérifier.
Le prix tendance Cardmarket (foil si la case est cochée) est affiché ; si elle dépasse le prix de vente de plus du seuil réglable
(champ « Alerte + », 0,50 € par défaut, mémorisé dans le navigateur), il passe en rouge et une alarme sonore retentit. « Prix tendance ↻ » retélécharge le guide des prix
Cardmarket (mis à jour chaque nuit).

## Exporter et mettre en vente

La mise en vente se fait avec **TCG Powertools** : MagicScanner ne publie plus rien sur Cardmarket lui-même.

**Export TCG Powertools** : le bouton « Export Powertools (N) » télécharge un CSV (format de `example-import.csv`)
des cartes scannées depuis le dernier export, puis les marque comme exportées. Les cartes sans identifiant Cardmarket
sont laissées de côté (signalé dans la barre d'état). `/api/export?everything=true` réexporte tout le stock sans rien marquer.

**Lien Cardmarket** : le bouton « Lien Cardmarket » ouvre la fiche de la carte (en français, avec les filtres vendeurs/langues/état
de `CM_BROWSE_QUERY` dans `config.py`) dans un nouvel onglet. Le slug est reconstruit (`/Magic/Products/Singles/<Extension>/<Carte>`) ;
les slugs Cardmarket n'étant pas réguliers (`Akroma-s-Memorial`, `LimDuls-Cohort`, `Plains-V-1`), la variante la plus probable est
proposée, et une URL connue dans la table `cm_urls` passe avant.

**En ligne de commande** :

```powershell
magicscanner status
magicscanner export inventaire.csv
```

Les anciennes tables `listings` (journal des prix des publications passées) et les colonnes `listed_quantity` / `list_error`
restent dans la base, mais plus rien n'y écrit.

## Cartes « The List » et « Mystery Booster »

Ces cartes sont identiques à leur impression d'origine (même cadre, même numéro, même code d'édition) à un détail
près : l'**étincelle de Planeswalker** dans la bordure noire, en bas à gauche. Le symbole ne dit pas laquelle des deux
(The List, Mystery Booster, Mystery Booster 2…) : Scryfall les regroupe dans la même édition (`plst`) et c'est
l'identifiant Cardmarket de la carte qui donne l'extension où elle se vend (autre extension, donc autre prix).

Le détecteur ([list_symbol.py](magicscanner/recognition/list_symbol.py)) cherche cette étincelle par reconnaissance de forme
dans une petite zone fixe. S'il la voit, l'impression `plst` est privilégiée ; sinon, c'est l'impression d'origine.
Quand une carte existe en plusieurs versions `plst` (ex. Extract from Darkness : 2X2-210 et E01-84), c'est le code
d'édition et le numéro d'origine imprimés sur la carte qui départagent (« 2X2 » ou « E01 »).
L'écran de scan affiche un badge avec l'extension réelle (« Mystery Booster », « The List »…), la ligne « Vendue dans »
et ce que la caméra a vu (« étincelle vue / douteuse / pas d'étincelle »). Sur des images dégradées comme une webcam,
99 % des cartes à étincelle sont détectées pour 0 % de fausses alertes. Si une carte est mal classée, `1`–`9` permet
de choisir l'autre impression.

Scryfall ne donne pas l'identifiant Cardmarket d'environ 1 carte `plst` sur 5. `magicscanner import` retrouve celui de
583 d'entre elles par le nom, uniquement quand c'est sans équivoque (un seul produit de ce nom dans The List / Mystery
Booster / Mystery Booster 2, pas déjà pris, une seule carte concernée). Les ~570 autres sont reconnues mais ne sont pas
exportées (comptées comme « sans identifiant Cardmarket » dans la barre d'état).

Limite : l'étincelle n'a été validée que sur des images simulées, pas encore sur une vraie carte.

## Organisation du code

```
magicscanner/
  cli.py              commandes (import, sync-expansions, serve, status, export)
  config.py           chemins, prix, Chrome, URLs des sources (surcharge MS_*)
  db.py               schéma SQLite et connexion
  inventory.py        stock : scans, annulation, correction, suivi des exports
  powertools.py       export CSV pour TCG Powertools
  catalog/            données de référence
    scryfall.py         import des éditions et des cartes (bulk all_cards, VO + VF)
    cardmarket.py       import du catalogue et des prix Cardmarket, rattachement éditions -> extensions
    lookup.py           Catalog : recherche floue des noms, impressions, fiche d'affichage
  recognition/        image webcam -> impression
    detect.py           localisation et redressement de la carte (contours)
    card_rect.py        détection de secours : rectangle aux proportions de carte dont les bords sont les mieux soutenus
                        (carte collée à la paroi de la boîte, pile de cartes, bord noir peu visible)
    ocr.py              RapidOCR + extraction du titre, du numéro, du code d'édition, de la langue ;
                        position de la carte déduite de son titre quand les contours échouent
    visual.py           comparaison avec les images Scryfall (cadre, symbole d'édition)
    list_symbol.py      détection de l'étincelle « The List » (gabarit dans assets/)
    scoring.py          score d'une impression candidate (poids réglables en tête de fichier)
    recognizer.py       pipeline complet (contours -> OCR ; à défaut, carte localisée par son texte)
  market/             site cardmarket.com
    urls.py             variantes d'URL produit, lien de navigation filtré
    browser.py          Chrome réel piloté en CDP (lecture des slugs d'extensions)
    expansions.py       liste officielle des extensions
  web/                interface de scan
    app.py              API FastAPI
    static/             index.html, style.css, js/ (main, camera, preview, tools, view, api, sound, dom)
tests/                pytest ; tests/fixtures contient de vraies photos webcam (régressions de détection)
```

## Tests

```powershell
pytest              # tout
pytest -m "not integration"   # sans la base importée
```

## Configuration (variables d'environnement)

`MS_PRICE` (0.18, prix par défaut du champ « Prix »), `MS_KEEP_SCANS` (`low` : photos gardées seulement pour les scans à vérifier ; `none` ou `all`), `MS_CHROME` (chemin chrome.exe), `MS_CDP_PORT` (9222),
`MS_WINDOW` (`left,top,width,height` de la fenêtre Chrome, `40,40,1500,1000`), `MS_DATA` (dossier `data/`).

## Limites connues (POC)

- Rééditions à illustration et cadre identiques : départagées surtout par le symbole d'édition et le numéro
  de collection ; vérifier visuellement et corriger avec `1`–`9` si besoin.
- Cartes split / aventure / à faces multiples (dont les cartes à bascule de Kamigawa) : le nom lu est celui de la première face.
- Certaines cartes n'ont pas de fiche française chez Scryfall (ex. les cartes à bascule de Champions of Kamigawa) : leur nom VF est alors absent de la base et la carte risque d'être confondue avec un nom voisin (« Adepte de sang » lu « Orateur de sang »). Les noms connus sont ajoutés à la main dans `MISSING_FR_NAMES` ([lookup.py](magicscanner/catalog/lookup.py)).
- Les images de référence Scryfall sont mises en cache en 366 px (~46 Ko) : suffisant pour départager les éditions.
- Vérifier le numéro de collection quand le choix est ambigu : le pied de carte est souvent illisible pour l'OCR.
- La localisation par le texte (carte à bord noir perdu dans l'ombre) exige un titre et une ligne du bas lisibles, et une carte à peu près droite ; elle ajoute ~2,5 s au scan concerné. Comme la ligne du bas est incertaine (cartes à bascule : nom retourné), plusieurs positions de carte sont essayées jusqu'à ce que le nom soit reconnu.
- Les images de scans ratés sont gardées (20 dernières) dans `data/scans/failed/` pour diagnostic.
