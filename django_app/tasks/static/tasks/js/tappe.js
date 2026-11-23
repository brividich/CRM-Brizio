/* Percorso del kickoff (_tappe.html): è l'indice delle tappe, senza campi propri.
 * «Assegna» crea l'attività del tipo giusto e la apre nel pannello laterale, già sul
 * collegamento che la tappa si aspetta; «Non serve» / «Serve» segnano la tappa.
 * Quando nel pannello cambia un collegamento (evento kc:cambiato) l'indice si rilegge. */
(function () {
  'use strict';
  if (window.__tappeKickoff) { return; }
  window.__tappeKickoff = true;

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

  /* L'attività appena nata si apre nel pannello laterale; senza pannello, nella sua pagina. */
  function apriAttivita(block, taskId, url) {
    var link = block.querySelector('[data-tp-task="' + taskId + '"]');
    if (link && window.HubBulkPannello && window.HubBulkPannello.open) {
      var normale = link.getAttribute('data-preview');
      link.setAttribute('data-preview', url);
      window.HubBulkPannello.open(link);
      link.setAttribute('data-preview', normale);
    } else {
      window.location.href = url;
    }
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
      if (!j.ok) { errore(block, j.reason || 'Operazione non riuscita.'); return; }
      block.innerHTML = j.html;
      if (j.messaggio && window.hubFlash) { window.hubFlash.show([{ level: 'success', text: j.messaggio }]); }
      if (j.task_id && j.apri) { apriAttivita(block, j.task_id, j.apri); }
    }).catch(function () {
      errore(block, 'Connessione non riuscita: riprova.');
    }).then(function () { block._inCorso = false; });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-tp-action]');
    if (!btn) { return; }
    var block = btn.closest('[data-tp-block]');
    var row = btn.closest('[data-tp-row]');
    if (!block || !row) { return; }
    e.preventDefault();
    errore(block, '');
    var dati = new FormData();
    dati.append('tappa', row.getAttribute('data-tp-row'));
    dati.append('action', btn.getAttribute('data-tp-action'));
    invia(block, dati);
  });

  /* Filtri del Percorso: tutte, le mie, in ritardo, da assegnare (solo a video). */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-tp-filtro]');
    if (!btn) { return; }
    var block = btn.closest('[data-tp-block]');
    var filtro = btn.getAttribute('data-tp-filtro');
    block.querySelectorAll('[data-tp-filtro]').forEach(function (b) { b.classList.toggle('is-on', b === btn); });
    block.querySelectorAll('[data-tp-row]').forEach(function (r) {
      var ok = !filtro || (filtro === 'mie' && r.dataset.mie === '1') || (filtro === 'ritardo' && r.dataset.stato === 'ritardo') ||
        (filtro === 'vuota' && r.dataset.stato === 'vuota');
      r.hidden = !ok;
    });
  });

  /* Un collegamento cambiato nel pannello: l'indice (stato «Manca: …» e voci sotto la tappa) si rilegge. */
  var inAttesa = null;
  document.addEventListener('kc:cambiato', function () {
    var block = document.querySelector('[data-tp-block]');
    if (!block) { return; }
    clearTimeout(inAttesa);
    inAttesa = setTimeout(function () {
      fetch(block.dataset.url + (block.dataset.meeting ? '?meeting_id=' + encodeURIComponent(block.dataset.meeting) : ''), { credentials: 'same-origin', headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); })
        .then(function (j) { if (j.ok && j.html) { block.innerHTML = j.html; } })
        .catch(function () {});
    }, 250);
  });
})();
