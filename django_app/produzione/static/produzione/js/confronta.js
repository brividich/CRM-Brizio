/* NOVICROM HUB — Ordini di produzione: scelta dei report da confrontare (2-6) negli elenchi dei report CMM. */
(function () {
  "use strict";
  var MASSIMO = 6;

  function prepara(form) {
    var barra = form.querySelector(".prod-confronta-barra");
    var conta = form.querySelector("[data-confronta-conta]");
    var caselle = function () { return Array.prototype.slice.call(form.querySelectorAll("input[name=r]")); };
    function aggiorna() {
      var scelte = caselle().filter(function (c) { return c.checked; });
      barra.hidden = scelte.length === 0;
      conta.textContent = scelte.length === 1
        ? "1 report scelto: scegline almeno un altro"
        : scelte.length + " report scelti" + (scelte.length >= MASSIMO ? " (massimo " + MASSIMO + ")" : "");
      barra.querySelector("button[type=submit]").disabled = scelte.length < 2;
      caselle().forEach(function (c) { if (!c.checked) c.disabled = scelte.length >= MASSIMO; });
      caselle().forEach(function (c) { c.closest("tr").classList.toggle("is-scelto", c.checked); });
    }
    form.addEventListener("change", aggiorna);
    form.querySelector("[data-confronta-annulla]").addEventListener("click", function () {
      caselle().forEach(function (c) { c.checked = false; });
      aggiorna();
    });
    aggiorna();
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-confronta]").forEach(prepara);
  });
})();
