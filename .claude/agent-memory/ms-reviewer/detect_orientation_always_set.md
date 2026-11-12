---
name: detect-orientation-always-set
description: l'interface envoie toujours orientation portrait/landscape (jamais None) ; tout filtre sur orientation dans detect.find_card s'applique donc à chaque scan réel
metadata:
  type: project
---

`web/static/js/api.js` envoie `orientation` = "landscape" si rotation impaire sinon "portrait" : jamais vide en usage réel.
Les tests, eux, appellent souvent `find_card(img)` sans orientation, donc ne voient pas un filtre qui n'agit que si
`orientation` est posé.

**Why:** relecture 0e04eb2..27355c9 : `_oriented` écarte les contours dans l'autre sens ; carte couchée avec aperçu à 0 degré
(ou l'inverse) donne un cadre faux (mesuré sur les fixtures thrive/opportunity/sentinel : aire 110-130k au lieu de ~300k).

**How to apply:** pour tout changement de detect.py/card_rect.py, comparer find_card avec orientation=None, "landscape" et
"portrait" sur toutes les fixtures (script d'une vingtaine de lignes), pas seulement l'orientation attendue.
Autre piège de ce dépôt : regex OCR du pied de carte sans `\b` (« Illus. Franz » lu comme code d'édition « illus »).
