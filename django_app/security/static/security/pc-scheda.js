/* Scheda PC del SOC (/soc/pc/): schede con #ancora, KPI e nodi del flusso cliccabili, filtri di CVE, software e timeline.
   Senza JavaScript tutte le sezioni restano visibili una sotto l'altra. */
(function () {
  "use strict";

  function init(root) {
    if (!root || root.dataset.pcsReady) return;
    root.dataset.pcsReady = "1";
    var tabs = root.querySelectorAll("[data-pcs-tab]");
    var panes = root.querySelectorAll("[data-pcs-pane]");
    var nav = root.querySelector(".pcs-tabs");

    function show(name, push) {
      var found = false;
      panes.forEach(function (p) { var on = p.dataset.pcsPane === name; p.classList.toggle("is-active", on); found = found || on; });
      if (!found) return show("panoramica", push);
      tabs.forEach(function (t) { var on = t.dataset.pcsTab === name; t.classList.toggle("is-active", on); t.setAttribute("aria-selected", on ? "true" : "false"); });
      if (push) { try { history.replaceState(null, "", "#" + name); } catch (e) { /* niente */ } }
    }

    root.classList.add("is-tabbed");
    if (nav) nav.classList.add("is-ready");
    show((location.hash || "#panoramica").slice(1), false);

    tabs.forEach(function (t) { t.addEventListener("click", function () { show(t.dataset.pcsTab, true); }); });

    // Qualunque elemento con data-pcs-go apre la sua scheda; data-pcs-focus porta a un riquadro, data-pcs-filter filtra la timeline.
    root.addEventListener("click", function (ev) {
      var el = ev.target.closest("[data-pcs-go]");
      if (!el || !root.contains(el)) return;
      show(el.dataset.pcsGo, true);
      if (el.dataset.pcsFilter) filtraTimeline(el.dataset.pcsFilter);
      var target = el.dataset.pcsFocus ? document.getElementById(el.dataset.pcsFocus) : nav;
      if (target) {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        if (el.dataset.pcsFocus) { target.classList.remove("pcs-flash"); void target.offsetWidth; target.classList.add("pcs-flash"); }
      }
    });

    // CVE per gravità (legenda dell'anello).
    var cveButtons = root.querySelectorAll("[data-pcs-filter-cve]");
    var cveRows = root.querySelectorAll("[data-pcs-cve-list] li[data-grav]");
    cveButtons.forEach(function (b) {
      b.addEventListener("click", function () {
        var g = b.dataset.pcsFilterCve;
        cveButtons.forEach(function (x) { x.classList.toggle("is-active", x === b); });
        cveRows.forEach(function (r) { r.hidden = !!g && r.dataset.grav !== g; });
      });
    });

    // Software: ricerca + filtro (CVE, gravi, fonte, non recenti) + produttore, combinabili; ordinamento per colonna.
    var search = root.querySelector("[data-pcs-sw-search]");
    var tbody = root.querySelector("[data-pcs-sw-table] tbody");
    var swRows = Array.prototype.slice.call(root.querySelectorAll("[data-pcs-sw-table] tbody tr[data-vendor]"));
    var vendors = root.querySelectorAll("[data-pcs-vendor]");
    var swFilters = root.querySelectorAll("[data-pcs-sw-filter]");
    var count = root.querySelector("[data-pcs-sw-count]");
    var none = root.querySelector("[data-pcs-sw-none]");
    var reset = root.querySelector("[data-pcs-sw-reset]");
    var vendor = "", swFiltro = "";
    var prove = {
      cve: function (r) { return +r.dataset.cve > 0; },
      grave: function (r) { return +r.dataset.grave > 0; },
      vecchio: function (r) { return r.dataset.vecchio === "1"; },
      watchguard: function (r) { return (" " + r.dataset.fonti + " ").indexOf(" watchguard ") !== -1; },
      defender: function (r) { return (" " + r.dataset.fonti + " ").indexOf(" defender ") !== -1; }
    };
    function filtraSoftware() {
      var q = (search && search.value || "").trim().toLowerCase();
      var n = 0;
      swRows.forEach(function (r) {
        var ok = (!vendor || r.dataset.vendor === vendor) && (!swFiltro || prove[swFiltro](r)) &&
                 (!q || r.textContent.toLowerCase().indexOf(q) !== -1);
        r.hidden = !ok;
        if (ok) n++;
      });
      var filtrato = !!(q || vendor || swFiltro);
      if (count) count.textContent = filtrato ? n + " di " + swRows.length + " programmi" : swRows.length + " programmi";
      if (none) none.hidden = n > 0 || !swRows.length;
      if (reset) reset.hidden = !filtrato;
    }
    if (search) {
      search.addEventListener("input", filtraSoftware);
      search.addEventListener("keydown", function (ev) { if (ev.key === "Escape") { search.value = ""; filtraSoftware(); } });
    }
    swFilters.forEach(function (b) {
      b.addEventListener("click", function () {
        swFiltro = swFiltro === b.dataset.pcsSwFilter ? "" : b.dataset.pcsSwFilter;
        swFilters.forEach(function (x) { x.classList.toggle("is-active", x.dataset.pcsSwFilter === swFiltro); });
        filtraSoftware();
      });
    });
    vendors.forEach(function (b) {
      b.addEventListener("click", function () {
        vendor = vendor === b.dataset.pcsVendor ? "" : b.dataset.pcsVendor;
        vendors.forEach(function (x) { x.classList.toggle("is-active", x.dataset.pcsVendor === vendor); });
        filtraSoftware();
      });
    });
    if (reset) reset.addEventListener("click", function () {
      vendor = ""; swFiltro = ""; if (search) search.value = "";
      vendors.forEach(function (x) { x.classList.remove("is-active"); });
      swFilters.forEach(function (x) { x.classList.toggle("is-active", !x.dataset.pcsSwFilter); });
      filtraSoftware();
    });
    // «/» porta alla ricerca del software quando la sezione è aperta.
    document.addEventListener("keydown", function (ev) {
      var pane = root.querySelector('[data-pcs-pane="software"]');
      if (ev.key !== "/" || !search || !pane || !pane.classList.contains("is-active")) return;
      var t = ev.target.tagName;
      if (t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || ev.target.isContentEditable) return;
      ev.preventDefault(); search.focus();
    });
    var ordine = { col: "", su: true };
    function chiave(r, col) {
      if (col === "cve") return +r.dataset.grave * 10000 + +r.dataset.cve;
      if (col === "visto") return +r.dataset.visto || 0;
      if (col === "versione") return (r.dataset.versione || "").split(/[^0-9]+/).filter(Boolean).map(function (x) { return ("000000" + x).slice(-6); }).join(".");
      return r.dataset.nome || "";
    }
    root.querySelectorAll("[data-pcs-sort]").forEach(function (b) {
      b.addEventListener("click", function () {
        var col = b.dataset.pcsSort;
        // CVE e Visto partono dal valore più alto, nome e versione dal più basso.
        ordine.su = ordine.col === col ? !ordine.su : !(col === "cve" || col === "visto");
        ordine.col = col;
        swRows.sort(function (a, c) {
          var x = chiave(a, col), y = chiave(c, col);
          return (x < y ? -1 : x > y ? 1 : 0) * (ordine.su ? 1 : -1);
        });
        swRows.forEach(function (r) { tbody.insertBefore(r, none || null); });
        root.querySelectorAll("[data-pcs-sort]").forEach(function (x) {
          x.classList.toggle("is-sorted", x === b);
          x.dataset.dir = x === b ? (ordine.su ? "asc" : "desc") : "";
        });
      });
    });

    // Timeline: filtro per tipo (i giorni senza fatti visibili spariscono) e salto al giorno dall'istogramma.
    var tlButtons = root.querySelectorAll("[data-pcs-tl]");
    var tlDays = root.querySelectorAll("[data-pcs-tl-day]");
    var tlNone = root.querySelector("[data-pcs-tl-none]");
    function filtraTimeline(tipo) {
      var totale = 0;
      tlButtons.forEach(function (x) { x.classList.toggle("is-active", x.dataset.pcsTl === tipo); });
      tlDays.forEach(function (d) {
        var n = 0;
        d.querySelectorAll("li[data-tipo]").forEach(function (r) { var ok = !tipo || r.dataset.tipo === tipo; r.hidden = !ok; if (ok) n++; });
        d.hidden = n === 0;
        var c = d.querySelector("[data-pcs-tl-daycount]");
        if (c) c.textContent = n;
        totale += n;
      });
      if (tlNone) tlNone.hidden = totale > 0 || !tlDays.length;
    }
    tlButtons.forEach(function (b) { b.addEventListener("click", function () { filtraTimeline(b.dataset.pcsTl); }); });
    root.querySelectorAll("[data-pcs-day]").forEach(function (b) {
      b.addEventListener("click", function () {
        var d = document.getElementById(b.dataset.pcsDay);
        if (!d) return;
        if (d.hidden) filtraTimeline("");
        d.scrollIntoView({ behavior: "smooth", block: "start" });
        d.classList.remove("pcs-flash"); void d.offsetWidth; d.classList.add("pcs-flash");
      });
    });

    // L'esito del controllo AI compare in Panoramica: ci si porta lì.
    var ai = root.querySelector("[data-pcs-ai]");
    if (ai) ai.addEventListener("submit", function () { show("panoramica", true); var out = document.getElementById("pc-ai-out"); if (out) out.scrollIntoView({ behavior: "smooth", block: "center" }); });

    window.addEventListener("hashchange", function () { show(location.hash.slice(1), false); });
  }

  function boot() { document.querySelectorAll("[data-pcs]").forEach(init); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
  document.addEventListener("htmx:afterSettle", boot);
})();
