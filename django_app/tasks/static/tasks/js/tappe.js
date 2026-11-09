/* Percorso del kickoff (_tappe.html): assegna una tappa o segnala che non serve, senza ricaricare. */
(function () {
  'use strict';
  if (window.__tappeKickoff) { return; }
  window.__tappeKickoff = true;

  var CAMPI = { owner: 'assigned_to', due: 'due_date', asset: 'asset', testo: 'testo' };

  function csrf() {
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input) { return input.value; }
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function errore(block, testo) {
    var err = block.querySelector('[data-tp="err"]');
    if (!err) { return; }
    err.textContent = testo || '';
    err.hidden = !testo;
  }

  function invia(block, dati) {
    if (block._inCorso) { return; }
    block._inCorso = true;
    if (block.dataset.meeting) { dati.append('meeting_id', block.dataset.meeting); }
    fetch(block.dataset.url, {
      method: 'POST', body: dati, credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, reason: 'Risposta non valida (' + r.status + ').' }; });
    }).then(function (j) {
      if (j.ok) { block.innerHTML = j.html; } else { errore(block, j.reason || 'Operazione non riuscita.'); }
    }).catch(function () {
      errore(block, 'Connessione non riuscita: riprova.');
    }).then(function () { block._inCorso = false; });
  }

  document.addEventListener('click', function (e) {
    var block = e.target.closest && e.target.closest('[data-tp-block]');
    if (!block) { return; }
    var row = e.target.closest('[data-tp-row]');
    if (!row) { return; }
    if (e.target.closest('[data-tp-apri]')) {
      var form = row.querySelector('[data-tp-form]');
      if (form) {
        form.hidden = !form.hidden;
        var primo = form.querySelector('select, input');
        if (!form.hidden && primo) { primo.focus(); }
      }
      return;
    }
    var btn = e.target.closest('[data-tp-action]');
    if (!btn) { return; }
    e.preventDefault();
    errore(block, '');
    var dati = new FormData();
    dati.append('tappa', row.getAttribute('data-tp-row'));
    dati.append('action', btn.getAttribute('data-tp-action'));
    Object.keys(CAMPI).forEach(function (nome) {
      var campo = row.querySelector('[data-tp="' + nome + '"]');
      if (campo) { dati.append(CAMPI[nome], campo.value); }
    });
    invia(block, dati);
  });

  /* Invio nei campi della tappa salva, senza inviare il form che la contiene. */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || !e.target.closest) { return; }
    var form = e.target.closest('[data-tp-form]');
    if (!form) { return; }
    e.preventDefault();
    var salva = form.querySelector('[data-tp-action="assegna"]');
    if (salva) { salva.click(); }
  });
})();
