/* «Le mie attività»: filtri, ricerca, due viste, gruppi richiudibili, chiusura dalla riga. */
(function () {
  'use strict';
  var root = document.querySelector('[data-ma]');
  if (!root) { return; }

  var stato = { urg: '', mod: '', q: '', view: 'moduli' };
  var CHIAVE = 'ma_preferenze_v1';
  var chiusi = {};
  try {
    var salvate = JSON.parse(localStorage.getItem(CHIAVE) || '{}');
    if (salvate.view === 'urgenza') { stato.view = 'urgenza'; }
    chiusi = salvate.chiusi || {};
  } catch (e) { /* senza memoria si riparte dai valori normali */ }

  function salva() {
    try { localStorage.setItem(CHIAVE, JSON.stringify({ view: stato.view, chiusi: chiusi })); } catch (e) { /* non serve altro */ }
  }

  function tutti(sel, base) { return Array.prototype.slice.call((base || root).querySelectorAll(sel)); }
  var griglia = root.querySelector('[data-ma-grid]');
  var piatta = root.querySelector('[data-ma-flat]');
  var listaPiatta = root.querySelector('[data-ma-flat-list]');
  var vuoto = root.querySelector('[data-ma-none]');

  /* La vista per urgenza è fatta di copie delle righe, ordinate per scadenza. */
  function preparaPiatta() {
    if (!listaPiatta || listaPiatta.children.length) { return; }
    tutti('.ma-row', griglia)
      .sort(function (a, b) {
        return (a.dataset.rank - b.dataset.rank) || (a.dataset.due < b.dataset.due ? -1 : a.dataset.due > b.dataset.due ? 1 : 0);
      })
      .forEach(function (riga) { listaPiatta.appendChild(riga.cloneNode(true)); });
  }

  function corrisponde(riga) {
    if (stato.urg && riga.dataset.urg !== stato.urg) { return false; }
    if (stato.mod && riga.dataset.mod !== stato.mod) { return false; }
    return !stato.q || (riga.dataset.text || '').toLowerCase().indexOf(stato.q) >= 0;
  }

  function applica() {
    if (!griglia) { return; }
    var perUrgenza = stato.view === 'urgenza';
    if (perUrgenza) { preparaPiatta(); }
    griglia.hidden = perUrgenza;
    griglia.style.display = perUrgenza ? 'none' : '';
    piatta.hidden = !perUrgenza;

    var visibili = 0;
    tutti('.ma-row', perUrgenza ? piatta : griglia).forEach(function (riga) {
      var ok = corrisponde(riga);
      riga.hidden = !ok;
      riga.style.display = ok ? '' : 'none';
      if (ok) { visibili += 1; }
    });
    tutti('[data-ma-group]', griglia).forEach(function (gruppo) {
      var conRighe = tutti('.ma-row', gruppo).some(function (r) { return !r.hidden; });
      gruppo.style.display = conRighe ? '' : 'none';
      gruppo.classList.toggle('is-closed', !!chiusi[gruppo.dataset.maGroup] && !stato.q);
      var bottone = gruppo.querySelector('[data-ma-toggle]');
      bottone.setAttribute('aria-expanded', gruppo.classList.contains('is-closed') ? 'false' : 'true');
    });
    if (vuoto) { vuoto.hidden = visibili > 0; }
    if (perUrgenza) { piatta.style.display = visibili ? '' : 'none'; } else { piatta.style.display = 'none'; }

    tutti('[data-ma-urg]').forEach(function (b) { b.classList.toggle('is-on', b.dataset.maUrg === stato.urg); });
    tutti('[data-ma-mod]').forEach(function (b) { b.classList.toggle('is-on', b.dataset.maMod === stato.mod); });
    tutti('[data-ma-view]').forEach(function (b) { b.classList.toggle('is-on', b.dataset.maView === stato.view); });
  }

  function csrf() {
    var input = root.querySelector('[name=csrfmiddlewaretoken]');
    return input ? input.value : '';
  }

  function invia(url, azione) {
    var dati = new FormData();
    dati.append('action', azione);
    return fetch(url, {
      method: 'POST',
      body: dati,
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) { return r.json(); });
  }

  function aggiustaConteggi(riga, delta) {
    var cambia = function (el) { el.textContent = Math.max(0, parseInt(el.textContent, 10) + delta); };
    tutti('[data-ma-count="tutte"],[data-ma-tot]').forEach(cambia);
    if (riga.dataset.urg) { tutti('[data-ma-count="' + riga.dataset.urg + '"]').forEach(cambia); }
    tutti('[data-ma-modn="' + riga.dataset.mod + '"]').forEach(cambia);
  }

  function avviso(testo, annulla) {
    var box = document.querySelector('.tr-toast');
    if (!box) {
      box = document.createElement('div');
      box.className = 'tr-toast';
      box.setAttribute('role', 'status');
      document.body.appendChild(box);
    }
    box.textContent = testo;
    box.hidden = false;
    if (annulla) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'ma-toast-undo';
      b.textContent = 'Annulla';
      b.addEventListener('click', annulla);
      box.appendChild(b);
    }
    clearTimeout(box._timer);
    box._timer = setTimeout(function () { box.hidden = true; }, 7000);
  }

  function segnaFatto(bottone) {
    var riga = bottone.closest('.ma-row');
    var url = bottone.dataset.maDone;
    var chiave = riga.dataset.maRow;
    bottone.disabled = true;
    invia(url, 'done').then(function (esito) {
      if (!esito.ok) { throw new Error('rifiutato'); }
      tutti('[data-ma-row="' + chiave + '"]').forEach(function (r) { r.classList.add('is-out'); });
      aggiustaConteggi(riga, -1);
      setTimeout(function () {
        tutti('[data-ma-row="' + chiave + '"]').forEach(function (r) { r.remove(); });
        applica();
      }, 260);
      avviso(esito.message || 'Fatto.', function () {
        invia(url, 'reopen').then(function () { window.location.reload(); });
      });
    }).catch(function () {
      bottone.disabled = false;
      avviso('Non è stato possibile aggiornare la voce. Riprova.');
    });
  }

  root.addEventListener('click', function (e) {
    var t = e.target;
    var urg = t.closest('[data-ma-urg]');
    if (urg) { stato.urg = urg.dataset.maUrg; applica(); return; }
    var mod = t.closest('[data-ma-mod]');
    if (mod) { stato.mod = mod.dataset.maMod; applica(); return; }
    var vista = t.closest('[data-ma-view]');
    if (vista) { stato.view = vista.dataset.maView; salva(); applica(); return; }
    var fatto = t.closest('[data-ma-done]');
    if (fatto) { segnaFatto(fatto); return; }
    if (t.closest('[data-ma-reset]')) {
      stato.urg = ''; stato.mod = ''; stato.q = '';
      var campo = root.querySelector('[data-ma-q]');
      if (campo) { campo.value = ''; }
      applica();
      return;
    }
    var apri = t.closest('[data-ma-toggle]');
    if (apri) {
      var chiaveGruppo = apri.closest('[data-ma-group]').dataset.maGroup;
      chiusi[chiaveGruppo] = !chiusi[chiaveGruppo];
      salva();
      applica();
    }
  });

  var ricerca = root.querySelector('[data-ma-q]');
  if (ricerca) {
    ricerca.addEventListener('input', function () {
      stato.q = ricerca.value.trim().toLowerCase();
      applica();
    });
  }

  applica();
})();
