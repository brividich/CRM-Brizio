/* Contatori IT: conferma sulle azioni con effetti (form con data-confirm) e pulsante occupato durante l'invio. */
(function () {
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form.closest || !form.closest(".contatori-module")) return;
    var testo = form.getAttribute("data-confirm");
    if (testo && !window.confirm(testo)) { ev.preventDefault(); return; }
    var occupato = form.getAttribute("data-busy");
    var bottone = form.querySelector("button[type=submit], button:not([type])");
    if (occupato && bottone) {
      // Dopo il submit: disabilitarlo prima annullerebbe l'invio del suo name/value.
      setTimeout(function () { bottone.disabled = true; bottone.textContent = occupato; }, 0);
    }
  });
})();
