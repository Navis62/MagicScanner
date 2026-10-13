// Publication sur Cardmarket : bouton, progression, rapport de fin.
import { api } from "./api.js";
import { $, esc } from "./dom.js";
import { setStatus } from "./view.js";

const POLL_MS = 1500;
let toList = { cards: 0, lines: 0, value: 0 };
let running = false;
let onFinished = () => {};

const plural = (n, word) => `${n} ${word}${n > 1 ? "s" : ""}`;
const euros = (v) => v.toFixed(2).replace(".", ",") + " €";

function renderButtons() {
  const idle = !running;
  $("btn-publish").disabled = !idle || toList.cards === 0;
  $("btn-publish-stop").hidden = idle;
  if (idle) {
    $("btn-publish").textContent = toList.cards
      ? `Publier ${plural(toList.cards, "carte")} sur Cardmarket`
      : "Rien à publier";
  }
}

/** À appeler à chaque mise à jour des statistiques (nombre de cartes pas encore en vente). */
export function updateToList(stats) {
  toList = { cards: stats.to_list, lines: stats.lines_to_list, value: stats.to_list_value };
  renderButtons();
}

function showReport(job) {
  const done = job.state === "done";
  $("publish-report").hidden = false;
  $("publish-report").className = "report " + (done ? (job.stopped || job.errors.length ? "warn" : "ok") : "busy");
  if (!done) {
    const pct = job.total ? Math.round((100 * job.done) / job.total) : 0;
    $("report-title").textContent = `Publication en cours : ${job.done} / ${job.total} exemplaires (${pct} %)`;
    $("report-body").innerHTML = `<div class="bar"><i style="width:${pct}%"></i></div>`
      + `<p>${job.current ? `Carte ${job.line} / ${job.lines} : <b>${esc(job.current)}</b>` : "Chrome ouvre les pages Cardmarket…"}`
      + (job.errors.length ? ` — <span class="stopped">${plural(job.errors.length, "erreur")}</span>` : "") + "</p>";
    return;
  }
  $("report-title").textContent = `Publication terminée : ${plural(job.done, "exemplaire")} mis en vente`
    + (job.errors.length ? `, ${plural(job.errors.length, "erreur")}` : "");
  const lines = [];
  if (job.stopped) lines.push(`<p class="stopped">⚠ ${esc(job.stopped)}</p>`);
  if (job.errors.length) {
    lines.push("<ul>" + job.errors.map((e) => `<li><b>${esc(e.label)}</b> — ${esc(e.message)}</li>`).join("") + "</ul>");
    lines.push("<p>Les cartes en erreur restent « à publier » : elles seront retentées au prochain clic.</p>");
  }
  $("report-body").innerHTML = lines.join("");
}

async function poll() {
  const job = await api.publishStatus();
  running = job.state === "running";
  showReport(job);
  renderButtons();
  if (running) {
    setStatus(`Publication Cardmarket : ${job.done} / ${job.total}${job.current ? " — " + job.current : ""}`, "busy");
    setTimeout(() => poll().catch(() => {}), POLL_MS);
  } else if (job.state === "done") {
    setStatus(job.stopped ? "Publication interrompue — voir le rapport" : "Publication terminée ✔", job.stopped ? "err" : "ok");
    onFinished();
  }
}

async function start() {
  const message = `Mettre en vente ${plural(toList.cards, "carte")} `
    + `(${plural(toList.lines, "référence")}, ${euros(toList.value)} au total) sur Cardmarket ?\n\n`
    + "Chrome va s'ouvrir et publier pour de vrai sur ton compte.\n"
    + "Les exemplaires déjà en vente ne sont pas republiés.";
  if (!confirm(message)) return;
  await api.publish();
  running = true;
  renderButtons();
  poll();
}

const safe = (fn) => (...args) => fn(...args).catch((e) => setStatus("Publication impossible : " + e.message, "err"));

export function initPublish(finishedCallback) {
  onFinished = finishedCallback;
  $("btn-publish").addEventListener("click", safe(() => start()));
  $("btn-publish-stop").addEventListener("click", safe(async () => {
    await api.publishStop();
    setStatus("Arrêt demandé : la carte en cours se termine…", "busy");
  }));
  $("report-close").addEventListener("click", () => { $("publish-report").hidden = true; });
  // Une publication lancée avant un rechargement de la page continue de tourner : on la reprend.
  api.publishStatus().then((job) => { if (job.state === "running") poll(); }).catch(() => {});
}
