/* NOVICROM HUB — init Tom Select sui <select class="js-searchable">.
 *
 * Ogni tendina con almeno due voci è ricercabile e, da 6 voci, ha in cima la
 * barra «Ordina: Come arriva · A→Z · Z→A» (esclusione con data-no-ordina).
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
      // Aspetto unico (proposta tendine del 28/11/2026): nella scelta singola la ricerca sta
      // in testa alla lista (il campo mostra solo il valore scelto); nella multipla ogni voce
      // ha la sua casella e le voci scelte restano nel campo con la × per toglierle.
      var plugins = el.multiple ? ["checkbox_options", "remove_button"] : ["dropdown_input"];
      // × per svuotare la scelta singola, solo se la tendina ha la voce vuota e non è obbligatoria.
      var svuotabile = !el.multiple && !el.required && !!el.querySelector("option[value='']");
      if (svuotabile) plugins.push({ name: "clear_button", options: { title: "Svuota la scelta" } });
      // eslint-disable-next-line no-undef
      var ts = new TomSelect(el, {
        create: false, // niente opzioni inventate: solo quelle esistenti
        allowEmptyOption: true,
        maxOptions: null, // niente cap: liste lunghe (dipendenti, asset...) intere
        placeholder: placeholder,
        plugins: plugins,
        // La lista si appende al body: dentro una card con overflow nascosto
        // (hr-card, fm-section, modali) altrimenti resta tagliata e invisibile.
        dropdownParent: "body",
        // Cerca su testo e value; ordina per pertinenza poi alfabetico.
        searchField: ["text"],
        // Le voci che la pagina nasconde (option.hidden, es. il ruolo stesso in «Riporta a»)
        // non si mostrano nella ricerca: sono anche disattivate, quindi non si scelgono.
        // Le voci «[codice] testo» (corsi, articoli…) mettono il codice in una colonna fissa.
        render: {
          option: function (data, escape) {
            var nascosta = data.$option && data.$option.hidden;
            return '<div class="ts-voce"' + (nascosta ? ' style="display:none"' : "") + ">" + contenuto(data, escape) + "</div>";
          },
          // Il campo chiuso mostra la voce scelta come nella lista: codice a parte, poi il testo.
          item: function (data, escape) {
            return '<div class="ts-scelta">' + contenuto(data, escape) + "</div>";
          },
          // Gruppi (<optgroup>): intestazione che resta in vista mentre si scorre.
          optgroup_header: function (data, escape) {
            return '<div class="optgroup-header">' + escape(data.label || "") + "</div>";
          },
        },
      });
      ts.wrapper.classList.add("hub-ts");
      collega(el, ts);
      testaLista(ts);
      ordinamento(el, ts);
      conteggio(ts);
      // Con lo zoom CSS di theme.css (schermi 4K: :root{zoom:1.5}) le
      // coordinate di getBoundingClientRect e quelle assolute del body non
      // coincidono e la lista finiva mezza pagina più in basso. Si misura la
      // mappa reale con due sonde invece di fidarsi di scrollY.
      ts.positionDropdown = function () {
        posiziona(this.control, this.dropdown);
      };
    } catch (e) {
      // Fail-safe: in caso di errore resta il select nativo.
      el.dataset.tsInit = "";
    }
  }

  // Testo di una voce: «[codice] titolo» mette il codice in una colonna fissa, «Nome — reparto»
  // mette il reparto a destra (come nel picker multiplo di Anagrafica).
  function contenuto(data, escape) {
    var testo = String(data.text == null ? "" : data.text);
    var m = /^\[([^\]]{1,24})\]\s*(.+)$/.exec(testo);
    if (m) return '<span class="ts-cod">' + escape(m[1]) + '</span><span class="ts-txt">' + escape(m[2]) + "</span>";
    var trattino = testo.indexOf(" — ");
    if (trattino > 0) {
      return '<span class="ts-txt">' + escape(testo.slice(0, trattino)) + '</span><span class="ts-dopo">' + escape(testo.slice(trattino + 3)) + "</span>";
    }
    return '<span class="ts-txt">' + escape(testo) + "</span>";
  }

  // Smartphone: sotto FOGLIO_MAX px la lista si apre dal basso a tutto schermo (classe hub-foglio).
  var FOGLIO_MAX = 640;

  // Lista larga quanto serve: almeno LARGA_MIN e al massimo LARGA_MAX px, mai meno del campo
  // e mai oltre lo schermo; allineata al campo, si sposta a sinistra se a destra non c'è
  // spazio. Con lo zoom CSS di theme.css (schermi 4K: :root{zoom:1.5}) le coordinate di
  // getBoundingClientRect e quelle assolute del body non coincidono: si misura la mappa
  // reale con due sonde invece di fidarsi di scrollY. Serve anche al picker multiplo
  // di Anagrafica (window.hubPosizionaLista).
  var LARGA_MIN = 480, LARGA_MAX = 640, MARGINE = 12;
  function posiziona(campo, lista) {
    var foglio = (document.documentElement.clientWidth || window.innerWidth) <= FOGLIO_MAX;
    lista.classList.toggle("hub-foglio", foglio);
    if (foglio) {
      lista.style.width = lista.style.top = lista.style.left = "";
      return;
    }
    var r = campo.getBoundingClientRect();
    var a = document.createElement("div"), b = document.createElement("div");
    a.style.cssText = b.style.cssText = "position:absolute;width:0;height:0;left:0;top:0;pointer-events:none;";
    b.style.top = "1000px";
    document.body.appendChild(a); document.body.appendChild(b);
    var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    document.body.removeChild(a); document.body.removeChild(b);
    var k = (rb.top - ra.top) / 1000 || 1;
    var schermo = document.documentElement.clientWidth || window.innerWidth;
    var larga = Math.max(r.width, Math.min(LARGA_MAX, Math.max(LARGA_MIN, r.width)));
    larga = Math.min(larga, schermo - 2 * MARGINE);
    var sinistra = Math.min(r.left, schermo - MARGINE - larga);
    sinistra = Math.max(MARGINE, sinistra);
    lista.style.width = (larga / k) + "px";
    lista.style.top = ((r.bottom - ra.top) / k) + "px";
    lista.style.left = ((sinistra - ra.left) / k) + "px";
  }
  window.hubPosizionaLista = posiziona;

  // Testa della lista: nella scelta singola è la riga della ricerca (plugin dropdown_input),
  // nella multipla una riga propria; lì si aggiunge poi la barra «Ordina».
  function testaLista(ts) {
    var testa = ts.dropdown.querySelector(".dropdown-input-wrap");
    if (!testa) {
      testa = document.createElement("div");
      ts.dropdown.insertBefore(testa, ts.dropdown.firstChild);
    }
    testa.classList.add("ts-testa");
    if (!ts.settings.mode || ts.settings.mode === "single") {
      var metti = function () { ts.control_input.placeholder = "Scrivi per cercare…"; };
      metti();
      ts.on("dropdown_open", metti);
    }
    ts.hubTesta = testa;
    return testa;
  }

  // Sotto la testa: quante voci ci sono e, mentre si cerca, quante ne trova.
  function conteggio(ts) {
    var riga = document.createElement("div");
    riga.className = "ts-conta";
    ts.hubTesta.parentNode.insertBefore(riga, ts.hubTesta.nextSibling);
    var aggiorna = function () {
      var tutte = Object.keys(ts.options).filter(function (v) { return v !== ""; }).length;
      riga.hidden = tutte < ORDINA_MIN;
      if (riga.hidden) return;
      var q = (ts.lastQuery || "").trim();
      var trovate = ((ts.currentResults && ts.currentResults.items) || []).filter(function (x) { return x.id !== ""; }).length;
      riga.textContent = q ? trovate + " su " + tutte + " voci" : tutte + " voci";
    };
    var refresh = ts.refreshOptions;
    ts.refreshOptions = function () {
      var esito = refresh.apply(this, arguments);
      aggiorna();
      return esito;
    };
    ts.on("dropdown_open", aggiorna);
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

  // Ordinamento scelto dall'utente dentro la tendina: «A→Z», «Z→A» oppure «Come
  // arriva» (l'ordine della pagina: stati, priorità, mesi hanno un ordine voluto).
  // La scelta si ricorda per quella tendina di quella pagina. La barra compare solo
  // con almeno ORDINA_MIN voci; la voce vuota («— scegli —») resta sempre in cima.
  // Mentre si cerca vale prima la pertinenza, poi l'ordine scelto (24/11/2026).
  var ORDINA_MIN = 6;
  var ORDINI = [
    { k: "originale", t: "Come arriva", title: "Ordine della pagina" },
    { k: "az", t: "A→Z", title: "Ordine alfabetico" },
    { k: "za", t: "Z→A", title: "Ordine alfabetico inverso" },
  ];

  function chiaveOrdine(el) {
    var nome = el.name || el.id || "";
    if (!nome) return "";
    return "hub:tendina-ordine:" + location.pathname + "|" + nome;
  }

  function leggiOrdine(el) {
    var k = chiaveOrdine(el);
    try { return (k && localStorage.getItem(k)) || "originale"; } catch (e) { return "originale"; }
  }

  function campiOrdine(ordine) {
    var campi = [{ field: "$score" }, { field: "_vuota", direction: "desc" }];
    if (ordine === "az") campi.push({ field: "text", direction: "asc" });
    else if (ordine === "za") campi.push({ field: "text", direction: "desc" });
    campi.push({ field: "$order" });
    return campi;
  }

  function ordinamento(el, ts) {
    if (el.hasAttribute("data-no-ordina")) return;
    var segna = function (value, data) { if (data) data._vuota = value === "" ? 1 : 0; };
    Object.keys(ts.options).forEach(function (v) { segna(v, ts.options[v]); });
    ts.on("option_add", segna);

    var ordine = leggiOrdine(el);
    ts.settings.sortField = campiOrdine(ordine);

    var barra = document.createElement("div");
    barra.className = "ts-ordina";
    barra.setAttribute("role", "group");
    barra.setAttribute("aria-label", "Ordina le voci");
    var etichetta = document.createElement("span");
    etichetta.className = "ts-ordina-lbl";
    etichetta.textContent = "Ordina";
    barra.appendChild(etichetta);
    ORDINI.forEach(function (o) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "ts-ordina-btn";
      b.dataset.ordine = o.k;
      b.textContent = o.t;
      b.title = o.title;
      barra.appendChild(b);
    });
    var evidenzia = function () {
      Array.prototype.forEach.call(barra.querySelectorAll(".ts-ordina-btn"), function (b) {
        var attivo = b.dataset.ordine === ordine;
        b.classList.toggle("is-on", attivo);
        b.setAttribute("aria-pressed", attivo ? "true" : "false");
      });
    };
    evidenzia();
    // mousedown: senza preventDefault il clic toglie il fuoco e chiude la tendina.
    barra.addEventListener("mousedown", function (e) { e.preventDefault(); e.stopPropagation(); });
    barra.addEventListener("click", function (e) {
      var b = e.target.closest(".ts-ordina-btn");
      if (!b) return;
      e.preventDefault();
      e.stopPropagation();
      ordine = b.dataset.ordine;
      var k = chiaveOrdine(el);
      try { if (k) { if (ordine === "originale") localStorage.removeItem(k); else localStorage.setItem(k, ordine); } } catch (err) { /* niente memoria */ }
      ts.settings.sortField = campiOrdine(ordine);
      evidenzia();
      ts.refreshOptions(false);
      ts.focus();
    });
    // Sulla stessa riga della ricerca (o in testa alla lista nella scelta multipla).
    (ts.hubTesta || ts.dropdown).appendChild(barra);
    var mostra = function () {
      barra.hidden = Object.keys(ts.options).length < ORDINA_MIN;
    };
    mostra();
    ts.on("dropdown_open", mostra);
  }

  // Oltre all'opt-in (.js-searchable), ogni tendina diventa ricercabile da sola, in
  // tutto il portale e anche le corte (richiesta del 24/11/2026: prima solo oltre 10
  // voci, poi tutte in Anagrafica). Resta nativa solo con una voce sola. Si esclude
  // con data-no-search, oppure quando è una lista a più righe (size) — lì la ricerca
  // la fa già la pagina — o un select nascosto di proposito (usato come dato).
  var AUTO_MIN = 1;
  function autoCandidata(el) {
    if (el.hasAttribute("data-no-search") || el.hasAttribute("data-picker")) return false;
    if (el.size && el.size > 1) return false;
    if (el.closest("[data-no-search]")) return false;
    if (el.hidden || el.style.display === "none") return false;
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
