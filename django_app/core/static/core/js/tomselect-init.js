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
        // Le voci che la pagina nasconde (option.hidden, es. il ruolo stesso in «Riporta a»)
        // non si mostrano nella ricerca: sono anche disattivate, quindi non si scelgono.
        render: {
          option: function (data, escape) {
            var nascosta = data.$option && data.$option.hidden;
            return "<div" + (nascosta ? ' style="display:none"' : "") + ">" + escape(data.text) + "</div>";
          },
        },
      });
      collega(el, ts);
      // Scelta singola: mentre si digita il valore già scelto (es. «Io stesso»)
      // resterebbe accanto al testo cercato e si sovrapporrebbe: si nasconde
      // finché c'è testo nella ricerca (CSS .ts-digita in components.css).
      if (!el.multiple) {
        var digita = function (testo) { ts.wrapper.classList.toggle("ts-digita", !!testo); };
        ts.on("type", digita);
        ts.on("dropdown_close", function () { digita(""); });
        ts.on("change", function () { digita(""); });
      }
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

  // Il <select> nativo resta la fonte del valore inviato col modulo: quando una pagina lo
  // cambia da script (sel.value = …, selectedIndex, nuove opzioni, disabled, hidden) la
  // tendina ricercabile si riallinea. Senza, la finestra «Modifica» mostrava il valore di
  // prima o il segnaposto mentre il modulo ne inviava un altro (24/11/2026).
  var NATIVO = {
    value: Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value"),
    selectedIndex: Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "selectedIndex"),
  };

  function collega(el, ts) {
    var inSync = false;
    function nascoste() {
      Array.prototype.forEach.call(el.options, function (o) {
        if (o.hidden && !o.disabled) { o.disabled = true; o.dataset.tsNascosta = "1"; }
        else if (!o.hidden && o.dataset.tsNascosta === "1") { o.disabled = false; delete o.dataset.tsNascosta; }
      });
    }
    function riallinea() {
      if (inSync) return;
      inSync = true;
      try {
        nascoste();
        if (typeof ts.sync === "function") ts.sync();
        else ts.setValue(NATIVO.value.get.call(el), true);
        if (el.disabled) ts.disable(); else ts.enable();
        var nascosto = el.hidden || el.style.display === "none";
        ts.wrapper.style.display = nascosto ? "none" : "";
      } catch (e) { /* resta il select nativo come fonte */ }
      osservatore.takeRecords();
      inSync = false;
    }
    ["value", "selectedIndex"].forEach(function (nome) {
      Object.defineProperty(el, nome, {
        configurable: true,
        get: function () { return NATIVO[nome].get.call(el); },
        set: function (v) { NATIVO[nome].set.call(el, v); riallinea(); },
      });
    });
    var attesa = null;
    var osservatore = new MutationObserver(function () {
      if (inSync) return;
      clearTimeout(attesa);
      attesa = setTimeout(riallinea, 0);
    });
    osservatore.observe(el, { childList: true, subtree: true, attributes: true,
                              attributeFilter: ["disabled", "hidden", "style", "label"] });
    el.tsRiallinea = riallinea;
    nascoste();
    if (Array.prototype.some.call(el.options, function (o) { return o.hidden; })) riallinea();
  }

  // Oltre all'opt-in (.js-searchable), ogni tendina lunga diventa ricercabile da
  // sola: con più di AUTO_MIN opzioni cercare a occhio non funziona più
  // (corsi, persone, mansioni, asset). Si esclude con data-no-search, oppure
  // quando è una lista a più righe (size) — lì la ricerca la fa già la pagina.
  // Nel modulo Anagrafica tutte le tendine si cercano scrivendo, anche le corte (richiesta del 24/11/2026).
  var AUTO_MIN = (location.pathname.indexOf("/anagrafica/") === 0 || window.HUB_TENDINE_TUTTE_RICERCABILI) ? 1 : 10;
  function autoCandidata(el) {
    if (el.hasAttribute("data-no-search") || el.hasAttribute("data-picker")) return false;
    if (el.size && el.size > 1) return false;
    if (el.closest("[data-no-search]")) return false;
    // Il mese del calendario (flatpickr) fa parte del calendario: resta com'è.
    if (el.closest(".flatpickr-calendar")) return false;
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
    // Tendine create dopo il caricamento da altri script (filtri di colonna e «Ordina per…»
    // delle tabelle, righe aggiunte nei moduli): diventano ricercabili appena compaiono.
    var attesa = null;
    new MutationObserver(function (mutazioni) {
      var nuove = mutazioni.some(function (m) {
        return Array.prototype.some.call(m.addedNodes, function (n) {
          return n.nodeType === 1 && (n.tagName === "SELECT" || (n.querySelector && n.querySelector("select")));
        });
      });
      if (!nuove) return;
      clearTimeout(attesa);
      attesa = setTimeout(function () { initAll(document); }, 0);
    }).observe(document.body, { childList: true, subtree: true });
  });
  // I select caricati via HTMX (gli eventi bubblano fino a document). Si aspetta
  // la fine del settle: con un elemento che mantiene lo stesso id, HTMX rimette
  // le classi originali al termine dello swap e toglierebbe quelle di Tom Select
  // (la tendina nativa ricompariva accanto a quella ricercabile).
  document.addEventListener("htmx:afterSettle", function (evt) {
    var root = (evt.detail && evt.detail.elt) || evt.target || document;
    // Con hx-swap="outerHTML" elt e' il nodo sostituito, ormai fuori dal DOM: si
    // riparte dal documento (initOne salta i select gia' inizializzati).
    initAll(root.isConnected === false ? document : root);
  });
})();
