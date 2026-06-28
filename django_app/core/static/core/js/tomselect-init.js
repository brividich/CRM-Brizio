/* NOVICROM HUB — init Tom Select sui <select class="js-searchable">.
 *
 * Progressive enhancement, opt-in via classe: il <select> nativo continua a
 * funzionare se JS e' disattivo o la libreria non carica. Inizializza anche i
 * select arrivati via HTMX (htmx:afterSwap) e ignora quelli gia' inizializzati.
 */
(function () {
  "use strict";

  function initOne(el) {
    if (el.dataset.tsInit === "1") return;
    el.dataset.tsInit = "1";
    var placeholder =
      el.getAttribute("data-placeholder") ||
      (el.querySelector("option[value='']") || {}).textContent ||
      "Cerca…";
    try {
      // eslint-disable-next-line no-undef, no-new
      new TomSelect(el, {
        create: false, // niente opzioni inventate: solo quelle esistenti
        allowEmptyOption: true,
        maxOptions: null, // niente cap: liste lunghe (dipendenti, asset...) intere
        placeholder: placeholder,
        // Cerca su testo e value; ordina per pertinenza poi alfabetico.
        searchField: ["text"],
      });
    } catch (e) {
      // Fail-safe: in caso di errore resta il select nativo.
      el.dataset.tsInit = "";
    }
  }

  function initAll(root) {
    if (typeof TomSelect === "undefined") return;
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("select.js-searchable").forEach(initOne);
    // Se root e' esso stesso un select target di uno swap.
    if (root && root.matches && root.matches("select.js-searchable")) initOne(root);
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAll(document);
  });
  // I select caricati via HTMX (gli eventi bubblano fino a document).
  document.addEventListener("htmx:afterSwap", function (evt) {
    initAll((evt.detail && evt.detail.elt) || evt.target || document);
  });
})();
