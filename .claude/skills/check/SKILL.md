---
name: check
description: "Vérification complète de MagicScanner avant de considérer un travail fini ou de commiter : ruff, tests rapides, tests d'intégration si la base est importée, cohérence README. À utiliser après une modification de code, ou quand l'utilisateur demande « vérifie », « lance les tests », « c'est bon ? »."
allowed-tools: Bash(.venv/Scripts/ruff check *) Bash(ruff check *) Bash(.venv/Scripts/python -m pytest *) Bash(pytest *) Bash(git status *) Bash(git diff *)
---

# check

Fichiers modifiés : !`git status --short`

1. `ruff check .`
2. `pytest -m "not integration" -q`
3. Si `data/magicscanner.db` existe : `pytest -m integration -q` (lent, utilise la vraie base en lecture).
4. Si `magicscanner/recognition/` a changé : `/diagnose-scan` sur `"tests/fixtures/*.jpg"` et comparer au
   comportement attendu de chaque photo.
5. README : si le diff touche un raccourci (`onKey` dans `main.js`), un bouton, une variable `MS_*` (`config.py`),
   une commande (`cli.py`) ou une limite connue, vérifier que le README le dit.

Rends compte en quelques lignes : résultat exact de chaque étape (passés / échoués / désélectionnés / sautés),
et pour un échec la cause probable avec `fichier:ligne`. Ne corrige rien sans le dire.
