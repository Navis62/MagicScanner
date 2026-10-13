// MagicScanner — orchestration : état du scan courant, actions, raccourcis clavier.
import { api } from "./api.js";
import { grabFrame, initCamera, isReady } from "./camera.js";
import { $ } from "./dom.js";
import { frameOnCard, initPreview, isDefaultZoom } from "./preview.js";
import { initPublish, updateToList } from "./publish.js";
import { sound } from "./sound.js";
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
    const r = await api.scan(await grabFrame());
    view.showScanDebug(r.warped, r.ocr);
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
    view.setStatus(low ? "Ajoutée — à vérifier (confiance faible)" : "Ajoutée ✔ — Espace pour la suivante", low ? "busy" : "ok");
    low ? sound.check() : sound.ok();
    refresh(r.stats);
  } finally {
    busy = false;
  }
});

const undo = safe(async () => {
  if (!editable()) return;
  const r = await api.undo(current.scanId);
  current.undone = true;
  view.setResultState("undone");
  view.setStatus("Scan annulé — repose la carte et appuie sur Espace", "busy");
  sound.undo();
  refresh(r.stats);
});

const reassign = safe(async (cardId, lang) => {
  if (!editable()) return;
  const r = await api.reassign(current.scanId, cardId, lang);
  if (current.card.card_id !== cardId) {
    // L'ancienne proposition rejoint les alternatives.
    current.alternatives = [current.card, ...current.alternatives.filter((c) => c.card_id !== cardId)];
    showAlternatives();
  }
  Object.assign(current, { card: r.card, lang });
  view.showCard(r.card, lang);
  view.setResultState("ok");
  view.setStatus("Corrigé ✔", "ok");
  refresh(r.stats);
});

const addManual = safe(async (cardId, lang) => {
  const r = await api.addManual(cardId, lang);
  current = { mode: "scan", scanId: r.scan_id, card: r.card, lang, alternatives: current?.alternatives || [] };
  view.showCard(r.card, lang);
  view.setResultState("ok");
  view.setStatus("Ajoutée manuellement ✔", "ok");
  refresh(r.stats);
});

function pickAlternative(i) {
  const card = current?.alternatives[i];
  if (!card) return;
  if (current.mode === "add") addManual(card.card_id, current.lang);
  else reassign(card.card_id, current.lang);
}

function toggleLang() {
  if (editable()) reassign(current.card.card_id, current.lang === "fr" ? "en" : "fr");
}

// Recherche manuelle : les résultats remplacent les alternatives.
let searchTimer;
const search = safe(async (q) => {
  if (q.length < 3) return;
  const r = await api.search(q);
  if (editable()) current = { ...current, alternatives: r.results, searched: true };
  else current = { mode: "add", lang: r.lang || "fr", alternatives: r.results };
  showAlternatives();
});

function onKey(e) {
  if (e.target.id === "search") {
    if (e.key === "Escape") { e.preventDefault(); e.target.blur(); }
    return;
  }
  if (e.code === "Space") { e.preventDefault(); scan(); }
  else if (e.key === "Escape" || e.key === "Backspace") { e.preventDefault(); undo(); }
  else if (e.key.toLowerCase() === "l") toggleLang();
  else if (e.key === "/") { e.preventDefault(); $("search").focus(); }
  else if (/^[1-9]$/.test(e.key)) pickAlternative(+e.key - 1);
}

function init() {
  $("btn-next").addEventListener("click", scan);
  $("btn-undo").addEventListener("click", undo);
  $("lang").addEventListener("click", toggleLang);
  $("search").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => search(e.target.value.trim()), 250);
  });
  document.addEventListener("keydown", onKey);
  // Après un clic, le focus revient à la page : Espace scanne au lieu de re-cliquer le bouton.
  document.addEventListener("click", (e) => e.target.closest("button")?.blur());
  initPreview();
  initPublish(() => refresh());
  initCamera().catch((e) => view.setStatus("Caméra indisponible : " + e.message, "err"));
  refresh();
}

init();
