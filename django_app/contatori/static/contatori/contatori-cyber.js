/* Contatori IT · tocco «cyber»: filtri e ricerca della mappa della flotta, nodi del flusso che filtrano per
   famiglia, dati tecnici (IP, MAC, matricole, OID) a spaziatura fissa nelle tabelle. Nessun cambio di comportamento. */
(function () {
  "use strict";

  function initMappa() {
    var map = document.querySelector("[data-cc-map]:not([data-cc-pronta])");
    if (!map) return;
    map.setAttribute("data-cc-pronta", "1");
    var tiles = map.querySelectorAll(".cc-tile");
    var bottoni = map.querySelectorAll("[data-cc-stato]");
    var cerca = map.querySelector("[data-cc-cerca]");
    var nodi = document.querySelectorAll("[data-cc-famiglia]");
    var stato = "", famiglia = "";
    function filtra() {
      var q = (cerca && cerca.value || "").trim().toLowerCase();
      tiles.forEach(function (t) {
        t.hidden = (!!stato && t.dataset.stato !== stato) || (!!famiglia && t.dataset.famiglia !== famiglia) ||
                   (!!q && t.dataset.testo.indexOf(q) === -1);
      });
    }
    bottoni.forEach(function (b) {
      b.addEventListener("click", function () {
        stato = stato === b.dataset.ccStato ? "" : b.dataset.ccStato;
        bottoni.forEach(function (x) { x.classList.toggle("is-active", x.dataset.ccStato === stato); });
        filtra();
      });
    });
    nodi.forEach(function (n) {
      n.addEventListener("click", function (ev) {
        ev.preventDefault();
        famiglia = famiglia === n.dataset.ccFamiglia ? "" : n.dataset.ccFamiglia;
        nodi.forEach(function (x) { x.classList.toggle("is-active", x.dataset.ccFamiglia === famiglia); });
        filtra();
        map.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
    if (cerca) cerca.addEventListener("input", filtra);
  }

  var TECNICO = [
    /^(\d{1,3}\.){3}\d{1,3}(:\d+)?$/,                 // IPv4 (con porta)
    /^([0-9A-F]{2}[:-]){5}[0-9A-F]{2}$/i,             // MAC
    /^\.?1\.3\.6\.1(\.\d+)+$/,                        // OID
    /^[A-Z0-9]{2,}[-/]?[A-Z0-9-]*\d[A-Z0-9-]*$/       // matricole e nomi host maiuscoli con cifre
  ];
  function tecnico(t) {
    t = (t || "").trim();
    if (!t || t.length > 40) return false;
    for (var i = 0; i < TECNICO.length; i++) { if (TECNICO[i].test(t)) return true; }
    return false;
  }
  function mono(root) {
    (root || document).querySelectorAll(".contatori-module table td:not([data-cc-visto])").forEach(function (td) {
      td.setAttribute("data-cc-visto", "1");
      if (!td.children.length) { if (tecnico(td.textContent)) td.classList.add("cc-mono"); return; }
      var el = Array.prototype.find.call(td.querySelectorAll("a, strong, b, span"), function (x) { return !x.children.length; });
      if (el && tecnico(el.textContent)) el.classList.add("cc-mono");
    });
  }

  function avvio() { initMappa(); mono(document); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvio); else avvio();
  document.addEventListener("htmx:afterSettle", avvio);
})();
