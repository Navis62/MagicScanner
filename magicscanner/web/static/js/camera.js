// Webcam : choix de la caméra, démarrage, chien de garde (image figée / flux coupé), capture.
import { $, store } from "./dom.js";
import { setStatus } from "./view.js";

export const video = $("video");
const select = $("camera");
const canvas = $("canvas");
const STALL_MS = 4000;

let starting = false;

async function videoInputs() {
  return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
}

async function start(deviceId) {
  if (starting) return;
  starting = true;
  try {
    video.srcObject?.getTracks().forEach((t) => t.stop());
    video.srcObject = null;
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { deviceId: deviceId ? { exact: deviceId } : undefined, width: { ideal: 1920 }, height: { ideal: 1080 } },
    });
    stream.getVideoTracks()[0].addEventListener("ended", () => restart("flux coupé"));
    video.srcObject = stream;
    await video.play().catch(() => {});
    store.set("ms-camera", deviceId);
    setStatus("Prêt — Espace pour scanner");
  } catch (e) {
    const busy = e.name === "NotReadableError" || e.name === "AbortError";
    setStatus(busy
      ? "Caméra occupée (autre onglet ou application ?) — ferme-la puis clique « Relancer la caméra »"
      : `Caméra indisponible : ${e.name} ${e.message}`, "err");
  } finally {
    starting = false;
  }
}

export function restart(reason) {
  setStatus(`Caméra : ${reason}, relance…`, "busy");
  start(select.value);
}

function watchdog() {
  let lastTime = -1, stalledSince = null;
  setInterval(() => {
    if (starting || !video.srcObject || document.hidden) { stalledSince = null; return; }
    if (video.currentTime !== lastTime) { lastTime = video.currentTime; stalledSince = null; return; }
    stalledSince ??= Date.now();
    if (Date.now() - stalledSince > STALL_MS) { stalledSince = null; restart("image figée"); }
  }, 1000);
}

export async function initCamera() {
  let devices = await videoInputs();
  if (!devices.some((d) => d.label)) {
    // Libellés inconnus tant que l'accès n'a pas été autorisé une fois.
    (await navigator.mediaDevices.getUserMedia({ video: true })).getTracks().forEach((t) => t.stop());
    devices = await videoInputs();
  }
  select.replaceChildren(...devices.map((d) => new Option(d.label || "Caméra", d.deviceId)));
  const saved = store.get("ms-camera");
  // Par défaut, on évite la caméra virtuelle Elgato.
  const pick = devices.find((d) => d.deviceId === saved) || devices.find((d) => !/virtual/i.test(d.label)) || devices[0];
  if (pick) select.value = pick.deviceId;
  select.addEventListener("change", () => start(select.value));
  $("cam-restart").addEventListener("click", () => restart("relance manuelle"));
  watchdog();
  await start(select.value);
}

export const isReady = () => video.videoWidth > 0;

// Image pleine résolution (indépendante du zoom de l'aperçu).
export function grabFrame() {
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
}
