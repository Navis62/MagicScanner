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

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** À z = 1 l'image est affichée à la hauteur de la fenêtre : plus large qu'elle, on en voit la partie centrale. */
function placement() {
  const vw = viewport.clientWidth, vh = viewport.clientHeight;
  const aspect = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 16 / 9;
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
  Object.assign(video.style, { width: `${p.W}px`, height: `${p.H}px`, transform: `translate(${p.tx}px, ${p.ty}px) scale(${p.z})` });
  $("zoom").value = view.z;
  $("zoom-val").textContent = view.z.toFixed(1) + "×";
  if (save) store.set("ms-view", view);
}

export const isDefaultZoom = () => view.z === 1;

export function frameOnCard(corners) {
  if (!corners || !video.videoWidth) return;
  const { vw, vh, W, H } = placement();
  const xs = corners.map((p) => p[0] / video.videoWidth), ys = corners.map((p) => p[1] / video.videoHeight);
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
}
