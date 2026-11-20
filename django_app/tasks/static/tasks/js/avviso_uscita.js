/* «Hai modifiche non salvate»: per i form lunghi del KICK-OFF (kickoff,
   convocazione, esito, VRF online). Un clic sul menu a metà compilazione
   faceva perdere tutto senza avviso.

   Conta come modifica: scrivere o scegliere in un campo con «name» del form
   marcato data-avviso-uscita, oppure un clic su un pulsante dentro una zona
   data-avviso-conta (l'ordine del giorno si costruisce a pulsanti e finisce
   in un campo nascosto solo al salvataggio).
   Non conta: quello che si salva da solo (note dei punti, barra attività,
   zone data-avviso-ignora). Con l'avviso di conflitto in pagina il form parte
   già «modificato»: quello che c'è dentro non è salvato. */
(function () {
  'use strict';

  var IGNORA = '[data-avviso-ignora], [data-agenda-nota], [data-qt-bar]';

  document.querySelectorAll('form[data-avviso-uscita]').forEach(function (form) {
    var modificato = !!form.querySelector('.kv-conflitto');

    function segna(ev) {
      var el = ev.target;
      if (!el || !el.closest || el.closest(IGNORA)) return;
      if (ev.type === 'click') {
        if (el.closest('[data-avviso-conta] button, button[data-avviso-conta]')) modificato = true;
        return;
      }
      if (el.name && el.name !== 'csrfmiddlewaretoken' && el.name !== 'impronta') modificato = true;
    }

    form.addEventListener('input', segna);
    form.addEventListener('change', segna);
    form.addEventListener('click', segna);
    form.addEventListener('submit', function () { modificato = false; });

    window.addEventListener('beforeunload', function (ev) {
      if (!modificato) return;
      ev.preventDefault();
      ev.returnValue = '';
    });
  });
})();
