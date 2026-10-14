// Rendu de l'interface (aucune logique métier ici).
import { $, esc } from "./dom.js";

export function setStatus(text, kind = "") {
  const el = $("status");
  el.textContent = text;
  el.className = "status " + kind;
}

/** État visuel du résultat : ok | warn | err | undone */
export function setResultState(kind) {
  $("result").className = "result " + kind;
}

export function showStats(st) {
  if (!st) return;
  $("st-today").textContent = st.today;
  $("st-cards").textContent = st.cards;
  $("st-tolist").textContent = st.to_list;
  $("st-value").textContent = st.value.toFixed(2).replace(".", ",") + " €";
  $("stat-tolist").classList.toggle("hot", st.to_list > 0);
}

export function showScanDebug(warped, ocrLines, listSymbol = null) {
  $("warped").src = warped || "";
  $("ocr").textContent = (ocrLines || []).join("\n");
  // Étincelle de Planeswalker (en bas à gauche : The List ou Mystery Booster) : on montre ce que la caméra a vu.
  const chip = $("list-chip");
  chip.hidden = listSymbol == null;
  if (listSymbol != null) {
    const seen = listSymbol >= 0.7, unsure = listSymbol > 0.45 && !seen;
    chip.textContent = seen ? "étincelle vue (List / Mystery Booster)" : unsure ? "étincelle douteuse" : "pas d'étincelle";
    chip.className = "chip list " + (seen ? "yes" : unsure ? "maybe" : "no");
  }
}

export function showCard(card, lang, confidence = null, needsReview = false) {
  const result = $("result");
  result.dataset.empty = "false";

  // Petite animation d'apparition à chaque nouvelle carte.
  const frame = $("card-img").parentElement;
  frame.classList.remove("pop");
  void frame.offsetWidth;
  frame.classList.add("pop");

  $("card-img").src = card.image || "";
  $("name-vo").textContent = card.name;
  $("name-vf").textContent = card.fr_name && card.fr_name !== card.name ? card.fr_name : "";
  $("lang").textContent = lang === "fr" ? "VF" : "VO";
  $("rarity").textContent = card.rarity || "";
  $("rarity").className = "badge " + (card.rarity || "");
  $("foil-badge").hidden = !card.foil;
  $("conf").textContent = confidence != null ? `confiance ${Math.round(confidence * 100)} %` : "";
  $("conf").className = "badge conf " + (confidence == null ? "" : needsReview ? "mid" : "high");
  $("set-icon").src = card.set_icon || "";
  $("set-name").textContent = `${card.set_name} (${card.set_code.toUpperCase()}) — ${card.set_date || ""}`;
  $("number").textContent = card.collector_number;
  $("list-badge").hidden = !card.is_list;
  $("list-badge").textContent = card.list_label || "";
  $("cm-exp").textContent = card.cm_expansion || "—";
  $("trend-label").textContent = card.foil ? "Tendance foil" : "Prix tendance";
  const trend = $("trend");
  trend.textContent = card.trend != null
    ? `${card.trend.toFixed(2).replace(".", ",")} €${card.price_alert ? "  ⚠ bien plus que le prix de vente !" : ""}`
    : "—";
  trend.className = card.price_alert ? "alert" : "";
  $("price-val").textContent = card.price != null ? card.price.toFixed(2).replace(".", ",") + " €" : "—";
  const toList = card.quantity - (card.listed || 0);
  $("qty").textContent = card.listed
    ? `${card.quantity} (dont ${card.listed} déjà en vente sur Cardmarket — ${Math.max(toList, 0)} à publier)`
    : `${card.quantity}`;
  const link = $("cm-url");
  link.href = card.cardmarket_url || "#";
  link.textContent = card.cardmarket_url || "URL introuvable";
}

export function showAlternatives(cards, title, onPick) {
  $("alts-title").firstChild.textContent = title + " ";
  $("alts").innerHTML = cards.map((c, i) => `
    <div class="alt" data-i="${i}" title="${esc(c.set_name)}">
      ${i < 9 ? `<span class="key">${i + 1}</span>` : ""}
      <img src="${esc(c.image_small || c.image)}" loading="lazy" alt="">
      <div class="label">
        ${c.set_icon ? `<img src="${esc(c.set_icon)}" alt="">` : ""}${esc(c.set_code.toUpperCase())} #${esc(c.collector_number)}
      </div>
      ${c.score != null ? `<div class="score">${c.score.toFixed(2)}</div>` : ""}
    </div>`).join("");
  $("alts").querySelectorAll(".alt").forEach((el) => el.addEventListener("click", () => onPick(+el.dataset.i)));
}

export function showRecent(rows) {
  $("recent").innerHTML = rows.map((r) => `
    <li>
      <span class="chip ${esc(r.lang)}">${esc(r.lang.toUpperCase())}</span>
      <b>${esc(r.lang === "fr" && r.fr_name ? r.fr_name : r.name)}</b>${r.foil ? ' <span class="chip foil">FOIL</span>' : ""}
      <span class="ref">${esc(r.set_code.toUpperCase())} #${esc(r.collector_number)}</span>
      <span class="ref">${r.price.toFixed(2).replace(".", ",")} €</span>
      <span class="qty">×${r.quantity}</span>
    </li>`).join("");
}
