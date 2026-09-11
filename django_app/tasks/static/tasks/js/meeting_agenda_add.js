/* Aggiunta «live» di un punto ODG (include _meeting_agenda_add.html).
 *
 * Il punto e' scritto subito lato server: in riunione non c'e' il tempo di
 * ricordarsi di salvare, e un punto perso e' un punto non trattato.
 *
 * Il template ospite puo' definire `window.MEETING_AGENDA_ADD.onAdded(item,
 * position)` per inserire la riga senza ricaricare. Dove non lo fa - la
 * schermata di conduzione, che salva tutto da se' - si ricarica la pagina.
 */
(function () {
  'use strict';

  var box = document.getElementById('agenda-live-add');
  if (!box) { return; }

  var titolo = document.getElementById('agenda-live-titolo');
  var responsabile = document.getElementById('agenda-live-responsabile');
  var durata = document.getElementById('agenda-live-durata');
  var button = document.getElementById('agenda-live-btn');
  var msg = document.getElementById('agenda-live-msg');

  function say(text, isError) {
    if (!msg) { return; }
    msg.textContent = text || '';
    msg.classList.toggle('error', !!isError);
  }

  function submit() {
    var value = (titolo.value || '').trim();
    if (!value) { titolo.focus(); return; }

    var csrf = box.querySelector('[name="csrfmiddlewaretoken"]');
    var body = new URLSearchParams();
    body.set('titolo', value);
    if (responsabile && responsabile.value) { body.set('responsabile_id', responsabile.value); }
    if (durata && durata.value) { body.set('durata_minuti', durata.value); }

    button.disabled = true;
    say('Salvataggio…', false);

    fetch(box.dataset.url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrf ? csrf.value : '',
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: body
    })
      .then(function (response) { return response.json().catch(function () { return { ok: false }; }); })
      .then(function (data) {
        button.disabled = false;
        if (!data.ok) {
          say(data.reason === 'title_required' ? 'Serve un titolo.' : 'Punto non aggiunto.', true);
          return;
        }
        titolo.value = '';
        if (durata) { durata.value = ''; }
        say('Punto aggiunto.', false);
        titolo.focus();
        var hook = (window.MEETING_AGENDA_ADD || {}).onAdded;
        if (typeof hook === 'function') { hook(data.item, data.position); }
        else { window.location.reload(); }
      })
      .catch(function () {
        button.disabled = false;
        say('Errore di rete. Riprova.', true);
      });
  }

  button.addEventListener('click', submit);
  titolo.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') { event.preventDefault(); submit(); }
  });
})();
