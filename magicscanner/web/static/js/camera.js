// Webcam : choix de la caméra, démarrage, chien de garde (image figée / flux coupé), capture.
import { $, store } from "./dom.js";
import { setStatus } from "./view.js";

export const video = $("video");
const select = $("camera");
const canvas = $("canvas");
const STALL_MS = 4000;

let starting = false;
let frozen = false;   // mise au point verrouillée (mode manuel)

function showFrozen(on) {
  frozen = on;
  $("cam-freeze").textContent = on ? "Focus figé ✔" : "Figer le focus";
  $("cam-freeze").classList.toggle("active", on);
}

async function videoInputs() {
  return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
}

async function start(deviceId) {
  if (starting) return;
  starting = true;
  try {
    video.srcObject?.getTracks().forEach((t) => t.stop());
    video.srcObject = null;
    showFrozen(false);   // un nouveau flux repart en autofocus
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

/** Relance la mise au point : un autofocus ponctuel si la caméra le permet, sinon on sort du mode continu et on y
 * revient ; à défaut de réglage de focus, on relance le flux. */
export async function refocus() {
  const track = video.srcObject?.getVideoTracks()[0];
  const modes = track?.getCapabilities?.().focusMode;
  if (!modes?.length) return restart("pas de réglage de focus, relance du flux");
  const set = (focusMode) => track.applyConstraints({ advanced: [{ focusMode }] });
  try {
    if (modes.includes("single-shot")) await set("single-shot");
    else if (modes.includes("manual") && modes.includes("continuous")) {
      await set("manual");
      await new Promise((r) => setTimeout(r, 300));
      await set("continuous");
      showFrozen(false);
    } else return restart("autofocus non relançable, relance du flux");
    setStatus("Autofocus relancé", "busy");
    setTimeout(() => !frozen && modes.includes("continuous") && set("continuous").catch(() => {}), 1500);
  } catch {
    restart("autofocus indisponible, relance du flux");
  }
}

/** Verrouille la mise au point là où elle est (ou la libère) : utile quand l'autofocus pompe sur la pile de cartes. */
async function toggleFreeze() {
  const track = video.srcObject?.getVideoTracks()[0];
  const caps = track?.getCapabilities?.() ?? {};
  if (!caps.focusMode?.includes("manual")) return setStatus("Cette caméra ne permet pas de figer le focus", "err");
  const advanced = frozen
    ? { focusMode: caps.focusMode.includes("continuous") ? "continuous" : "manual" }
    : { focusMode: "manual", ...(track.getSettings().focusDistance != null && { focusDistance: track.getSettings().focusDistance }) };
  try {
    await track.applyConstraints({ advanced: [advanced] });
    showFrozen(!frozen);
    setStatus(frozen ? "Focus figé — Autofocus puis « Figer » pour le recaler" : "Autofocus continu rétabli", "busy");
  } catch (e) {
    setStatus("Réglage du focus refusé : " + e.message, "err");
  }
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
  $("cam-focus").addEventListener("click", refocus);
  $("cam-freeze").addEventListener("click", toggleFreeze);
  watchdog();
  await start(select.value);
}

export const isReady = () => video.videoWidth > 0;

// Image pleine résolution (indépendante du zoom de l'aperçu).
export async function grabFrame() {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  // Le canvas peut rester noir alors que l'aperçu s'affiche (décodage GPU, caméra virtuelle) : on essaie une autre voie.
  const sources = [() => video, () => createImageBitmap(video)];
  for (const source of sources) {
    ctx.drawImage(await source(), 0, 0);
    if (!isBlank(ctx)) return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
  }
  restart("image capturée noire");
  throw new Error("Capture noire : la caméra est relancée, réessaie dans un instant");
}

/** Vrai si l'image est entièrement noire (échantillon de pixels répartis sur tout le canvas). */
function isBlank(ctx) {
  const { width, height } = canvas;
  for (let i = 1; i <= 8; i++) {
    const d = ctx.getImageData(Math.floor((width * i) / 9), Math.floor((height * i) / 9), 1, 1).data;
    if (d[0] + d[1] + d[2] > 12) return false;
  }
  return true;
}
