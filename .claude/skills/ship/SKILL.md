---
name: ship
description: "Livre le travail en cours de MagicScanner : vérifications, commits en français sur master, push vers origin. Use only when the user runs /ship or explicitly asks to commit and push."
disable-model-invocation: true
argument-hint: "[--no-push]"
---

# ship

Le dépôt avance par commits directs sur `master` (un seul développeur). `/ship` vaut accord pour commiter et pousser
**ce** travail, pas les suivants.

Branche : !`git branch --show-current`
État : !`git status --short`

## Étapes

1. **Vérifier** avec `/check`. Ne continue pas si ruff ou un test échoue : rapporte l'échec.
2. **Relire** `git status` : ne commite jamais `data/`, une base `.db`, un CSV d'export, un secret ni un réglage
   personnel (`.claude/settings.local.json`, `CLAUDE.local.md`). Ajoute les fichiers un par un, pas `git add -A`.
3. **Commits** petits et ordonnés, un sujet chacun. Message **en français** : un titre court qui dit ce qui change
   (« OCR : titre relu à pleine résolution sur les cartes sombres »), puis, si le commit n'est pas trivial, un corps :
   - **Pourquoi** : le défaut ou le besoin tel que l'utilisateur l'a vu ;
   - **Quoi** : ce qui change ;
   - **Preuve** : tests ajoutés (vus échouer avant le correctif), totaux pytest, photos de fixtures vérifiées.
   Termine par la ligne d'attribution demandée par l'environnement.
4. **Push** : `git push origin master`, sauf si `$ARGUMENTS` contient `--no-push`.
5. Rends compte : la liste des commits (`git log --oneline -5`) et le résultat du push.

## Garde-fous

Pas de `--force`, pas de `--no-verify`, pas de `--amend` d'un commit déjà poussé. Si le push est refusé (distant en
avance), rapporte-le et propose `git pull --rebase` sans le lancer.
