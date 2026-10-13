// MagicScanner — interface de scan.
const $ = (id) => document.getElementById(id);
const video = $("video"), canvas = $("canvas");
let current = null;      // { scan_id, card, lang, alternatives, undone }
let busy = false;

// ---------- Webcam ----------
async function listCameras() {
  // Une première autorisation est nécessaire pour obtenir les libellés.
  const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
  tmp.getTracks().forEach((t) => t.stop());
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
  const sel = $("camera");
  sel.innerHTML = devices.map((d) => `<option value="${d.deviceId}">${d.label || "Caméra"}</option>`).join("");
  let saved = null;
  try { saved = localStorage.getItem("ms-camera"); } catch {}
  // Par défaut, on évite la caméra virtuelle Elgato.
  const pick = devices.find((d) => d.deviceId === saved) || devices.find((d) => !/virtual/i.test(d.label)) || devices[0];
  if (pick) sel.value = pick.deviceId;
  await startCamera(sel.value);
}

async function startCamera(deviceId) {
  if (video.srcObject) video.srcObject.getTracks().forEach((t) => t.stop());
  video.srcObject = await navigator.mediaDevices.getUserMedia({
    video: { deviceId: deviceId ? { exact: deviceId } : undefined, width: { ideal: 1920 }, height: { ideal: 1080 } },
  });
  try { localStorage.setItem("ms-camera", deviceId); } catch {}
}
$("camera").addEventListener("change", (e) => startCamera(e.target.value));

// ---------- Zoom de l'aperçu (affichage uniquement, la capture reste en pleine résolution) ----------
const viewport = $("viewport");
let view = { z: 1, cx: 0.5, cy: 0.5 };   // zoom + centre (fractions de l'image)
let lastCorners = null;
try { view = { ...view, ...JSON.parse(localStorage.getItem("ms-view") || "{}") }; } catch {}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const offset = (c, z) => clamp(0.5 / z - c, 1 / z - 1, 0);

function applyView(save = true) {
  view.z = clamp(view.z, 1, 5);
  video.style.transform = `scale(${view.z}) translate(${offset(view.cx, view.z) * 100}%, ${offset(view.cy, view.z) * 100}%)`;
  $("zoom").value = view.z;
  $("zoom-val").textContent = view.z.toFixed(1) + "×";
  if (save) try { localStorage.setItem("ms-view", JSON.stringify(view)); } catch {}
}

function frameOnCard(corners) {
  if (!corners || !video.videoWidth) return;
  const W = video.videoWidth, H = video.videoHeight;
  const xs = corners.map((p) => p[0] / W), ys = corners.map((p) => p[1] / H);
  const bw = Math.max(...xs) - Math.min(...xs), bh = Math.max(...ys) - Math.min(...ys);
  view.cx = (Math.max(...xs) + Math.min(...xs)) / 2;
  view.cy = (Math.max(...ys) + Math.min(...ys)) / 2;
  view.z = Math.min(0.8 / bw, 0.8 / bh);   // la carte occupe ~80 % de l'aperçu, avec un peu de marge
  applyView();
}

video.addEventListener("loadedmetadata", () => {
  viewport.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
  applyView(false);
});
viewport.addEventListener("wheel", (e) => {
  e.preventDefault();
  view.z *= e.deltaY < 0 ? 1.1 : 1 / 1.1;
  applyView();
}, { passive: false });
viewport.addEventListener("click", (e) => {
  const r = viewport.getBoundingClientRect();
  view.cx = (e.clientX - r.left) / r.width / view.z - offset(view.cx, view.z);
  view.cy = (e.clientY - r.top) / r.height / view.z - offset(view.cy, view.z);
  applyView();
});
$("zoom").addEventListener("input", (e) => { view.z = +e.target.value; applyView(); });
$("zoom-card").addEventListener("click", async () => {
  const fd = new FormData();
  fd.append("image", await grabFrame(), "frame.jpg");
  const r = await (await fetch("/api/detect", { method: "POST", body: fd })).json();
  if (r.corners) { lastCorners = r.corners; frameOnCard(r.corners); }
  else setStatus("Carte non détectée pour le cadrage", "err");
});
$("zoom-reset").addEventListener("click", () => { view = { z: 1, cx: 0.5, cy: 0.5 }; applyView(); });

function grabFrame() {
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  return new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.92));
}

// ---------- Sons ----------
const audio = new (window.AudioContext || window.webkitAudioContext)();
function beep(freq, ms = 90) {
  const o = audio.createOscillator(), g = audio.createGain();
  o.frequency.value = freq; o.connect(g); g.connect(audio.destination);
  g.gain.setValueAtTime(0.15, audio.currentTime);
  g.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + ms / 1000);
  o.start(); o.stop(audio.currentTime + ms / 1000);
}

// ---------- Affichage ----------
function setStatus(text, cls = "") {
  const s = $("status");
  s.textContent = text;
  s.className = "status " + cls;
}

function showStats(st) {
  if (!st) return;
  $("st-today").textContent = st.today;
  $("st-cards").textContent = st.cards;
  $("st-tolist").textContent = st.to_list;
  $("st-value").textContent = st.value.toFixed(2) + " €";
}

function showCard(card, lang, confidence) {
  $("card-img").src = card.image || "";
  $("name-vo").textContent = card.name;
  $("name-vf").textContent = card.fr_name && card.fr_name !== card.name ? card.fr_name : "";
  $("lang").textContent = lang === "fr" ? "VF" : "VO";
  $("rarity").textContent = card.rarity || "";
  $("rarity").className = "badge " + (card.rarity || "");
  $("conf").textContent = confidence != null ? `confiance ${Math.round(confidence * 100)} %` : "";
  $("set-icon").src = card.set_icon || "";
  $("set-name").textContent = `${card.set_name} (${card.set_code.toUpperCase()}) — ${card.set_date || ""}`;
  $("number").textContent = card.collector_number;
  $("trend").innerHTML = card.trend != null
    ? `<span class="${card.price_alert ? "alert" : ""}">${card.trend.toFixed(2)} €${card.price_alert ? " ⚠ vaut plus que le prix de vente !" : ""}</span>`
    : "—";
  $("qty").textContent = card.quantity;
  const a = $("cm-url");
  a.href = card.cardmarket_url || "#";
  a.textContent = card.cardmarket_url || "URL introuvable";
}

function showAlternatives(alts) {
  $("alts").innerHTML = alts.map((c, i) => `
    <div class="alt" data-i="${i}" title="${c.set_name}">
      ${i < 9 ? `<span class="key">${i + 1}</span>` : ""}
      <img src="${c.image_small || c.image || ""}" loading="lazy" alt="">
      <div>${c.set_code.toUpperCase()} #${c.collector_number}</div>
      ${c.score != null ? `<div class="score">${c.score.toFixed(2)}</div>` : ""}
    </div>`).join("");
  $("alts").querySelectorAll(".alt").forEach((el) => el.addEventListener("click", () => pickAlternative(+el.dataset.i)));
}

function resultClass(cls) {
  $("result").className = "result " + cls;
}

async function refreshRecent() {
  const rows = await (await fetch("/api/recent?limit=20")).json();
  $("recent").innerHTML = rows.map((r) =>
    `<li><b>${r.lang === "fr" && r.fr_name ? r.fr_name : r.name}</b> — ${r.set_code.toUpperCase()} #${r.collector_number} ${r.lang.toUpperCase()} (x${r.quantity})</li>`).join("");
}

// ---------- Actions ----------
async function scan() {
  if (busy || !video.videoWidth) return;
  busy = true;
  setStatus("Analyse…", "busy");
  try {
    const blob = await grabFrame();
    const fd = new FormData();
    fd.append("image", blob, "frame.jpg");
    const r = await (await fetch("/api/scan", { method: "POST", body: fd })).json();
    $("warped").src = r.warped || "";
    $("ocr").textContent = (r.ocr || []).join("\n");
    if (r.corners) {
      lastCorners = r.corners;
      if (view.z === 1) frameOnCard(r.corners);   // premier cadrage automatique
    }
    if (!r.ok) {
      current = null;
      resultClass("err");
      setStatus(r.error || "Échec", "err");
      beep(180, 250);
      $("search").value = r.title || "";
      return;
    }
    current = { scan_id: r.scan_id, card: r.card, lang: r.lang, alternatives: r.alternatives, confidence: r.confidence };
    showCard(r.card, r.lang, r.confidence);
    showAlternatives(r.alternatives);
    $("alts-title").firstChild.textContent = "Autres impressions ";
    showStats(r.stats);
    const low = r.confidence < 0.5;
    resultClass(low ? "warn" : "ok");
    setStatus(low ? "Ajoutée — à vérifier (confiance faible)" : "Ajoutée ✔ — Espace pour la suivante", low ? "busy" : "ok");
    beep(low ? 520 : 880);
    refreshRecent();
  } catch (e) {
    setStatus("Erreur : " + e, "err");
  } finally {
    busy = false;
  }
}

async function undo() {
  if (!current || current.undone) return;
  const r = await fetch(`/api/scans/${current.scan_id}/undo`, { method: "POST" });
  if (r.ok) {
    current.undone = true;
    showStats((await r.json()).stats);
    resultClass("undone");
    setStatus("Scan annulé — repose la carte et appuie sur Espace", "busy");
    beep(300, 150);
    refreshRecent();
  }
}

async function reassign(cardId, lang) {
  if (!current || current.undone) return;
  const r = await fetch(`/api/scans/${current.scan_id}/reassign`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ card_id: cardId, lang }),
  });
  if (!r.ok) return;
  const data = await r.json();
  const previous = current.card;
  current.card = data.card;
  current.lang = lang;
  // L'ancienne proposition rejoint les alternatives.
  if (previous.card_id !== cardId) {
    current.alternatives = [previous, ...current.alternatives.filter((c) => c.card_id !== cardId)];
    showAlternatives(current.alternatives);
  }
  showCard(data.card, lang, null);
  showStats(data.stats);
  resultClass("ok");
  setStatus("Corrigé ✔", "ok");
  refreshRecent();
}

function pickAlternative(i) {
  const c = current && current.alternatives[i];
  if (c) {
    if (current.manual) addManual(c.card_id, current.lang);
    else reassign(c.card_id, current.lang);
  }
}

function toggleLang() {
  if (current && !current.undone && !current.manual) reassign(current.card.card_id, current.lang === "fr" ? "en" : "fr");
}

async function addManual(cardId, lang) {
  const r = await (await fetch("/api/manual", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ card_id: cardId, lang }),
  })).json();
  current = { scan_id: r.scan_id, card: r.card, lang, alternatives: current?.alternatives || [] };
  showCard(r.card, lang, null);
  showStats(r.stats);
  resultClass("ok");
  setStatus("Ajoutée manuellement ✔", "ok");
  refreshRecent();
}

// Recherche manuelle : affiche les impressions dans la zone des alternatives.
let searchTimer;
$("search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const q = e.target.value.trim();
    if (q.length < 3) return;
    const r = await (await fetch("/api/search?q=" + encodeURIComponent(q))).json();
    const lang = r.lang || "fr";
    // Si un scan est en cours, un clic corrige ce scan ; sinon il ajoute la carte.
    const manual = !current || current.undone || current.manual;
    current = manual ? { manual: true, lang, alternatives: r.results } : { ...current, alternatives: r.results };
    $("alts-title").firstChild.textContent = manual ? "Résultats — clic pour AJOUTER " : "Résultats — clic pour CORRIGER le scan ";
    showAlternatives(r.results);
  }, 250);
});

$("btn-next").addEventListener("click", scan);
$("btn-undo").addEventListener("click", undo);
$("lang").addEventListener("click", toggleLang);

document.addEventListener("keydown", (e) => {
  if (e.target.id === "search") {
    if (e.key === "Escape") { e.target.blur(); e.preventDefault(); }
    return;
  }
  if (e.code === "Space") { e.preventDefault(); scan(); }
  else if (e.key === "Escape" || e.key === "Backspace") { e.preventDefault(); undo(); }
  else if (e.key === "l" || e.key === "L") toggleLang();
  else if (e.key === "/") { e.preventDefault(); $("search").focus(); }
  else if (/^[1-9]$/.test(e.key)) pickAlternative(+e.key - 1);
});

listCameras().catch((e) => setStatus("Caméra indisponible : " + e, "err"));
fetch("/api/stats").then((r) => r.json()).then(showStats);
refreshRecent();

// Après un clic, on rend le focus à la page pour que Espace scanne toujours (et ne re-clique pas le bouton).
document.addEventListener("click", (e) => { const b = e.target.closest("button, select"); if (b && b.tagName === "BUTTON") b.blur(); });
$("zoom").addEventListener("change", (e) => e.target.blur());
