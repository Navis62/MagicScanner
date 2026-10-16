// Édition fixée : pour un paquet d'une seule édition, seules ses cartes sont envisagées (plus rapide, moins d'erreurs).
import { api } from "./api.js";
import { $, store } from "./dom.js";
import { setStatus } from "./view.js";

const KEY = "lockedSet";
const byLabel = new Map();   // « Nom — CODE » -> code
const names = new Map();     // code -> nom
let locked = "";

const label = (s) => `${s.name} — ${s.code.toUpperCase()}`;

/** Code de l'édition fixée, "" pour toutes. */
export const lockedSet = () => locked;

function lock(code) {
  locked = names.has(code) ? code : "";
  $("locked-set").value = locked ? label({ code: locked, name: names.get(locked) }) : "";
  $("set-field").classList.toggle("active", !!locked);
  store.set(KEY, locked);
}

/** Accepte une ligne de la liste, un code (« dmu ») ou un nom exact ; sinon, retour à toutes les éditions. */
function onChange() {
  const text = $("locked-set").value.trim();
  const lower = text.toLowerCase();
  const code = byLabel.get(text) ?? (names.has(lower) ? lower
    : [...names].find(([, name]) => name.toLowerCase() === lower)?.[0]);
  lock(code || "");
  setStatus(locked ? `Édition fixée : ${names.get(locked)} — les cartes d'une autre édition sont signalées`
    : text ? `Édition « ${text} » inconnue — toutes les éditions` : "Toutes les éditions", locked || !text ? "ok" : "err");
}

export async function initEdition() {
  const sets = await api.sets();
  $("sets-list").innerHTML = "";
  for (const s of sets) {
    byLabel.set(label(s), s.code);
    names.set(s.code, s.name);
    $("sets-list").append(new Option(label(s)));
  }
  lock(store.get(KEY, ""));
  $("locked-set").addEventListener("change", onChange);
  $("locked-set").addEventListener("focus", (e) => e.target.select());
  $("locked-set-clear").addEventListener("click", () => { lock(""); setStatus("Toutes les éditions", "ok"); });
}
