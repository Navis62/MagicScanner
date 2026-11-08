---
name: add-fixture
description: "Transforme une vraie photo webcam (scan raté, carte confondue) en test de régression pytest dans tests/fixtures, écrit avant le correctif et vu échouer. À utiliser quand une carte est mal reconnue et qu'on veut verrouiller le comportement attendu."
argument-hint: "<chemin de l'image> <impression attendue, ex. « c13 87 fr »>"
---

# add-fixture

Arguments : `$ARGUMENTS` (image source, puis l'impression attendue : édition, numéro, langue, foil éventuel).
S'il manque l'impression attendue, demande-la : ne la devine pas à partir de ce que la reconnaissance a trouvé.

## Étapes

1. **Regarder la photo** (Read) : vérifier qu'on voit bien la carte attendue et qu'elle ne montre rien de personnel
   (visage, papiers). Sinon, demander une autre photo ou la recadrer.
2. **Copier** dans `tests/fixtures/` sous un nom qui dit la carte et le problème, dans la forme des existants :
   `<carte>_<édition>_<langue>_<problème>.jpg` (ex. `dirty_wererat_half_contour_failed.jpg`). Moins de ~500 Ko :
   sinon réenregistrer en JPEG qualité 85 avec OpenCV.
3. **Écrire le test** dans le fichier de test qui correspond à l'étape fautive (voir `/diagnose-scan`) :
   - détection / cadrage, sans base : coins attendus à une tolérance près (`test_recognition.py`,
     `test_detects_and_straightens_card`) ;
   - OCR, sans base : titre, numéro, langue lus (`test_ocr.py`) ;
   - impression retenue, avec base : `@pytest.mark.integration` + `skipif(not DB_PATH.exists(), ...)`, et vérifier
     `set_code`, `collector_number`, `lang` de `rec.best`.
   Docstring en français qui décrit la photo (« Photo webcam réelle : … »).
4. **Le voir échouer** pour la bonne raison : `pytest <fichier>::<test> -q`. S'il passe déjà, le dire : le bug n'est
   pas reproduit par ce test (orientation, édition fixée, foil ?) ; ajuster avant d'aller plus loin.
5. Rendre compte : fichier ajouté, test, sortie de l'échec. Le correctif est une étape suivante (`ms-vision`).
