---
name: detect-misoriented-quads-compete
description: depuis la correction "carte posée dans l'autre sens que l'aperçu", les quads mal orientés dont la carte déduite sort de l'image entrent dans `candidates` à égalité de score avec les quads orientés
metadata:
  type: project
---

Relecture du 2026-11-12 (diff non commité detect.py `_shapes`) : un quad perpendiculaire à l'orientation annoncée est
promu en candidat normal dès que `_card_around_art` sort de l'image, donc tout grand rectangle aux proportions de carte
(panneau, couvercle, tapis) bat la vraie carte plus petite et bien orientée (tri par aire). Reproduit en synthétique
(carte 500x350 sur panneau portrait 640x894, "landscape") : ancien code = la carte, nouveau = le panneau.
Les 51 combinaisons fixture x orientation ne le voient pas (aucun écart quand l'orientation est la bonne).

**How to apply:** pour tout changement de detect.py, comparer ancien/nouveau (`git archive HEAD magicscanner` dans le
scratchpad, script `find_card` sur toutes les fixtures x {None, portrait, landscape}) ET écrire un cas synthétique où
une grande forme perpendiculaire entoure la vraie carte. Les écarts attendus sont seulement ceux d'orientation fausse.

Fait vérifié en base (2026-11-12) : toutes les éditions d'extension/core/commander/masters depuis M15 ont un code
Scryfall à 3 caractères (les codes de 4+ sont tokens `t…`, promos `p…`, art series `a…`, minijeux `m…`, alchemy `y…`).
