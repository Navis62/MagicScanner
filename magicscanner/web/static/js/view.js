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
  $("st-value").textContent = st.value.toFixed(2) + " €";
}

export function showScanDebug(warped, ocrLines) {
  $("warped").src = warped || "";
  $("ocr").textContent = (ocrLines || []).join("\n");
}

export function showCard(card, lang, confidence = null) {
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
  const trend = $("trend");
  trend.textContent = card.trend != null
    ? `${card.trend.toFixed(2)} €${card.price_alert ? " ⚠ vaut plus que le prix de vente !" : ""}`
    : "—";
  trend.className = card.price_alert ? "alert" : "";
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
      <div>${esc(c.set_code.toUpperCase())} #${esc(c.collector_number)}</div>
      ${c.score != null ? `<div class="score">${c.score.toFixed(2)}</div>` : ""}
    </div>`).join("");
  $("alts").querySelectorAll(".alt").forEach((el) => el.addEventListener("click", () => onPick(+el.dataset.i)));
}

export function showRecent(rows) {
  $("recent").innerHTML = rows.map((r) => `
    <li><b>${esc(r.lang === "fr" && r.fr_name ? r.fr_name : r.name)}</b>
      — ${esc(r.set_code.toUpperCase())} #${esc(r.collector_number)} ${esc(r.lang.toUpperCase())} (x${r.quantity})</li>`).join("");
}
