/* «Programmi e FAI» della commessa: registro costruito dalle attività.

   Chi ne ha il diritto agisce anche da qui: cambia la fase di un programma, toglie un
   collegamento, lega a un'attività una voce rimasta senza, apre un'attività per
   aggiungerle un collegamento. Ogni comando passa da tasks:collegamenti_registro e il
   server rimanda la tabella rifatta. I filtri per tipo sono solo a video. */
(function () {
  'use strict';
  if (window.__rcRegistro) { return; }
  window.__rcRegistro = true;

  function dici(testo, errore) {
    if (window.hubFlash && testo) { window.hubFlash.show([{ level: errore ? 'error' : 'success', text: testo }]); }
  }
  function blocco(el) { return el.closest ? el.closest('[data-rc]') : null; }

  function filtra(root) {
    var attivo = root.querySelector('[data-rc-filtro][aria-pressed="true"]');
    var tipi = attivo ? attivo.getAttribute('data-rc-tipi').split(' ') : null;
    var viste = 0, righe = root.querySelectorAll('[data-rc-riga]');
    righe.forEach(function (r) {
      var ok = !tipi || tipi.indexOf(r.getAttribute('data-rc-tipo')) >= 0;
      r.hidden = !ok;
      if (ok) { viste += 1; }
    });
    var nessuna = root.querySelector('[data-rc-nessuna]');
    if (nessuna) { nessuna.hidden = !(righe.length && !viste); }
  }

  function ridisegna(root, html) {
    var attivo = root.querySelector('[data-rc-filtro][aria-pressed="true"]');
    var codice = attivo ? attivo.getAttribute('data-rc-filtro') : '';
    root.innerHTML = html;
    root.querySelectorAll('[data-rc-filtro]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-rc-filtro') === codice ? 'true' : 'false');
    });
    if (!root.querySelector('[data-rc-filtro][aria-pressed="true"]')) {
      var primo = root.querySelector('[data-rc-filtro]');
      if (primo) { primo.setAttribute('aria-pressed', 'true'); }
    }
    filtra(root);
  }

  function invia(root, dati) {
    return fetch(root.getAttribute('data-url'), {
      method: 'POST',
      headers: {
        'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': root.getAttribute('data-csrf'),
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      credentials: 'same-origin',
      body: new URLSearchParams(dati).toString()
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { j.ok = r.ok && j.ok !== false; return j; });
    }).then(function (j) {
      if (j.html) { ridisegna(root, j.html); }
      if (j.ok) { dici(j.messaggio); } else { dici(j.reason || j.error || 'Modifica non salvata.', true); }
      return j;
    }).catch(function () {
      dici('Non riesco a salvare: controlla la connessione e riprova.', true);
      return { ok: false };
    });
  }

  function rileggi(root) {
    fetch(root.getAttribute('data-url'), { credentials: 'same-origin', headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (j.ok && j.html) { ridisegna(root, j.html); } })
      .catch(function () {});
  }

  /* Apre l'attività nel pannello laterale (o nella sua pagina, se il pannello non c'è). */
  function apri(el, url) {
    if (window.HubBulkPannello && window.HubBulkPannello.open) {
      el.setAttribute('data-preview', url);
      window.HubBulkPannello.open(el);
      el.removeAttribute('data-preview');
    } else {
      window.location.href = url;
    }
  }

  document.addEventListener('click', function (e) {
    var root = blocco(e.target), b;
    if (!root) { return; }
    if ((b = e.target.closest('[data-rc-filtro]'))) {
      root.querySelectorAll('[data-rc-filtro]').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      filtra(root);
      return;
    }
    if ((b = e.target.closest('[data-rc-nuovo]'))) {
      var box = root.querySelector('[data-rc-nuovo-box]');
      box.hidden = !box.hidden;
      b.setAttribute('aria-expanded', box.hidden ? 'false' : 'true');
      if (!box.hidden) { box.querySelector('select').focus(); }
      return;
    }
    if ((b = e.target.closest('[data-rc-togli]'))) {
      var riga = b.closest('[data-rc-riga]');
      b.disabled = true;
      invia(root, { action: 'togli', task: riga.getAttribute('data-rc-task'), chiave: riga.getAttribute('data-rc-riga') });
      return;
    }
    if ((b = e.target.closest('[data-rc-elimina]'))) {
      // Due clic: il primo chiede conferma sul pulsante stesso.
      if (!b.hasAttribute('data-rc-sicuro')) {
        b.setAttribute('data-rc-sicuro', '1');
        b.textContent = 'Conferma';
        setTimeout(function () { if (b.isConnected) { b.removeAttribute('data-rc-sicuro'); b.textContent = 'Elimina'; } }, 4000);
        return;
      }
      b.disabled = true;
      invia(root, { action: 'elimina', chiave: b.closest('[data-rc-riga]').getAttribute('data-rc-riga') });
      return;
    }
    if ((b = e.target.closest('[data-rc-fai]'))) {
      b.disabled = true;
      invia(root, { action: 'fai_non_richiesto', valore: b.getAttribute('data-rc-fai') });
    }
  });

  document.addEventListener('change', function (e) {
    var el = e.target, root = blocco(el);
    if (!root || !el.matches || !el.value) { return; }
    var riga = el.closest('[data-rc-riga]');
    if (el.matches('[data-rc-fase]')) {
      el.disabled = true;
      invia(root, { action: 'fase', chiave: riga.getAttribute('data-rc-riga'), valore: el.value })
        .then(function (j) { if (!j.ok && el.isConnected) { el.disabled = false; el.value = ''; } });
    } else if (el.matches('[data-rc-orfano]')) {
      el.disabled = true;
      invia(root, { action: 'orfano', chiave: riga.getAttribute('data-rc-riga'), task: el.value })
        .then(function (j) { if (!j.ok && el.isConnected) { el.disabled = false; el.value = ''; } });
    } else if (el.matches('[data-rc-attivita]')) {
      // «+ Collegamento»: scelta l'attività, si apre il suo riquadro «Collegamenti» nel pannello.
      var url = el.value;
      el.value = '';
      apri(el, url);
    }
  });

  /* Un collegamento cambiato nel pannello dell'attività: il registro si rilegge. */
  var inAttesa = null;
  document.addEventListener('kc:cambiato', function () {
    var root = document.querySelector('[data-rc]');
    if (!root) { return; }
    clearTimeout(inAttesa);
    inAttesa = setTimeout(function () { rileggi(root); }, 250);
  });

  function avvia() { document.querySelectorAll('[data-rc]').forEach(filtra); }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', avvia); } else { avvia(); }
})();
