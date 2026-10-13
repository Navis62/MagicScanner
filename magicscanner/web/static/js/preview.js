// Zoom numérique de l'aperçu (affichage uniquement : la capture reste en pleine résolution).
import { api } from "./api.js";
import { grabFrame, video } from "./camera.js";
import { $, store } from "./dom.js";
import { setStatus } from "./view.js";

const viewport = $("viewport");
const DEFAULT_VIEW = { z: 1, cx: 0.5, cy: 0.5 };   // zoom + centre (fractions de l'image)
const CARD_FILL = 0.8;                             // la carte occupe ~80 % de l'aperçu une fois cadrée
let view = { ...DEFAULT_VIEW, ...store.get("ms-view", {}) };

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
// Décalage (fraction de l'image) qui amène le centre c au milieu de l'aperçu, sans laisser de bord vide.
const offset = (c, z) => clamp(0.5 / z - c, 1 / z - 1, 0);

function apply(save = true) {
  view.z = clamp(view.z, 1, 5);
  video.style.transform = `scale(${view.z}) translate(${offset(view.cx, view.z) * 100}%, ${offset(view.cy, view.z) * 100}%)`;
  $("zoom").value = view.z;
  $("zoom-val").textContent = view.z.toFixed(1) + "×";
  if (save) store.set("ms-view", view);
}

export const isDefaultZoom = () => view.z === 1;

export function frameOnCard(corners) {
  if (!corners || !video.videoWidth) return;
  const xs = corners.map((p) => p[0] / video.videoWidth), ys = corners.map((p) => p[1] / video.videoHeight);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  view = { z: Math.min(CARD_FILL / (x1 - x0), CARD_FILL / (y1 - y0)), cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
  apply();
}

async function frameOnDetectedCard() {
  const { corners } = await api.detect(await grabFrame());
  if (corners) frameOnCard(corners);
  else setStatus("Carte non détectée pour le cadrage", "err");
}

export function initPreview() {
  video.addEventListener("loadedmetadata", () => {
    viewport.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
    apply(false);
  });
  viewport.addEventListener("wheel", (e) => {
    e.preventDefault();
    view.z *= e.deltaY < 0 ? 1.1 : 1 / 1.1;
    apply();
  }, { passive: false });
  viewport.addEventListener("click", (e) => {
    const r = viewport.getBoundingClientRect();
    view.cx = (e.clientX - r.left) / r.width / view.z - offset(view.cx, view.z);
    view.cy = (e.clientY - r.top) / r.height / view.z - offset(view.cy, view.z);
    apply();
  });
  const slider = $("zoom");
  slider.addEventListener("input", () => { view.z = +slider.value; apply(); });
  slider.addEventListener("change", () => slider.blur());   // Espace doit rester au scan
  $("zoom-card").addEventListener("click", frameOnDetectedCard);
  $("zoom-reset").addEventListener("click", () => { view = { ...DEFAULT_VIEW }; apply(); });
}
