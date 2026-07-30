/* NOVICROM HUB — init Flatpickr sui <input class="js-datepicker"> (e js-daterange).
 *
 * Progressive enhancement, opt-in via classe. Senza JS resta l'<input type="date">
 * nativo; con JS diventa un date picker coerente (locale IT, formato d/m/Y mostrato,
 * valore inviato sempre ISO Y-m-d → compatibile coi filtri Django). Inizializza
 * anche gli input arrivati via HTMX e ignora quelli gia' inizializzati.
 */
(function () {
  "use strict";

  function initOne(el) {
    if (el.dataset.fpInit === "1" || typeof flatpickr === "undefined") return;
    el.dataset.fpInit = "1";
    var wasDate = el.type === "date";
    var range = el.classList.contains("js-daterange");
    try {
      // Evita il doppio picker (nativo + flatpickr): senza JS resta type=date.
      if (wasDate) el.type = "text";
      flatpickr(el, {
        locale: flatpickr.l10ns && flatpickr.l10ns.it ? "it" : "default",
        dateFormat: "Y-m-d", // valore inviato: ISO (compat filtri Django)
        altInput: true,
        altFormat: "d/m/Y", // mostrato all'utente
        allowInput: true,
        mode: range ? "range" : "single",
      });
    } catch (e) {
      el.dataset.fpInit = "";
      if (wasDate) el.type = "date"; // ripristina il nativo
    }
  }

  function initOneMulti(el) {
    if (el.dataset.fpInit === "1" || typeof flatpickr === "undefined") return;
    el.dataset.fpInit = "1";
    try {
      flatpickr(el, {
        locale: flatpickr.l10ns && flatpickr.l10ns.it ? "it" : "default",
        mode: "multiple",
        dateFormat: "d/m/Y", // stesso formato accettato dal parser lato server
        conjunction: "\n", // una data per riga, invariato per chi scrive a mano
        inline: true,
        allowInput: true,
        // Flatpickr non genera un evento nativo sui click: lo simuliamo per chi
        // ascolta "input"/"change" sul campo (es. l'anteprima ore del wizard).
        onChange: function () {
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));
        },
      });
    } catch (e) {
      el.dataset.fpInit = "";
    }
  }

  function initAll(root) {
    if (typeof flatpickr === "undefined") return;
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("input.js-datepicker, input.js-daterange").forEach(initOne);
    if (root && root.matches && root.matches("input.js-datepicker, input.js-daterange")) initOne(root);
    scope.querySelectorAll("input.js-datepicker-multi, textarea.js-datepicker-multi").forEach(initOneMulti);
    if (root && root.matches && root.matches("input.js-datepicker-multi, textarea.js-datepicker-multi")) initOneMulti(root);
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAll(document);
  });
  document.addEventListener("htmx:afterSwap", function (evt) {
    initAll((evt.detail && evt.detail.elt) || evt.target || document);
  });
})();
