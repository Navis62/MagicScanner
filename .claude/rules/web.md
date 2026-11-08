---
paths:
  - "magicscanner/web/**"
---

# Interface et API

- `web/app.py` : FastAPI, paramètres en `Annotated[...]`. Le serveur n'écoute que sur 127.0.0.1 ; ne change pas l'hôte.
- `web/static/` : modules ES natifs (`import ... from "./x.js"`), sans framework, sans bundler, sans npm.
  Un nouveau module s'importe depuis `main.js` ; les accès DOM passent par `dom.js` (`$`, `store`).
- Toute action asynchrone passe par `safe(...)` (`main.js`) pour finir dans la barre d'état en cas d'erreur.
- Le scan se pilote au clavier : un raccourci ajouté ou changé doit apparaître dans le tableau des touches du README
  et ne pas se déclencher quand le focus est dans un champ de saisie. Piège : ces champs sont listés à la main par
  `id` au début de `onKey` (`main.js`) ; un nouveau `<input>` doit y être ajouté, sinon taper « f » ou « e »
  dedans déclenche le raccourci.
- Textes affichés en français. Noms de cartes et d'éditions viennent de Scryfall : toute valeur insérée dans un
  gabarit `innerHTML` passe par `esc()` (`dom.js`) ; sinon `textContent`.
- Préférences de l'utilisateur (seuil d'alerte, édition fixée, caméra) : mémorisées via `store` (localStorage).
- Vérifier une modification dans le vrai navigateur (`magicscanner serve`) : les tests ne couvrent pas l'interface.
