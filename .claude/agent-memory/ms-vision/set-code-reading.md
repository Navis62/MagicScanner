---
name: set-code-reading
description: Code d'édition lu en bas de carte — forme réelle des lignes OCR, longueur des codes imprimés, bonus « approchant » (2026-11-12)
metadata:
  type: project
---

Lignes réelles lues sur les photos webcam : « MM3·EN ANTHONY PALUMBO », « EMA·ENVINCENT PROCE », « MM3-ENBASTIEN »,
« MMS-EN » (MM3 mal lu), « MM2 -EN », « MM2·ENRON SPEARS », « MSH·EN IOHAN GRENIER ». Jamais lues : « MM2ENDAREN »
(sans séparateur), « MM2 <EN », « DOM TFR », « DOM-  DIST » (code perdu, le numéro suffit souvent).
Codes imprimés : 3 caractères pour toutes les éditions à ligne « code · langue » (depuis M15) ; en base, seuls
plst (code d'origine imprimé), cmb1/cmb2/ulst/sunf/ph* font plus. La regex exige donc 3 caractères, ce qui écarte
« ILLUS. FRANZ » et « JEAN-FRANCOIS ».
Bonus SET_CODE_NEAR : seulement si le code lu n'est celui d'aucune impression candidate (champ `candidate_codes` de
`Evidence`). Sur les 20 photos du soir : « approchant » sur Spire Monitor, Night Terrors, Chandra's Outrage (« MMS »).

**Why:** des faux codes bloquaient la lecture du vrai ; un code exact donnait encore +0,25 aux éditions voisines.

**How to apply:** avant d'élargir la regex, vérifier sur ces lignes réelles ; voir [[orientation-art-box]].
