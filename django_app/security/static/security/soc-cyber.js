/* SOC · tocco «cyber»: riquadri caricati a parte ([data-cy-lazy]), mappa dei PC (filtri e ricerca),
   dati tecnici a spaziatura fissa nelle tabelle (CVE, IP, MAC, KB, nomi host). Nessun cambio di comportamento. */
(function () {
  "use strict";

  // --- Riquadri caricati a parte ------------------------------------------------------------
  function carica(box, url) {
    box.setAttribute("aria-busy", "true");
    fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) { box.innerHTML = html; box.removeAttribute("aria-busy"); initMappa(box); monoTabelle(box); })
      .catch(function () { box.innerHTML = '<p class="sec-empty">Riquadro non disponibile in questo momento. Ricarica la pagina per riprovare.</p>'; });
  }
  function lazy(root) {
    (root || document).querySelectorAll("[data-cy-lazy]:not([data-cy-done])").forEach(function (box) {
      box.setAttribute("data-cy-done", "1");
      carica(box, box.getAttribute("data-cy-lazy"));
      box.addEventListener("click", function (ev) {
        var a = ev.target.closest("[data-cy-map-refresh]");
        if (!a) return;
        ev.preventDefault();
        box.innerHTML = '<p class="sec-muted sec-small cy-loading"><span class="cy-spin" aria-hidden="true"></span>Ricalcolo…</p>';
        carica(box, a.getAttribute("href"));
      });
    });
  }

  // --- Mappa dei PC -------------------------------------------------------------------------
  function initMappa(root) {
    var map = root.querySelector("[data-cy-map]");
    if (!map) return;
    var tiles = map.querySelectorAll(".cy-tile");
    var bottoni = map.querySelectorAll("[data-cy-map-tono]");
    var cerca = map.querySelector("[data-cy-map-search]");
    var tono = "";
    function filtra() {
      var q = (cerca && cerca.value || "").trim().toLowerCase();
      tiles.forEach(function (t) { t.hidden = (!!tono && t.dataset.tono !== tono) || (!!q && t.dataset.nome.indexOf(q) === -1); });
    }
    bottoni.forEach(function (b) {
      b.addEventListener("click", function () {
        tono = tono === b.dataset.cyMapTono ? "" : b.dataset.cyMapTono;
        bottoni.forEach(function (x) { x.classList.toggle("is-active", x.dataset.cyMapTono === tono); });
        filtra();
      });
    });
    if (cerca) cerca.addEventListener("input", filtra);
  }

  // --- Dati tecnici a spaziatura fissa -----------------------------------------------------------
  var TECNICO = [
    /^CVE-\d{4}-\d{3,}$/i,                                // CVE
    /^(\d{1,3}\.){3}\d{1,3}(\/\d{1,2})?$/,                // IPv4
    /^([0-9A-F]{2}[:-]){5}[0-9A-F]{2}$/i,                 // MAC
    /^KB\d{6,8}$/i,                                       // KB Microsoft
    /^[A-Z][A-Z0-9]*-?[A-Z0-9-]*\d[A-Z0-9-]*(\.[\w.-]+)?$/ // nome host maiuscolo con cifre (PC-01, SRVDC01)
  ];
  function tecnico(testo) {
    testo = (testo || "").trim();
    if (!testo || testo.length > 48) return false;
    for (var i = 0; i < TECNICO.length; i++) { if (TECNICO[i].test(testo)) return true; }
    return false;
  }
  function monoTabelle(root) {
    // Celle intere (testo semplice) o il primo link/grassetto della cella (es. nome del PC sopra a una riga di dettaglio).
    (root || document).querySelectorAll(".soc-module table td:not([data-cy-checked])").forEach(function (td) {
      td.setAttribute("data-cy-checked", "1");
      if (!td.children.length) { if (tecnico(td.textContent)) td.classList.add("cy-mono"); return; }
      var el = Array.prototype.find.call(td.querySelectorAll("a, strong, b"), function (x) { return !x.children.length; });
      if (el && tecnico(el.textContent)) el.classList.add("cy-mono");
    });
  }

  function avvio() { lazy(document); monoTabelle(document); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvio); else avvio();
  document.addEventListener("htmx:afterSettle", avvio);
  // Tabelle riscritte dai filtri o dalla paginazione: ricontrollo leggero, al massimo una volta per fotogramma.
  var attesa = false;
  var obs = new MutationObserver(function () {
    if (attesa) return;
    attesa = true;
    requestAnimationFrame(function () { attesa = false; monoTabelle(document); });
  });
  function osserva() { var m = document.querySelector(".soc-module"); if (m) obs.observe(m, { childList: true, subtree: true }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", osserva); else osserva();
})();
