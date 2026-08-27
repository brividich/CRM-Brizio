/**
 * ana_table_ux.js — UX comune a TUTTE le tabelle del modulo Anagrafica HR
 * (e dei suoi sotto-moduli: formazione, qualifiche, sicurezza, MPQ, visite…).
 *
 * Caricato una volta sola da `anagrafica/components/subnav.html`, che è incluso
 * in ogni pagina del modulo: nessuna pagina deve fare nulla per averlo.
 *
 * 1) RICERCA LIVE — la casella di ricerca già presente sopra l'elenco filtra le
 *    righe mentre si digita, senza ricaricare. Dove la tabella è gestita da
 *    fm-table-enhanced deleghiamo a lui (`fmTableEnhanced.setSearch`): così il
 *    filtro riusa il caricamento automatico delle altre pagine di una tabella
 *    paginata server-side e convive con i filtri di colonna. Altrove si usa un
 *    filtro locale equivalente. Il submit del form resta valido e autorevole:
 *    la ricerca server-side copre anche i campi non mostrati in tabella.
 *
 * 2) RIGA CLICCABILE — l'intera riga porta dove porta il suo link principale.
 *    Ctrl/Cmd/click centrale aprono in una nuova scheda. La riga aperta resta
 *    evidenziata al ritorno sull'elenco (sessionStorage, per pagina).
 *    È un miglioramento *solo puntatore*: il link della riga resta al suo posto
 *    per la tastiera, così non si raddoppiano le tab-stop su elenchi lunghi.
 *
 * Opt-out: `data-ana-row-click="0"` sulla tabella (o su un antenato) toglie la
 * riga cliccabile; `data-ana-live-skip="1"` su un input toglie la ricerca live;
 * `data-ana-live-target="<selettore>"` su un input forza la tabella bersaglio.
 */
(function () {
  "use strict";

  var SEARCH_NAMES = /^(q|q_text|cerca|ricerca|search|filtro_q|query)$/i;
  var SKIP_HREF = /^(#|mailto:|tel:|javascript:)/i;
  var DESTRUCTIVE = /elimina|cancella|rimuovi|disattiva|archivia/i;
  var INTERACTIVE = "a,button,input,select,textarea,label,summary,details,form,[onclick],.no-row-click";
  var DEBOUNCE_MS = 120;

  function $$(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function isDataTable(table) {
    if (!table || table.tagName !== "TABLE") return false;
    if (table.closest("[data-fm-table-skip='1'], [data-table-enhanced='0']")) return false;
    if (!table.tHead || !table.tBodies || !table.tBodies[0]) return false;
    return table.tBodies[0].rows.length > 0;
  }

  function dataRows(table) {
    return $$("tr", table.tBodies[0]).filter(function (tr) {
      return !tr.hasAttribute("data-empty-row") &&
        !tr.classList.contains("fm-detail-row") &&
        tr.dataset.fmDetailRow !== "1";
    });
  }

  // ─── 1. Ricerca live ──────────────────────────────────────────────────────

  function liveInputs() {
    return $$("input[type=text], input[type=search]").filter(function (input) {
      if (input.dataset.anaLiveSkip === "1" || input.dataset.anaLiveInit === "1") return false;
      if (input.disabled || input.readOnly) return false;
      // Già live per conto suo (ricerca HTMX di formazione/sicurezza): un
      // secondo filtro sulle stesse righe si pesterebbe i piedi col primo.
      if (input.hasAttribute("hx-get") || input.hasAttribute("hx-post")) return false;
      return input.dataset.anaLiveSearch === "1" || SEARCH_NAMES.test(input.name || "");
    });
  }

  /* Tabella bersaglio: la prima tabella dati che *segue* l'input, cercata
     risalendo di antenato in antenato. Così in una pagina con più pannelli la
     ricerca di un pannello non va a filtrare la tabella di quello sotto. */
  function targetTable(input) {
    if (input.dataset.anaLiveTarget) {
      var forced = document.querySelector(input.dataset.anaLiveTarget);
      return isDataTable(forced) ? forced : null;
    }
    var node = input.parentElement;
    while (node && node !== document.body) {
      var following = $$("table", node).filter(function (table) {
        if (!isDataTable(table)) return false;
        return !!(input.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      if (following.length) return following[0];
      node = node.parentElement;
    }
    return null;
  }

  function localFilter(table, query) {
    var q = query.toLowerCase();
    dataRows(table).forEach(function (tr) {
      tr.style.display = (!q || tr.textContent.toLowerCase().indexOf(q) !== -1) ? "" : "none";
    });
  }

  function countChip(input) {
    var chip = document.createElement("span");
    chip.className = "ana-live-count";
    chip.hidden = true;
    var anchor = input.closest(".fmd-search, .hr-search, .fm-search") || input;
    anchor.parentNode.insertBefore(chip, anchor.nextSibling);
    return chip;
  }

  function emptyNote(table) {
    var note = document.createElement("div");
    note.className = "ana-live-empty";
    note.hidden = true;
    note.textContent = "Nessun risultato per questa ricerca.";
    var wrap = table.closest(".fmd-tablewrap, .hr-table-wrap, .ana-table-wrap, .table-responsive, .table-wrap") || table;
    wrap.parentNode.insertBefore(note, wrap.nextSibling);
    return note;
  }

  function bindLiveSearch(input) {
    var table = targetTable(input);
    if (!table) return;
    input.dataset.anaLiveInit = "1";

    var chip = countChip(input);
    var note = emptyNote(table);
    var timer = null;

    // Il contatore di fm-table-enhanced: nel modulo la barra controlli è
    // nascosta (subnav marca <body data-fm-hide-controls="1">), quindi lo
    // aggiorniamo noi passandogli il nostro chip — senza mai rubarlo a una
    // barra visibile.
    function adoptCounter() {
      if (!table._fmTblCountEl) table._fmTblCountEl = chip;
    }

    function refresh() {
      var q = input.value.trim();
      var rows = dataRows(table);
      var shown = rows.filter(function (tr) { return tr.style.display !== "none"; }).length;
      chip.hidden = !q;
      chip.textContent = shown + " / " + rows.length;
      chip.classList.toggle("ana-live-count-zero", q && shown === 0);
      note.hidden = !(q && shown === 0);
    }

    function apply() {
      var q = input.value.trim();
      adoptCounter();
      if (!(window.fmTableEnhanced && window.fmTableEnhanced.setSearch(table, q))) {
        localFilter(table, q);
      }
      refresh();
    }

    input.addEventListener("input", function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(apply, DEBOUNCE_MS);
    });
    input.addEventListener("search", apply);   // la "x" degli input type=search

    // Su una tabella paginata server-side fm-table unisce le altre pagine in
    // background: quando le righe arrivano, conteggio e nota vanno rifatti.
    if (window.MutationObserver) {
      new MutationObserver(function () {
        if (input.value.trim()) refresh();
      }).observe(table.tBodies[0], { childList: true });
    }

    // fm-table-enhanced inizializza in modo asincrono: quando la tabella è
    // pronta ripassiamo la query da lui, azzerando il filtro locale di ripiego
    // (che agisce sullo stesso `display` e altrimenti resterebbe appiccicato).
    table.addEventListener("fm-table:ready", function () {
      if (!input.value.trim()) return;
      dataRows(table).forEach(function (tr) { tr.style.display = ""; });
      apply();
    });
  }

  // ─── 2. Riga cliccabile ───────────────────────────────────────────────────

  function usableLink(a) {
    var href = a.getAttribute("href") || "";
    if (!href || SKIP_HREF.test(href)) return false;
    if (a.hasAttribute("download") || a.dataset.rowLink === "skip") return false;
    if (a.target && a.target !== "_self") return false;
    if (a.closest("form")) return false;
    if (DESTRUCTIVE.test(a.textContent || "")) return false;
    if (/danger/i.test(a.className || "")) return false;
    return true;
  }

  /* Href della riga: quello dichiarato, poi il link marcato `data-row-link`,
     infine il primo link utile in ordine di lettura (di norma il nome, o il
     bottone «Scheda» della colonna azioni). */
  function rowHref(tr) {
    if (tr.dataset.rowHref) return tr.dataset.rowHref;
    var marked = tr.querySelector("a[data-row-link]:not([data-row-link='skip'])");
    if (marked && usableLink(marked)) return marked.getAttribute("href");
    var found = "";
    $$("a[href]", tr).some(function (a) {
      if (!usableLink(a)) return false;
      found = a.getAttribute("href");
      return true;
    });
    return found;
  }

  function storageKey() {
    return "ana-row-sel:" + window.location.pathname;
  }

  function rememberRow(href) {
    try { window.sessionStorage.setItem(storageKey(), href); } catch (e) { /* storage negato */ }
  }

  function rememberedRow() {
    try { return window.sessionStorage.getItem(storageKey()) || ""; } catch (e) { return ""; }
  }

  function selectRow(tr) {
    $$(".ana-row-sel").forEach(function (other) { other.classList.remove("ana-row-sel"); });
    tr.classList.add("ana-row-sel");
  }

  function bindRowClick(table) {
    if (table.dataset.anaRowInit === "1") return;
    if (table.dataset.anaRowClick === "0" || table.closest("[data-ana-row-click='0']")) return;
    var tbody = table.tBodies[0];
    var marked = 0;
    var previous = rememberedRow();

    dataRows(table).forEach(function (tr) {
      var href = rowHref(tr);
      if (!href) return;
      tr.dataset.anaHref = href;
      tr.classList.add("ana-row-link");
      marked += 1;
      if (previous && href === previous) tr.classList.add("ana-row-sel");
    });
    if (!marked) return;
    table.dataset.anaRowInit = "1";

    function rowFor(event) {
      var tr = event.target.closest ? event.target.closest("tr") : null;
      if (!tr || !tr.dataset.anaHref) return null;
      if (event.target.closest(INTERACTIVE)) return null;
      return tr;
    }

    tbody.addEventListener("click", function (event) {
      var tr = rowFor(event);
      if (!tr) return;
      // Un click che chiude una selezione di testo dentro la riga non è un
      // click di apertura (una selezione altrove sulla pagina non c'entra).
      var sel = window.getSelection ? window.getSelection() : null;
      if (sel && !sel.isCollapsed && sel.anchorNode && tr.contains(sel.anchorNode)) return;
      var href = tr.dataset.anaHref;
      selectRow(tr);
      rememberRow(href);
      if (event.ctrlKey || event.metaKey || event.shiftKey) {
        window.open(href, "_blank", "noopener");
        return;
      }
      window.location.href = href;
    });

    tbody.addEventListener("auxclick", function (event) {
      if (event.button !== 1) return;
      var tr = rowFor(event);
      if (!tr) return;
      event.preventDefault();
      window.open(tr.dataset.anaHref, "_blank", "noopener");
    });
  }

  // ─── Avvio ────────────────────────────────────────────────────────────────

  function initAll() {
    $$("table").filter(isDataTable).forEach(bindRowClick);
    liveInputs().forEach(bindLiveSearch);
  }

  function start() {
    initAll();
    // Tabelle che arrivano dopo (HTMX, popover, pannelli aperti a richiesta).
    if (!window.MutationObserver || !document.body) return;
    var timer = null;
    new MutationObserver(function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(initAll, 150);
    }).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
