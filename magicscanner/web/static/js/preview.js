// Aperçu de la caméra : une fenêtre portrait sur l'image, avec zoom et recentrage.
// Affichage uniquement : la capture envoyée à la reconnaissance reste l'image entière, en pleine résolution.
import { api } from "./api.js";
import { grabFrame, video } from "./camera.js";
import { $, store } from "./dom.js";
import { setStatus } from "./view.js";

const viewport = $("viewport");
const DEFAULT_VIEW = { z: 1, cx: 0.5, cy: 0.5 };   // zoom + point de l'image au centre de la fenêtre (fractions 0-1)
const CARD_FILL = 0.8;                             // la carte occupe ~80 % de la fenêtre une fois cadrée
const MAX_ZOOM = 5;
const WHEEL_STEP = 1.1;
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

  viewport.addEventListener("click", (e) => {
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
