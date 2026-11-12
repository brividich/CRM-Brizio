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

    // Software: ricerca e produttore.
    var search = root.querySelector("[data-pcs-sw-search]");
    var swRows = root.querySelectorAll("[data-pcs-sw-table] tbody tr[data-vendor]");
    var vendors = root.querySelectorAll("[data-pcs-vendor]");
    var count = root.querySelector("[data-pcs-sw-count]");
    var vendor = "";
    function filtraSoftware() {
      var q = (search && search.value || "").trim().toLowerCase();
      var n = 0;
      swRows.forEach(function (r) {
        var ok = (!vendor || r.dataset.vendor === vendor) && (!q || r.textContent.toLowerCase().indexOf(q) !== -1);
        r.hidden = !ok;
        if (ok) n++;
      });
      if (count) count.textContent = (q || vendor) ? n + " di " + swRows.length + " programmi" + (vendor ? " · " + vendor : "") : "";
    }
    if (search) search.addEventListener("input", filtraSoftware);
    vendors.forEach(function (b) {
      b.addEventListener("click", function () {
        vendor = vendor === b.dataset.pcsVendor ? "" : b.dataset.pcsVendor;
        vendors.forEach(function (x) { x.classList.toggle("is-active", x.dataset.pcsVendor === vendor); });
        filtraSoftware();
      });
    });

    // Timeline per tipo.
    var tlButtons = root.querySelectorAll("[data-pcs-tl]");
    var tlRows = root.querySelectorAll(".pcs-timeline li[data-tipo]");
    function filtraTimeline(tipo) {
      tlButtons.forEach(function (x) { x.classList.toggle("is-active", x.dataset.pcsTl === tipo); });
      tlRows.forEach(function (r) { r.hidden = !!tipo && r.dataset.tipo !== tipo; });
    }
    tlButtons.forEach(function (b) { b.addEventListener("click", function () { filtraTimeline(b.dataset.pcsTl); }); });

    // L'esito del controllo AI compare in Panoramica: ci si porta lì.
    var ai = root.querySelector("[data-pcs-ai]");
    if (ai) ai.addEventListener("submit", function () { show("panoramica", true); var out = document.getElementById("pc-ai-out"); if (out) out.scrollIntoView({ behavior: "smooth", block: "center" }); });

    window.addEventListener("hashchange", function () { show(location.hash.slice(1), false); });
  }

  function boot() { document.querySelectorAll("[data-pcs]").forEach(init); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
  document.addEventListener("htmx:afterSettle", boot);
})();
