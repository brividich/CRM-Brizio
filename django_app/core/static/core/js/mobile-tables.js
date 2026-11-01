/* Tabelle su smartphone (≤720px).
   Una tabella più larga dello schermo, invece di scorrere di lato, mostra ogni riga come una
   scheda: la prima colonna fa da titolo, le altre diventano «Etichetta: valore» con l'etichetta
   presa dall'intestazione. Solo tabelle semplici (una riga di intestazione, niente celle unite);
   escluse quelle con data-mcards-off o già a schede per conto loro. Sopra i 720px non cambia
   niente: la classe .mcards c'è solo mentre il telefono è in verticale. */
(function () {
  "use strict";

  var mq = window.matchMedia("(max-width:720px)");
  var tables = [];

  var BLOCK_TAGS = /^(DIV|P|UL|OL|SECTION|TABLE|FORM)$/;

  function clean(t) { return String(t || "").replace(/\s+/g, " ").trim(); }

  function headCells(table) {
    var rows = table.tHead ? table.tHead.rows : [];
    if (rows.length !== 1) return null;
    var cells = Array.prototype.slice.call(rows[0].cells);
    for (var i = 0; i < cells.length; i++) if (cells[i].colSpan > 1 || cells[i].rowSpan > 1) return null;
    return cells;
  }

  function simpleBody(table, n) {
    var bodies = table.tBodies;
    for (var b = 0; b < bodies.length; b++) {
      var rows = bodies[b].rows;
      for (var r = 0; r < rows.length; r++) {
        var cells = rows[r].cells;
        for (var c = 0; c < cells.length; c++) {
          if (cells[c].rowSpan > 1) return false;
          /* Righe «vuoto»/dettaglio a tutta larghezza vanno bene; celle unite a metà no. */
          if (cells[c].colSpan > 1 && cells.length > 1) return false;
        }
        if (cells.length > 1 && cells.length !== n) return false;
      }
    }
    return true;
  }

  /* Testo dell'intestazione senza i comandi aggiunti dal motore tabelle (ordina, filtra). */
  function headText(th) {
    if (th.hasAttribute("data-mcards-label")) return clean(th.getAttribute("data-mcards-label"));
    var lbl = th.querySelector(".fm-th-label");
    return clean((lbl || th).textContent);
  }

  function label(table) {
    var heads = table.__mcHeads;
    if (!heads) return;
    Array.prototype.forEach.call(table.tBodies, function (tb) {
      Array.prototype.forEach.call(tb.rows, function (row) {
        if (row.cells.length === 1) { row.classList.add("mcards-full"); return; }
        if (row.__mcDone) return;
        row.__mcDone = true;
        var titled = false;
        Array.prototype.forEach.call(row.cells, function (td, i) {
          var h = heads[i] ? headText(heads[i]) : "";
          var text = clean(td.textContent);
          td.setAttribute("data-label", h);
          /* Casella di selezione senza intestazione: va nell'angolo, il titolo è la colonna dopo. */
          if (!h && !text && td.querySelector("input[type='checkbox'], input[type='radio']")) {
            td.classList.add("mcards-check");
            return;
          }
          if (!titled) { td.classList.add("mcards-title"); titled = true; return; }
          /* Campi vuoti («—», «-»): nella scheda non servono. */
          if (/^[-–—]?$/.test(text) && !td.querySelector("input, select, textarea, img, svg, button, a")) td.classList.add("mcards-empty");
          /* Senza etichetta, o con un'etichetta uguale al contenuto (es. pulsante «Scheda»). */
          if (!h || h === text) td.classList.add("mcards-nolabel");
          /* Più blocchi nella cella (righe di dettaglio): uno sotto l'altro a destra dell'etichetta. */
          var blocks = 0;
          for (var k = 0; k < td.children.length; k++) if (BLOCK_TAGS.test(td.children[k].tagName)) blocks++;
          if (blocks > 1) td.classList.add("mcards-stack");
        });
      });
    });
  }

  function eligible(table) {
    if (table.__mc || table.hasAttribute("data-mcards-off") || table.closest("[data-mcards-off], .mnav-sheet")) return false;
    if (table.getClientRects().length === 0) return false;
    var cs = window.getComputedStyle(table);
    if (cs.display !== "table") return false;
    if (table.tHead && window.getComputedStyle(table.tHead).display === "none") return false;
    var heads = headCells(table);
    if (!heads || heads.length < 3 || heads.length > 24) return false;
    if (!table.tBodies.length || !simpleBody(table, heads.length)) return false;
    /* Solo se davvero non ci sta: confronto con lo spazio del contenitore che scorre. */
    var box = (table._fmViewport || table.parentElement);
    var outer = box && box.parentElement ? box.parentElement : box;
    var avail = Math.min(outer ? outer.clientWidth : window.innerWidth, window.innerWidth);
    if (table.scrollWidth <= avail + 6) return false;
    table.__mcHeads = heads;
    return true;
  }

  /* Tabelle che non diventano schede (intestazioni a più righe, celle unite) ma escono dallo
     schermo: le si mette in un riquadro che scorre di lato da solo, così la pagina resta ferma. */
  function scrollBox(table) {
    if (table.__mcBox || table.getClientRects().length === 0) return;
    if (table.closest(".mnav-sheet, .mcards")) return;
    var w = document.documentElement.clientWidth;
    if (table.getBoundingClientRect().right <= w + 2) return;
    for (var p = table.parentElement; p && p !== document.body; p = p.parentElement) {
      var o = window.getComputedStyle(p).overflowX;
      if (o === "auto" || o === "scroll" || o === "hidden") return;
    }
    table.__mcBox = true;
    var box = document.createElement("div");
    box.className = "mtable-scroll";
    table.parentNode.insertBefore(box, table);
    box.appendChild(table);
  }

  function scan() {
    if (!mq.matches) return;
    document.querySelectorAll("table").forEach(function (table) {
      if (!eligible(table)) { scrollBox(table); return; }
      table.__mc = true;
      label(table);
      tables.push(table);
      /* Righe aggiunte dopo (filtri, «Mostra altre», HTMX): etichette anche a loro. */
      if (window.MutationObserver) {
        new MutationObserver(function () { label(table); })
          .observe(table, { childList: true, subtree: true });
      }
    });
    sync();
  }

  function sync() {
    var on = mq.matches;
    tables.forEach(function (t) {
      t.classList.toggle("mcards", on);
      var vp = t.closest(".fm-tbl-viewport");
      if (vp) vp.classList.toggle("mcards-vp", on);
    });
  }

  if (mq.addEventListener) mq.addEventListener("change", function () { sync(); scan(); });
  else if (mq.addListener) mq.addListener(function () { sync(); scan(); });

  /* Dopo il motore delle tabelle (fm-table) che può nascondere colonne o avvolgere la tabella. */
  window.addEventListener("load", function () { setTimeout(scan, 0); });
  document.addEventListener("htmx:afterSettle", function () { setTimeout(scan, 0); });
  var t = null;
  document.addEventListener("click", function () { clearTimeout(t); t = setTimeout(scan, 150); });
})();
