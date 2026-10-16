// Boîte de confirmation à l'image du site (remplace window.confirm).
import { esc } from "./dom.js";

/** Affiche `message` (paragraphes séparés par une ligne vide) ; résout true si confirmé. `danger` : action sensible. */
export function confirmDialog({ title, message, ok = "Confirmer", cancel = "Annuler", danger = false }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "modal";
    dlg.innerHTML = `<h2 class="modal-title">${esc(title)}</h2>`
      + message.split("\n\n").map((p) => `<p>${esc(p).replace(/\n/g, "<br>")}</p>`).join("")
      + `<div class="modal-actions"><button type="button" data-v="">${esc(cancel)}</button>`
      + `<button type="button" data-v="1" class="${danger ? "danger" : "primary"}">${esc(ok)}</button></div>`;
    dlg.addEventListener("click", (e) => {
      const v = e.target.closest("button")?.dataset.v;
      if (v !== undefined) dlg.close(v);
      else if (e.target === dlg) dlg.close("");   // clic sur le fond
    });
    dlg.addEventListener("close", () => { resolve(dlg.returnValue === "1"); dlg.remove(); });
    document.body.append(dlg);
    dlg.showModal();
    dlg.querySelector("[data-v='1']").focus();
  });
}
