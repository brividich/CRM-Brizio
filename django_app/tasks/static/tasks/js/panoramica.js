/* Panoramica di commessa.
   1. «Assegna» di «Cosa manca» apre il Percorso (chiuso finché non serve).
   2. Quando il Percorso cambia (tappa assegnata, tolta, «non serve»), la pagina
      rilegge se stessa e aggiorna le zone vive: «Cosa manca» e linea del tempo. */
(function () {
  'use strict';
  var percorso = document.querySelector('[data-ko-percorso]');
  if (!percorso) return;

  function apri() {
    percorso.open = true;
    percorso.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[href="#percorso"]');
    if (!a) return;
    e.preventDefault();
    apri();
  });
  if (window.location.hash === '#percorso') apri();
  window.addEventListener('hashchange', function () {
    if (window.location.hash === '#percorso') apri();
  });

  var blocco = percorso.querySelector('[data-tp-block]');
  if (!blocco || !window.MutationObserver) return;
  var timer = null;
  function rileggi() {
    fetch(window.location.href, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(); })
      .then(function (html) {
        var nuovo = new DOMParser().parseFromString(html, 'text/html');
        document.querySelectorAll('[data-ka-live]').forEach(function (zona) {
          var fresca = nuovo.querySelector('[data-ka-live="' + zona.getAttribute('data-ka-live') + '"]');
          if (!fresca) return;
          zona.innerHTML = fresca.innerHTML;
          zona.className = fresca.className;
        });
        var testo = nuovo.querySelector('[data-ko-percorso] > summary');
        var qui = percorso.querySelector(':scope > summary');
        if (testo && qui) qui.innerHTML = testo.innerHTML;
      })
      .catch(function () { /* la pagina resta com'è: al prossimo caricamento è aggiornata */ });
  }
  new MutationObserver(function () {
    clearTimeout(timer);
    timer = setTimeout(rileggi, 250);
  }).observe(blocco, { childList: true });
})();
