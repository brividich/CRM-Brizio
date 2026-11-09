/* Percorso del kickoff (_tappe.html): assegna una tappa o segnala che non serve, senza ricaricare.
 * Mentre si compila: «Entro il» non può precedere l'inizio, e sotto la riga compaiono subito
 * le assenze del responsabile e, per la macchina, abilitati e impegni nel periodo. */
(function () {
  'use strict';
  if (window.__tappeKickoff) { return; }
  window.__tappeKickoff = true;

  var CAMPI = { owner: 'assigned_to', start: 'start_date', due: 'due_date', asset: 'asset', testo: 'testo' };

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

  function campi(row) {
    var valori = { tappa: row.getAttribute('data-tp-row') };
    Object.keys(CAMPI).forEach(function (nome) {
      var campo = row.querySelector('[data-tp="' + nome + '"]');
      if (campo) { valori[CAMPI[nome]] = campo.value; }
    });
    var outlook = row.querySelector('[data-tp="outlook"]');
    if (outlook && outlook.checked) { valori.outlook = '1'; }
    return valori;
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

  /* Anteprima: un controllo per volta, l'ultimo vince. */
  function anteprima(block, row) {
    var box = row.querySelector('[data-tp-anteprima]');
    if (!box || !block.dataset.anteprima) { return; }
    var valori = campi(row);
    if (!valori.assigned_to && !valori.asset) { box.innerHTML = ''; return; }
    var params = new URLSearchParams(valori);
    var giro = (row._giro || 0) + 1;
    row._giro = giro;
    box.classList.add('is-loading');
    fetch(block.dataset.anteprima + '?' + params.toString(), {
      credentials: 'same-origin', headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (row._giro === giro) { box.innerHTML = j.ok ? j.html : ''; }
    }).catch(function () {
      if (row._giro === giro) { box.innerHTML = ''; }
    }).then(function () { box.classList.remove('is-loading'); });
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
    var valori = campi(row);
    Object.keys(valori).forEach(function (k) { dati.append(k, valori[k]); });
    dati.append('action', btn.getAttribute('data-tp-action'));
    invia(block, dati);
  });

  document.addEventListener('change', function (e) {
    var row = e.target.closest && e.target.closest('[data-tp-form]') && e.target.closest('[data-tp-row]');
    if (!row) { return; }
    var block = row.closest('[data-tp-block]');
    var nome = e.target.getAttribute('data-tp');
    if (nome === 'start') {
      var due = row.querySelector('[data-tp="due"]');
      if (due) {
        due.min = e.target.value || '';
        if (due.value && e.target.value && due.value < e.target.value) { due.value = e.target.value; }
      }
    }
    if (nome !== 'outlook' && nome !== 'testo') { anteprima(block, row); }
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
