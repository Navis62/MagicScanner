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
  $("btn-publish-one").disabled = !idle || toList.cards === 0;
  $("btn-publish-stop").hidden = idle;
  $("btn-publish-one").hidden = !idle;
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
  const mode = job.dry_run ? " (essai à blanc : rien n'est publié)" : "";
  if (!done) {
    $("report-title").textContent = `Publication en cours : ${job.done} / ${job.total}${mode}`;
    $("report-body").textContent = job.current ? `Dernière carte : ${job.current}` : "Chrome ouvre les pages Cardmarket…";
    return;
  }
  $("report-title").textContent = (job.dry_run ? "Essai terminé : " : "Publication terminée : ")
    + `${plural(job.done, "exemplaire")} ${job.dry_run ? "préparé" : "mis"}${job.dry_run || job.done < 2 ? "" : "s"} en vente`
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
    setStatus(`Publication Cardmarket : ${job.done} / ${job.total}`, "busy");
    setTimeout(() => poll().catch(() => {}), POLL_MS);
  } else if (job.state === "done") {
    setStatus(job.stopped ? "Publication interrompue — voir le rapport" : "Publication terminée ✔", job.stopped ? "err" : "ok");
    onFinished();
  }
}

async function start({ limit = null, dry_run = false } = {}) {
  const what = limit ? "1 carte" : plural(toList.cards, "carte");
  const total = limit ? "" : ` (${plural(toList.lines, "référence")}, ${euros(toList.value)} au total)`;
  const message = dry_run
    ? `Essai à blanc de ${what} : les formulaires sont remplis, rien n'est publié.`
    : `Mettre en vente ${what}${total} sur Cardmarket ?\n\n`
      + "Chrome va s'ouvrir et publier pour de vrai sur ton compte.\n"
      + "Les exemplaires déjà en vente ne sont pas republiés.";
  if (!confirm(message)) return;
  await api.publish({ limit, dry_run });
  running = true;
  renderButtons();
  poll();
}

const safe = (fn) => (...args) => fn(...args).catch((e) => setStatus("Publication impossible : " + e.message, "err"));

export function initPublish(finishedCallback) {
  onFinished = finishedCallback;
  $("btn-publish").addEventListener("click", safe(() => start()));
  $("btn-publish-one").addEventListener("click", safe(() => start({ limit: 1 })));
  $("btn-publish-stop").addEventListener("click", safe(async () => {
    await api.publishStop();
    setStatus("Arrêt demandé : la carte en cours se termine…", "busy");
  }));
  $("report-close").addEventListener("click", () => { $("publish-report").hidden = true; });
  // Une publication lancée avant un rechargement de la page continue de tourner : on la reprend.
  api.publishStatus().then((job) => { if (job.state === "running") poll(); }).catch(() => {});
}
