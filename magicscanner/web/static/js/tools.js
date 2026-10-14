// Outils du stock : export CSV pour TCG Powertools, mise à jour des prix tendance Cardmarket.
import { api } from "./api.js";
import { $, plural } from "./dom.js";
import { setStatus } from "./view.js";

let onDone = () => {};

/** Bouton « Export Powertools » : actif tant que des cartes n'ont pas été exportées. */
export function updateToExport(stats) {
  const n = stats.to_export;
  $("btn-export").disabled = n === 0;
  $("btn-export").textContent = n ? `Export Powertools (${n})` : "Export Powertools";
}

async function exportCsv() {
  const { blob, lines, skipped } = await api.exportPowertools();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `powertools-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
  setStatus(`CSV Powertools : ${plural(lines, "ligne")} exportée${lines > 1 ? "s" : ""}`
    + (skipped ? ` — ${plural(skipped, "carte")} sans identifiant Cardmarket laissée${skipped > 1 ? "s" : ""} de côté` : ""),
    skipped ? "err" : "ok");
  onDone();
}

/** Retélécharge le guide des prix Cardmarket (quelques secondes). */
async function refreshPrices() {
  const button = $("btn-prices");
  button.disabled = true;
  setStatus("Téléchargement des prix Cardmarket…", "busy");
  try {
    const { created_at: created } = await api.refreshPrices();
    const day = created ? new Date(created).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "date inconnue";
    setStatus(`Prix tendance à jour (guide Cardmarket du ${day})`, "ok");
    onDone();
  } finally {
    button.disabled = false;
  }
}

const guarded = (fn, failure) => () => fn().catch((e) => setStatus(`${failure} : ${e.message}`, "err"));

export function initTools(doneCallback) {
  onDone = doneCallback;
  $("btn-export").addEventListener("click", guarded(exportCsv, "Export impossible"));
  $("btn-prices").addEventListener("click", guarded(refreshPrices, "Prix non mis à jour"));
}
