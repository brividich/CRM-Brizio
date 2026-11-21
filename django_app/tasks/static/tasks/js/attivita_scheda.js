/* Scheda dell'attività: stato, sotto-attività, «Sposta la scadenza», collegamenti.

   Ogni modifica passa dagli indirizzi che già usano il pannello e il Piano
   (task_azione_rapida, dipendenze del Gantt): stesse regole, decide il server.
   Dopo il salvataggio la pagina si ricarica, così si vede lo stato salvato
   e la Cronologia aggiornata. */
(function () {
  'use strict';

  var scheda = document.querySelector('[data-ka-scheda]');
  if (!scheda) return;
  var csrf = scheda.getAttribute('data-csrf');
  var esito = document.querySelector('[data-ka-esito]');

  function dici(testo, errore) {
    if (!esito) return;
    esito.textContent = testo;
    esito.classList.toggle('is-ko', !!errore);
    esito.hidden = false;
  }

  function invia(url, dati) {
    return fetch(url, {
      method: 'POST',
      headers: {
        'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      credentials: 'same-origin',
      body: new URLSearchParams(dati || {}).toString()
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        return { ok: r.ok && j.ok !== false, messaggio: j.messaggio || j.message || j.reason || j.error || '' };
      });
    });
  }

  function salvaERicarica(controllo, url, dati, fallback) {
    if (controllo) controllo.disabled = true;
    return invia(url, dati).then(function (res) {
      if (!res.ok) {
        dici(res.messaggio || 'Modifica non salvata.', true);
        if (controllo) controllo.disabled = false;
        return;
      }
      dici(res.messaggio || fallback);
      window.location.reload();
    }).catch(function () {
      dici('Non riesco a salvare: controlla la connessione e riprova.', true);
      if (controllo) controllo.disabled = false;
    });
  }

  /* Campi che si salvano da soli o mostrano «Salva» solo se cambiano. */
  document.querySelectorAll('[data-mostra-salva]').forEach(function (campo) {
    var salva = campo.form.querySelector('button[type="submit"]');
    var iniziale = campo.value;
    campo.addEventListener('input', function () { salva.hidden = campo.value === iniziale; });
  });
  document.querySelectorAll('[data-invia-al-cambio]').forEach(function (campo) {
    campo.addEventListener('change', function () { if (campo.value) campo.form.requestSubmit(); });
  });

  /* «Sposta la scadenza»: stessa azione del menu «⋯» e del pannello. */
  var sposta = scheda.querySelector('[data-ka-sposta]');
  if (sposta) {
    sposta.addEventListener('submit', function (e) {
      e.preventDefault();
      salvaERicarica(sposta.querySelector('button[type="submit"]'), sposta.getAttribute('data-url'), {
        azione: 'date',
        inizio: sposta.getAttribute('data-inizio') || '',
        fine: sposta.elements.fine.value,
        motivo: sposta.elements.motivo.value
      }, 'Scadenza aggiornata.');
    });
  }

  /* Collegamenti: si sceglie il verso, poi l'attività (clic o trascinamento). */
  scheda.querySelectorAll('[data-ka-scollega-dep]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      salvaERicarica(btn, btn.getAttribute('data-url'), {}, 'Collegamento tolto.');
    });
  });

  var box = scheda.querySelector('[data-ka-colleg]');
  if (box) {
    var lista = box.querySelector('[data-ka-colleg-lista]');
    var aiuto = box.querySelector('[data-ka-colleg-aiuto]');
    var anelli = Array.prototype.slice.call(box.querySelectorAll('[data-ka-verso]'));
    var verso = null;

    var fine = function () {
      verso = null;
      lista.classList.remove('is-scelta');
      aiuto.hidden = true;
      anelli.forEach(function (a) { a.setAttribute('aria-pressed', 'false'); });
      lista.querySelectorAll('.is-bersaglio').forEach(function (li) { li.classList.remove('is-bersaglio'); });
    };
    var inizia = function (anello) {
      var nuovo = anello.getAttribute('data-ka-verso');
      if (verso === nuovo) { fine(); return; }
      fine();
      verso = nuovo;
      anello.setAttribute('aria-pressed', 'true');
      lista.classList.add('is-scelta');
      aiuto.hidden = false;
    };
    var collega = function (li) {
      if (!verso) return;
      var questa = box.getAttribute('data-task');
      var altra = li.getAttribute('data-ka-bersaglio');
      // «Viene dopo X»: X è la precedente. «Viene prima di X»: questa è la precedente.
      var dati = verso === 'dopo'
        ? { predecessor_id: altra, successor_id: questa }
        : { predecessor_id: questa, successor_id: altra };
      fine();
      li.classList.add('is-attesa');
      salvaERicarica(null, box.getAttribute('data-url'), dati, 'Attività collegate.');
    };

    anelli.forEach(function (anello) {
      anello.addEventListener('click', function () { inizia(anello); });
      anello.addEventListener('dragstart', function (e) {
        fine();
        verso = anello.getAttribute('data-ka-verso');
        lista.classList.add('is-scelta');
        e.dataTransfer.effectAllowed = 'link';
        try { e.dataTransfer.setData('text/plain', verso); } catch (err) { /* vecchi browser */ }
      });
      anello.addEventListener('dragend', function () { if (lista.querySelector('.is-attesa') === null) fine(); });
    });
    box.querySelector('[data-ka-colleg-annulla]').addEventListener('click', fine);
    lista.querySelectorAll('[data-ka-bersaglio]').forEach(function (li) {
      li.addEventListener('click', function () { collega(li); });
      li.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); collega(li); }
      });
      li.addEventListener('dragover', function (e) {
        if (!verso) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'link';
        li.classList.add('is-bersaglio');
      });
      li.addEventListener('dragleave', function () { li.classList.remove('is-bersaglio'); });
      li.addEventListener('drop', function (e) { e.preventDefault(); collega(li); });
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && verso) fine(); });
  }

  /* Sotto-attività: spunta senza ricaricare. */
  function contaSotto() {
    var label = document.getElementById('subtask-progress-label');
    var rows = document.querySelectorAll('#subtask-table tbody .st-row');
    if (!label || rows.length === 0) return;
    var fatte = document.querySelectorAll('#subtask-table tbody .st-row.done-row').length;
    label.textContent = fatte + ' di ' + rows.length + ' completate';
  }
  document.querySelectorAll('[data-st-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var row = document.getElementById('st-row-' + btn.getAttribute('data-st-toggle'));
      btn.disabled = true;
      fetch(btn.getAttribute('data-toggle-url'), {
        method: 'POST', credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' }
      }).then(function (r) { return r.json(); }).then(function (data) {
        btn.disabled = false;
        if (!data.ok || !row) return;
        var fatta = data.status === 'DONE';
        row.dataset.status = data.status;
        row.classList.toggle('done-row', fatta);
        btn.classList.toggle('done', fatta);
        btn.title = fatta ? 'Segna come Da fare' : 'Segna come Fatto';
        var sel = row.querySelector('select[name="status"]');
        if (sel) sel.value = data.status;
        contaSotto();
      }).catch(function () { btn.disabled = false; });
    });
  });
  contaSotto();
})();
