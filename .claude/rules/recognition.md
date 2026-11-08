---
paths:
  - "magicscanner/recognition/**"
  - "tests/test_recognition.py"
  - "tests/test_ocr.py"
  - "tests/test_scoring.py"
  - "tests/test_list_symbol.py"
---

# Reconnaissance (image webcam -> impression)

- Pipeline : `detect.find_card` (contours) -> `card_rect` (secours) -> OCR du titre -> `Catalog.match_names` -> candidats
  -> `scoring` (visuel + indices lus) -> `Recognition`. À défaut de contour, `_locate_by_text` retrouve la carte par son texte.
- Les poids et seuils sont des constantes nommées en tête de fichier (`scoring.py`, `recognizer.py`) : une seule
  décision à un seul endroit. N'en ajoute pas en dur dans le code.
- Toute modification se valide sur **toutes** les photos de `tests/fixtures/` (`/diagnose-scan`), pas seulement sur
  la carte qui posait problème : un gain sur une carte qui en casse une autre est une régression.
- Une photo qui échoue devient d'abord un test qui échoue (`/add-fixture`), ensuite seulement le correctif.
- Le temps de scan compte (l'utilisateur enchaîne les cartes à la touche Espace ; la localisation par le texte ajoute
  ~2,5 s et reste un secours). `diagnose.py` affiche la durée : compare avant / après tout changement qui touche
  l'OCR ou la comparaison d'images.
- L'OCR (RapidOCR / onnxruntime) est coûteux à initialiser : une seule instance de `OcrEngine`, jamais par scan.
- Images OpenCV en BGR, `np.uint8` ; les coins sont dans l'ordre haut-gauche, haut-droite, bas-droite, bas-gauche.
