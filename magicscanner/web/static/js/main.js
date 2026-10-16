// MagicScanner — orchestration : état du scan courant, actions, raccourcis clavier.
import { api } from "./api.js";
import { grabFrame, initCamera, isReady } from "./camera.js";
import { $ } from "./dom.js";
import { initEdition, lockedSet } from "./edition.js";
import { frameOnCard, initPreview, isDefaultZoom } from "./preview.js";
import { initPublish, updateToList } from "./publish.js";
import { sound } from "./sound.js";
import { initTools, updateToExport } from "./tools.js";
import * as view from "./view.js";

// Carte affichée. mode : "scan" (un clic sur une alternative corrige ce scan) ou "add" (un clic ajoute la carte).
let current = null;   // { mode, scanId, card, lang, alternatives, undone }
let busy = false;

const editable = () => current && current.mode === "scan" && !current.undone;

// Toute action en échec s'affiche dans la barre d'état.
const safe = (fn) => (...args) => fn(...args).catch((e) => view.setStatus("Erreur : " + e.message, "err"));

async function refresh(stats) {
  stats ??= await api.stats();
  view.showStats(stats);
  updateToList(stats);
  updateToExport(stats);
  view.showRecent(await api.recent());
}

function showAlternatives() {
  const title = current.mode === "add" ? "Résultats — clic pour AJOUTER"
    : current.searched ? "Résultats — clic pour CORRIGER le scan" : "Autres impressions";
  view.showAlternatives(current.alternatives, title, pickAlternative);
}

const scan = safe(async () => {
  if (busy || !isReady()) return;
  busy = true;
  view.setStatus("Analyse…", "busy");
  try {
    const r = await api.scan(await grabFrame(), foilOn(), price(), lockedSet());
    view.showScanDebug(r.warped, r.ocr, r.list_symbol);
    if (r.corners && isDefaultZoom()) frameOnCard(r.corners);   // premier cadrage automatique
    if (!r.ok) {
      current = null;
      view.setResultState("err");
      view.setStatus(r.error || "Échec", "err");
      sound.error();
      $("search").value = r.title || "";
      return;
    }
    current = { mode: "scan", scanId: r.scan_id, card: r.card, lang: r.lang, alternatives: r.alternatives };
    view.showCard(r.card, r.lang, r.confidence, r.needs_review);
    showAlternatives();
    const low = r.needs_review;
    view.setResultState(low ? "warn" : "ok");
    view.setStatus(low ? `Ajoutée — à vérifier (${r.review_reason})` : "Ajoutée ✔ — Espace pour la suivante", low ? "busy" : "ok");
    r.card.price_alert ? sound.alarm() : low ? sound.check() : sound.ok();
    refresh(r.stats);
  } finally {
    busy = false;
  }
});

// Chaque appel annule le scan actif le plus récent : on peut remonter plusieurs fois en arrière.
const undo = safe(async () => {
  const r = await api.undo();
  current = { mode: "scan", scanId: null, card: r.card, lang: r.lang, alternatives: [], undone: true };
  view.showCard(r.card, r.lang);
  view.setResultState("undone");
  view.setStatus(`Annulé : ${r.card.name} — encore pour revenir en arrière, Espace pour scanner`, "busy");
  sound.undo();
  refresh(r.stats);
});

const reassign = safe(async (cardId, lang, foil = null, newPrice = null) => {
  if (!editable()) return;
  const r = await api.reassign(current.scanId, cardId, lang, foil, newPrice);
  if (current.card.card_id !== cardId) {
    // L'ancienne proposition rejoint les alternatives.
    current.alternatives = [current.card, ...current.alternatives.filter((c) => c.card_id !== cardId)];
    showAlternatives();
  }
  Object.assign(current, { card: r.card, lang });
  view.showCard(r.card, lang);
  view.setResultState("ok");
  view.setStatus("Corrigé ✔", "ok");
  if (r.card.price_alert) sound.alarm();
  refresh(r.stats);
});

// Un exemplaire de plus de la dernière carte ajoutée, à l'identique (édition, langue, finition, prix), sans scanner.
const addSame = safe(async () => {
  if (busy || !editable()) return;
  busy = true;
  try {
    const { card, lang } = current;
    const r = await api.addManual(card.card_id, lang, !!card.foil, card.price);
    current = { ...current, scanId: r.scan_id, card: r.card, searched: false };
    view.showCard(r.card, lang);
    view.setResultState("ok");
    view.setStatus(`Encore une ✔ — ${r.card.quantity} en stock`, "ok");
    sound.ok();
    refresh(r.stats);
  } finally {
    busy = false;
  }
});

const addManual = safe(async (cardId, lang) => {
  const r = await api.addManual(cardId, lang, foilOn(), price());
  current = { mode: "scan", scanId: r.scan_id, card: r.card, lang, alternatives: current?.alternatives || [] };
  view.showCard(r.card, lang);
  view.setResultState("ok");
  view.setStatus("Ajoutée manuellement ✔", "ok");
  if (r.card.price_alert) sound.alarm();
  refresh(r.stats);
});

function pickAlternative(i) {
  const card = current?.alternatives[i];
  if (!card) return;
  if (current.mode === "add") addManual(card.card_id, current.lang);
  else reassign(card.card_id, current.lang);
}

const foilOn = () => $("foil").checked;

/** La case s'applique aux prochains scans ; si une carte vient d'être scannée, elle bascule aussi. */
function setFoil(on) {
  $("foil").checked = on;
  if (editable() && !!current.card.foil !== on) reassign(current.card.card_id, current.lang, on);
}

/** Prix saisi (0,18 € par défaut) ; une saisie invalide revient au dernier prix valable. */
let lastPrice = 0.18;
function price() {
  const v = Math.round(parseFloat($("price").value) * 100) / 100;
  if (v >= 0.02) lastPrice = v;
  $("price").value = lastPrice.toFixed(2);
  return lastPrice;
}

function onPriceChange() {
  const p = price();
  if (editable() && current.card.price !== p) reassign(current.card.card_id, current.lang, null, p);
}

function toggleLang() {
  if (editable()) reassign(current.card.card_id, current.lang === "fr" ? "en" : "fr");
}

// Recherche manuelle : les résultats remplacent les alternatives.
let searchTimer;
const search = safe(async (q) => {
  if (q.length < 3) return;
  const r = await api.search(q, lockedSet());
  if (editable()) current = { ...current, alternatives: r.results, searched: true };
  else current = { mode: "add", lang: r.lang || "fr", alternatives: r.results };
  showAlternatives();
});

function onKey(e) {
  if (document.querySelector("dialog[open]")) return;   // une boîte de dialogue gère ses propres touches
  if (["search", "price", "locked-set"].includes(e.target.id)) {
    if (e.key === "Escape" || (e.key === "Enter" && e.target.id !== "search")) { e.preventDefault(); e.target.blur(); }
    return;
  }
  if (e.code === "Space") { e.preventDefault(); scan(); }
  else if (e.key === "Escape" || e.key === "Backspace") { e.preventDefault(); undo(); }
  else if (e.key === "+") { e.preventDefault(); addSame(); }
  else if (e.key.toLowerCase() === "l") toggleLang();
  else if (e.key.toLowerCase() === "f") setFoil(!foilOn());
  else if (e.key === "/") { e.preventDefault(); $("search").focus(); }
  else if (e.key.toLowerCase() === "e") { e.preventDefault(); $("locked-set").focus(); }
  else if (/^[1-9]$/.test(e.key)) pickAlternative(+e.key - 1);
}

function init() {
  $("btn-next").addEventListener("click", scan);
  $("btn-undo").addEventListener("click", undo);
  $("btn-same").addEventListener("click", addSame);
  $("lang").addEventListener("click", toggleLang);
  $("price").addEventListener("change", onPriceChange);
  $("foil").addEventListener("change", (e) => { setFoil(e.target.checked); e.target.blur(); });
  $("search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => search(e.target.value.trim()), 250);
  });
  document.addEventListener("keydown", onKey);
  // Après un clic, le focus revient à la page : Espace scanne au lieu de re-cliquer le bouton.
  document.addEventListener("click", (e) => e.target.closest("button")?.blur());
  initPreview();
  initPublish(() => refresh());
  initTools(() => refresh());
  initEdition().catch((e) => view.setStatus("Éditions indisponibles : " + e.message, "err"));
  initCamera().catch((e) => view.setStatus("Caméra indisponible : " + e.message, "err"));
  api.stats().then((st) => { lastPrice = st.default_price; price(); }).catch(() => {});
  refresh();
}

init();
