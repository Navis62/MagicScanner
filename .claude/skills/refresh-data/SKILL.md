---
name: refresh-data
description: "Met à jour le référentiel de MagicScanner (Scryfall, catalogue et prix Cardmarket, slugs d'extensions) après une sauvegarde de la base. Use only when the user runs /refresh-data or explicitly asks to reimport the catalogue."
disable-model-invocation: true
argument-hint: "[--skip-download] [--expansions]"
---

# refresh-data

`/refresh-data` vaut accord pour télécharger (~400 Mo) et réécrire le référentiel dans `data/magicscanner.db`.

1. **Le serveur est-il lancé ?** S'il tourne (port 8765), demande à l'utilisateur de l'arrêter : l'import écrit
   dans la base qu'il utilise.
2. **Sauvegarde** : copie `data/magicscanner.db` vers `data/magicscanner.backup-<AAAAMMJJ>.db` (format des
   sauvegardes existantes). Avec SQLite en WAL, passe par l'API de sauvegarde plutôt qu'une copie de fichier :
   `.venv/Scripts/python -c "import sqlite3; s=sqlite3.connect('data/magicscanner.db'); d=sqlite3.connect('data/magicscanner.backup-<AAAAMMJJ>.db'); s.backup(d); d.close(); s.close()"`.
   Relève avant : `magicscanner status` (nombre de cartes et de lignes du stock).
3. **Import** : `magicscanner import $ARGUMENTS` (`--skip-download` réutilise le fichier Scryfall déjà téléchargé).
   Lance-le en arrière-plan : il prend plusieurs minutes.
4. **Extensions** (si `--expansions` ou si une extension est sortie) : `magicscanner sync-expansions`. Il ouvre le
   vrai Chrome de l'utilisateur : préviens-le avant.
5. **Contrôle** : `magicscanner status` doit donner le même stock qu'avant. Sinon, arrête-toi et signale-le (la
   sauvegarde permet de revenir en arrière ; ne la restaure pas sans accord).
6. Rends compte : durée, nombre de cartes et d'éditions importées (logs), cardmarket_id rattachés pour The List,
   stock inchangé. Propose de supprimer les sauvegardes de plus d'un mois, sans le faire.
