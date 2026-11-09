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
      // eslint-disable-next-line no-undef
      var ts = new TomSelect(el, {
        create: false, // niente opzioni inventate: solo quelle esistenti
        allowEmptyOption: true,
        maxOptions: null, // niente cap: liste lunghe (dipendenti, asset...) intere
        placeholder: placeholder,
        // La lista si appende al body: dentro una card con overflow nascosto
        // (hr-card, fm-section, modali) altrimenti resta tagliata e invisibile.
        dropdownParent: "body",
        // Cerca su testo e value; ordina per pertinenza poi alfabetico.
        searchField: ["text"],
      });
      // Con lo zoom CSS di theme.css (schermi 4K: :root{zoom:1.5}) le
      // coordinate di getBoundingClientRect e quelle assolute del body non
      // coincidono e la lista finiva mezza pagina più in basso. Si misura la
      // mappa reale con due sonde invece di fidarsi di scrollY.
      ts.positionDropdown = function () {
        var r = this.control.getBoundingClientRect();
        var a = document.createElement("div"), b = document.createElement("div");
        a.style.cssText = b.style.cssText = "position:absolute;width:0;height:0;left:0;top:0;pointer-events:none;";
        b.style.top = "1000px";
        document.body.appendChild(a); document.body.appendChild(b);
        var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
        document.body.removeChild(a); document.body.removeChild(b);
        var k = (rb.top - ra.top) / 1000 || 1;
        this.dropdown.style.width = (r.width / k) + "px";
        this.dropdown.style.top = ((r.bottom - ra.top) / k) + "px";
        this.dropdown.style.left = ((r.left - ra.left) / k) + "px";
      };
    } catch (e) {
      // Fail-safe: in caso di errore resta il select nativo.
      el.dataset.tsInit = "";
    }
  }

  // Oltre all'opt-in (.js-searchable), ogni tendina lunga diventa ricercabile da
  // sola: con più di AUTO_MIN opzioni cercare a occhio non funziona più
  // (corsi, persone, mansioni, asset). Si esclude con data-no-search, oppure
  // quando è una lista a più righe (size) — lì la ricerca la fa già la pagina.
  var AUTO_MIN = 10;
  function autoCandidata(el) {
    if (el.hasAttribute("data-no-search") || el.hasAttribute("data-picker")) return false;
    if (el.size && el.size > 1) return false;
    if (el.closest("[data-no-search]")) return false;
    return el.options.length > AUTO_MIN || el.multiple;
  }

  function initAll(root) {
    if (typeof TomSelect === "undefined") return;
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("select.js-searchable").forEach(initOne);
    scope.querySelectorAll("select:not(.js-searchable)").forEach(function (el) {
      if (autoCandidata(el)) initOne(el);
    });
    // Se root e' esso stesso un select target di uno swap.
    if (root && root.matches && root.matches("select.js-searchable")) initOne(root);
  }

  document.addEventListener("DOMContentLoaded", function () {
    initAll(document);
  });
  // I select caricati via HTMX (gli eventi bubblano fino a document).
  document.addEventListener("htmx:afterSwap", function (evt) {
    var root = (evt.detail && evt.detail.elt) || evt.target || document;
    // Con hx-swap="outerHTML" elt e' il nodo sostituito, ormai fuori dal DOM: si
    // riparte dal documento (initOne salta i select gia' inizializzati).
    initAll(root.isConnected === false ? document : root);
  });
})();
