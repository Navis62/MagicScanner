# MagicScanner

Scanner webcam de cartes Magic -> identification de l'impression (Scryfall) -> stock SQLite -> export CSV TCG Powertools
(mise en vente Cardmarket). Projet perso, un seul développeur, Windows, interface locale sur 127.0.0.1:8765.
Le README décrit le fonctionnement et l'organisation du code : @README.md

## Commandes

```powershell
.\.venv\Scripts\activate
pytest -m "not integration" -q          # rapide, sans la base importée (~5 s)
pytest                                  # tout, y compris l'intégration (data/magicscanner.db requise)
pytest tests/test_scoring.py::test_nom  # un seul test
ruff check .                            # lint (pas de ruff format : le style du code est voulu)
magicscanner serve --no-browser         # interface
python .claude/skills/diagnose-scan/scripts/diagnose.py <image>   # passe une photo dans la reconnaissance
```

## Règles du dépôt

- **Français** partout : interface, messages, docstrings, commentaires, noms de tests, commits.
- **`data/` est l'état réel de l'utilisateur** (base de stock, profil Chrome connecté à Cardmarket, caches de 400 Mo) :
  ne jamais le supprimer, le réinitialiser ni écrire dedans à la main. Les tests utilisent `tmp_path` (fixture `con`).
  Ne jamais lire `data/chrome-profile/` (cookies de session).
- Toute évolution de schéma passe par `_migrate` dans `magicscanner/db.py` et doit garder le stock existant.
- SQL paramétré uniquement (`?`) ; une f-string SQL n'est admise que pour un nom de colonne ou de table issu du code.
- Un changement de reconnaissance se prouve sur les vraies photos de `tests/fixtures/` : pas de seuil retouché « au jugé ».
- Mettre à jour le README quand un comportement visible change (raccourci, bouton, variable `MS_*`, limite connue).
- Commits directs sur `master`, petits, message en français. Pas de push sans demande (`/ship`).

## Où regarder

- Règles détaillées par zone : `.claude/rules/` (chargées automatiquement selon les fichiers touchés).
- Agents : `ms-architect` (conception, lecture seule), `ms-vision` (reconnaissance), `ms-catalog` (données, stock,
  export), `ms-web` (API + interface), `ms-tester`, `ms-reviewer` (relecture, lecture seule).
- Skills : `/check`, `/diagnose-scan`, `/add-fixture`, `/refresh-data`, `/ship`, `/ub-mode`, `/tech-debt-audit`.
