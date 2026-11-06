// Aperçu de la caméra : une fenêtre portrait sur l'image, avec zoom et recentrage.
// La capture reste l'image entière en pleine résolution ; zoomé, le serveur n'en analyse que la zone affichée (cropArea).
import { api } from "./api.js";
import { grabFrame, video } from "./camera.js";
import { $, store } from "./dom.js";
import { setStatus } from "./view.js";

const viewport = $("viewport");
const DEFAULT_VIEW = { z: 1, cx: 0.5, cy: 0.5 };   // zoom + point de l'image au centre de la fenêtre (fractions 0-1)
const CARD_FILL = 0.8;                             // la carte occupe ~80 % de la fenêtre une fois cadrée
const MAX_ZOOM = 5;
const WHEEL_STEP = 1.1;
const DRAG_THRESHOLD = 4;                          // pixels : en deçà, c'est un clic (recentrage), pas un glisser
let view = { ...DEFAULT_VIEW, ...store.get("ms-view", {}) };
// Rotation de l'aperçu en quarts de tour horaires (0-3) : une carte couchée dans l'image, titre à gauche, apparaît
// droite avec 1. `view` est exprimé dans l'image tournée, telle qu'affichée.
let turns = store.get("ms-rotation", 0) % 4;
const sideways = () => turns % 2 === 1;
// Point de l'image d'origine (fractions) -> point de l'image affichée.
const TO_DISPLAY = [([x, y]) => [x, y], ([x, y]) => [1 - y, x], ([x, y]) => [1 - x, 1 - y], ([x, y]) => [y, 1 - x]];

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** À z = 1 l'image est affichée à la hauteur de la fenêtre : plus large qu'elle, on en voit la partie centrale. */
function placement() {
  const vw = viewport.clientWidth, vh = viewport.clientHeight;
  const native = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 16 / 9;
  const aspect = sideways() ? 1 / native : native;     // proportions de l'image telle qu'affichée
  const W = vh * aspect, H = vh;                    // taille de l'image à z = 1, en pixels
  const z = clamp(view.z, 1, MAX_ZOOM);
  // coin haut-gauche de l'image : le point voulu au centre de la fenêtre, sans jamais laisser de bord vide
  const tx = clamp(vw / 2 - view.cx * W * z, vw - W * z, 0);
  const ty = clamp(vh / 2 - view.cy * H * z, vh - H * z, 0);
  return { vw, vh, W, H, z, tx, ty };
}

function apply(save = true) {
  const p = placement();
  if (!p.vw || !p.vh) return;
  view.z = p.z;
  view.cx = (p.vw / 2 - p.tx) / (p.W * p.z);        // centre réellement affiché (après recadrage dans l'image)
  view.cy = (p.vh / 2 - p.ty) / (p.H * p.z);
  // L'élément vidéo garde ses proportions d'origine (W et H échangés de côté) ; la rotation autour de l'origine le
  // fait sortir de la fenêtre, la translation qui la précède l'y ramène.
  const [ew, eh] = sideways() ? [p.H, p.W] : [p.W, p.H];
  const back = [null, `${eh}px, 0`, `${ew}px, ${eh}px`, `0, ${ew}px`][turns];
  const turn = turns ? ` translate(${back}) rotate(${90 * turns}deg)` : "";
  Object.assign(video.style, { width: `${ew}px`, height: `${eh}px`, transform: `translate(${p.tx}px, ${p.ty}px) scale(${p.z})${turn}` });
  $("zoom").value = view.z;
  $("zoom-val").textContent = view.z.toFixed(1) + "×";
  if (save) store.set("ms-view", view);
}

export const isDefaultZoom = () => view.z === 1;

const CROP_MARGIN = 0.25;   // marge autour de la zone affichée (fraction de sa taille) : carte un peu hors cadre
// Point de l'image affichée -> point de l'image d'origine (inverse de TO_DISPLAY).
const TO_SOURCE = [([x, y]) => [x, y], ([x, y]) => [y, 1 - x], ([x, y]) => [1 - x, 1 - y], ([x, y]) => [1 - y, x]];

/** Zone de l'image d'origine à analyser (fractions x0, y0, x1, y1) : ce que montre l'aperçu zoomé, plus une marge. Sans
 * zoom, toute l'image (null). Le tapis, la boîte et les cartes voisines hors champ ne peuvent plus passer pour la carte. */
export function cropArea() {
  if (view.z <= 1) return null;
  const { vw, vh, W, H, z, tx, ty } = placement();
  if (!vw || !vh) return null;
  const [dx0, dy0, dx1, dy1] = [-tx / (W * z), -ty / (H * z), (vw - tx) / (W * z), (vh - ty) / (H * z)];
  const mx = CROP_MARGIN * (dx1 - dx0), my = CROP_MARGIN * (dy1 - dy0);
  const [a, b] = [TO_SOURCE[turns]([dx0 - mx, dy0 - my]), TO_SOURCE[turns]([dx1 + mx, dy1 + my])];
  const box = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
  return box.map((v) => clamp(v, 0, 1));
}

export function frameOnCard(corners) {
  if (!corners || !video.videoWidth) return;
  const { vw, vh, W, H } = placement();
  const pts = corners.map(([x, y]) => TO_DISPLAY[turns]([x / video.videoWidth, y / video.videoHeight]));
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  view = {
    z: Math.min((CARD_FILL * vw) / ((x1 - x0) * W), (CARD_FILL * vh) / ((y1 - y0) * H)),
    cx: (x0 + x1) / 2,
    cy: (y0 + y1) / 2,
  };
  apply();
}

async function frameOnDetectedCard() {
  const { corners } = await api.detect(await grabFrame());
  if (corners) frameOnCard(corners);
  else setStatus("Carte non détectée pour le cadrage", "err");
}

/** Point de l'image (fractions) sous un point de la fenêtre (pixels). */
function imagePointAt(px, py) {
  const p = placement();
  return { x: (px - p.tx) / (p.W * p.z), y: (py - p.ty) / (p.H * p.z) };
}

export function initPreview() {
  video.addEventListener("loadedmetadata", () => apply(false));
  new ResizeObserver(() => apply(false)).observe(viewport);

  viewport.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = viewport.getBoundingClientRect();
    const px = e.clientX - r.left, py = e.clientY - r.top;
    const under = imagePointAt(px, py);             // le point sous le curseur reste sous le curseur
    const z = clamp(view.z * (e.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP), 1, MAX_ZOOM);
    const { vw, vh, W, H } = placement();
    view = { z, cx: under.x - (px - vw / 2) / (W * z), cy: under.y - (py - vh / 2) / (H * z) };
    apply();
  }, { passive: false });

  // Glisser (zoom > 1) : l'image suit la souris, pour amener la carte au centre. Un simple clic recentre toujours.
  let drag = null;   // { id, x, y, cx, cy, moved }
  let dragged = false;   // le clic qui suit un glisser ne recentre pas sur le point lâché
  viewport.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    dragged = false;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY, cx: view.cx, cy: view.cy, moved: false };
  });
  viewport.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    if (!drag.moved) {
      drag.moved = true;
      viewport.setPointerCapture(e.pointerId);
      viewport.classList.add("dragging");
    }
    const { W, H, z } = placement();
    view.cx = drag.cx - dx / (W * z);
    view.cy = drag.cy - dy / (H * z);
    apply(false);
  });
  const endDrag = (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (drag.moved) {
      viewport.classList.remove("dragging");
      store.set("ms-view", view);
      dragged = true;
    }
    drag = null;
  };
  viewport.addEventListener("pointerup", endDrag);
  viewport.addEventListener("pointercancel", endDrag);

  viewport.addEventListener("click", (e) => {
    if (dragged) return;
    const r = viewport.getBoundingClientRect();
    const at = imagePointAt(e.clientX - r.left, e.clientY - r.top);
    view.cx = at.x;
    view.cy = at.y;
    apply();
  });

  const slider = $("zoom");
  slider.addEventListener("input", () => { view.z = +slider.value; apply(); });
  slider.addEventListener("change", () => slider.blur());   // Espace doit rester au scan
  $("zoom-card").addEventListener("click", frameOnDetectedCard);
  $("zoom-reset").addEventListener("click", () => { view = { ...DEFAULT_VIEW }; apply(); });
  const rotate = $("cam-rotate");
  const showTurns = () => { $("rotate-val").textContent = `${90 * turns}°`; rotate.classList.toggle("active", turns > 0); };
  showTurns();
  rotate.addEventListener("click", () => {
    turns = (turns + 1) % 4;
    store.set("ms-rotation", turns);
    showTurns();
    view = { ...DEFAULT_VIEW };                     // le cadrage précédent était exprimé dans l'autre orientation
    apply();
    rotate.blur();                                  // Espace doit rester au scan
  });
}
