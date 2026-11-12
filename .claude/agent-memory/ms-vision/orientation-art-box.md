---
name: orientation-art-box
description: find_card avec orientation annoncée — distinguer cadre d'illustration couché et carte posée dans l'autre sens ; indices essayés et leur résultat (2026-11-12)
metadata:
  type: project
---

Un contour dans l'autre sens que l'orientation annoncée est soit le cadre de l'illustration (1,36:1, donc aux
proportions d'une carte tournée), soit la carte elle-même posée dans l'autre sens que l'aperçu (↻ oublié).
Critère retenu (2026-11-12) : c'est un cadre d'illustration seulement si la carte déduite autour (`_card_around_art`)
tient dans l'image ; sinon c'est une carte. Mesuré : sépare tous les cas des fixtures et des 20 photos du soir
(images zoomées, carte ~20 % de l'image -> carte déduite ~54 %, hors image).

**Why:** 0e04eb2 écartait tout contour mal orienté : une carte posée dans l'autre sens n'était plus trouvée (échec
« Nom illisible » sur les 4 fixtures `*_art_box` annoncées en portrait).

**How to apply:** cas non résolu = carte droite petite dans une image NON zoomée annoncée « landscape »
(gargantua_c13_fr) : la carte déduite tient dans l'image. Indices déjà essayés, AUCUN ne sépare (ne pas réessayer) :
soutien Canny des côtés de la carte déduite (0,22-0,28 art vs 0,30 carte), noirceur de la bordure Q vs déduite (191457
inversé, 190635 à 15 vs 17), soutien du cadre ART_BOX dans Q redressé (0,09-0,97 partout), densité de bords entre Q et
la carte déduite (reckless 0,074 vs gargantua 0,065-0,074). Piste restante : décider à l'OCR (recognizer).
Les fixtures `*_art_box` sont aujourd'hui trouvées par leur contour (RATIO_TOL 0,16) ; seule
`gravedigger_ema_en_art_box_only` passe par la carte déduite du cadre d'illustration. Voir [[set-code-reading]].
