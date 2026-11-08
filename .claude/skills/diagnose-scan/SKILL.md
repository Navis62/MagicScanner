---
name: diagnose-scan
description: "Passe une ou plusieurs photos de carte dans la reconnaissance de MagicScanner et explique le résultat (titre lu, lignes OCR, candidats et leurs scores, durée). À utiliser quand une carte est mal reconnue ou non détectée, pour les scans ratés de data/scans/failed, ou pour comparer toutes les fixtures avant / après un changement de reconnaissance."
argument-hint: "[image | motif glob | failed] [--orientation landscape] [--locked-set CODE] [--foil]"
allowed-tools: Bash(.venv/Scripts/python .claude/skills/diagnose-scan/scripts/diagnose.py *) Bash(python .claude/skills/diagnose-scan/scripts/diagnose.py *) Read
---

# diagnose-scan

Base importée : !`.venv/Scripts/python -c "from magicscanner.config import DB_PATH; print('oui' if DB_PATH.exists() else 'NON : lancer magicscanner import')"`
Scans ratés disponibles : !`ls data/scans/failed 2>/dev/null | wc -l`

## Lancer

```bash
.venv/Scripts/python .claude/skills/diagnose-scan/scripts/diagnose.py $ARGUMENTS
```

Sans argument, passe toutes les fixtures : `"tests/fixtures/*.jpg"` (guillemets : le script développe le motif).
`failed` = les 20 derniers scans ratés gardés par l'interface. Options : `--orientation portrait|landscape` (l'aperçu
était tourné à 90°), `--locked-set <code>` (édition fixée), `--foil`, `--top N`, `--save <dossier>` (carte redressée ;
utilise le dossier scratchpad, jamais `data/` ni `tests/`).

Le script est en lecture seule : il n'ajoute rien au stock. Il faut compter environ 1 à 3 s par photo.

## Lire le résultat

Pour chaque photo, situe l'étape fautive :

| Symptôme | Étape | Où regarder |
|---|---|---|
| `ÉCHEC`, aucune ligne OCR | détection / cadrage | `detect.py`, `card_rect.py` ; `--save` et ouvrir l'image redressée |
| titre lu faux ou vide | OCR du titre | `ocr.py` (zone du titre, résolution `OCR_MAX_HEIGHT`) |
| bon nom, mauvaise impression | scoring | raisons et `visuel` des candidats, poids de `scoring.py` |
| nom VF inconnu | catalogue | `MISSING_FR_NAMES` dans `catalog/lookup.py` |
| `AMBIGU` | deux produits Cardmarket proches | écart de score entre les candidats 1 et 2 |
| durée > 2 s | localisation par le texte | `Recognizer._locate_by_text` a pris le relais |

Rends compte en français : par photo, ce qui a été reconnu, l'étape en cause et l'hypothèse de correction. Pour une
photo à garder comme test de régression, propose `/add-fixture`.
