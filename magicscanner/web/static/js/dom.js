// Petits utilitaires DOM, texte et stockage local.
export const $ = (id) => document.getElementById(id);

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

/** « 3 cartes », « 1 carte ». */
export const plural = (n, word) => `${n} ${word}${n > 1 ? "s" : ""}`;

// localStorage peut être indisponible (navigation privée…) : préférences de confort uniquement.
export const store = {
  get(key, fallback = null) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
  },
};
