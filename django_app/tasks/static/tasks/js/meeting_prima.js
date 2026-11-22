/* Scheda incontro, fase «Prima»: l'ordine del giorno si cambia sul posto.
 *
 * «+ Punto», «Sposta su», «Sposta giù», «Togli», «Accetta» / «Rifiuta» una proposta e
 * «Aggiungi all'ordine del giorno» scrivono subito sul server; poi si rileggono solo i
 * riquadri della fase (`?riquadro=prima`), così numeri, proposte, «Dagli incontri
 * precedenti» e «Convocazione da reinviare» sono sempre quelli calcolati dal server.
 * La pagina non si ricarica; se il server non riconosce più la fase (sessione scaduta,
 * incontro non più pianificato) si ricarica per mostrare lo stato vero.
 */
(function () {
  'use strict';

  var root = document.getElementById('mprima');
  if (!root) { return; }
  var cfg = root.dataset;
  var RIQUADRI = ['prima-odg', 'prima-invio', 'prima-precedenti'];
  var occupato = false;

  function csrf() {
    var input = root.querySelector('[name=csrfmiddlewaretoken]');
    if (input) { return input.value; }
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function say(text, isError) {
    var msg = document.getElementById('prima-msg');
    if (!msg) { return; }
    msg.textContent = text || '';
    msg.classList.toggle('error', !!isError);
  }

  function post(url, data) {
    var body = new URLSearchParams();
    Object.keys(data).forEach(function (key) { body.set(key, data[key]); });
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
      body: body
    }).then(function (response) {
      return response.json().catch(function () { return { ok: false }; });
    });
  }

  /* Rilegge i riquadri dal server e li sostituisce. */
  function rileggi() {
    return fetch(cfg.frammentoUrl, {
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (response) {
      if (!response.ok) { throw new Error(response.status); }
      return response.text();
    }).then(function (html) {
      var doc = new DOMParser().parseFromString(html, 'text/html');
      var nuovi = RIQUADRI.map(function (id) { return doc.getElementById(id); });
      if (nuovi.some(function (el) { return !el; })) { throw new Error('frammento'); }
      RIQUADRI.forEach(function (id, index) {
        var attuale = document.getElementById(id);
        if (attuale) { attuale.innerHTML = nuovi[index].innerHTML; }
      });
    }).catch(function () { window.location.reload(); });
  }

  /* Un'azione alla volta: invia, poi rilegge. `dopo` rimette il fuoco dove serve. */
  function esegui(url, data, opzioni) {
    if (occupato) { return; }
    occupato = true;
    root.classList.add('is-busy');
    post(url, data).then(function (esito) {
      if (!esito.ok) {
        occupato = false;
        root.classList.remove('is-busy');
        say((opzioni && opzioni.errore && opzioni.errore(esito)) || 'Modifica non salvata. Riprova.', true);
        return null;
      }
      return rileggi().then(function () {
        occupato = false;
        root.classList.remove('is-busy');
        if (opzioni && opzioni.dopo) { opzioni.dopo(esito); }
      });
    }).catch(function () {
      occupato = false;
      root.classList.remove('is-busy');
      say('Errore di rete. Riprova.', true);
    });
  }

  function punto(el) { return el.closest('[data-item-id]'); }

  function aggiungi() {
    var campo = document.getElementById('prima-nuovo-titolo');
    if (!campo) { return; }
    var titolo = (campo.value || '').trim();
    if (!titolo) { campo.focus(); return; }
    esegui(cfg.addUrl, { titolo: titolo, source: 'scheda' }, {
      errore: function (esito) { return esito.reason === 'title_required' ? 'Serve un titolo.' : ''; },
      dopo: function () {
        var nuovo = document.getElementById('prima-nuovo-titolo');
        if (nuovo) { nuovo.focus(); }
        say('Punto aggiunto.', false);
      }
    });
  }

  function sposta(btn) {
    var riga = punto(btn);
    if (!riga) { return; }
    var id = riga.dataset.itemId;
    var verso = btn.dataset.odgSposta;
    esegui(cfg.moveUrl, { item_id: id, verso: verso }, {
      dopo: function () {
        var stessa = root.querySelector('[data-item-id="' + (window.CSS && CSS.escape ? CSS.escape(id) : id) + '"]');
        var bottone = stessa && stessa.querySelector('[data-odg-sposta="' + verso + '"]');
        if (bottone && bottone.disabled) { bottone = stessa.querySelector('[data-odg-sposta]:not([disabled])'); }
        if (bottone) { bottone.focus(); }
      }
    });
  }

  function togli(btn) {
    var riga = punto(btn);
    if (!riga) { return; }
    var domanda = 'Togliere dall\'ordine del giorno il punto «' + (riga.dataset.titolo || '') + '»?';
    var conferma = typeof window.hubConfirm === 'function'
      ? window.hubConfirm(domanda, { ok: 'Togli', tone: 'danger' })
      : Promise.resolve(window.confirm(domanda));
    conferma.then(function (si) {
      if (!si) { return; }
      esegui(cfg.delUrl, { item_id: riga.dataset.itemId, fase: 'prima' }, {
        errore: function (esito) {
          return esito.reason === 'not_removable' ? 'Su questo punto è già nato qualcosa: non si toglie.' : '';
        },
        dopo: function () { say('Punto tolto.', false); }
      });
    });
  }

  function riporta(btn) {
    esegui(cfg.carryUrl, { tipo: btn.dataset.tipo, id: btn.dataset.id }, {
      dopo: function () { say('Punto aggiunto.', false); }
    });
  }

  function decidi(btn) {
    var box = btn.closest('[data-url]');
    if (!box) { return; }
    var nota = box.querySelector('[data-proposta-nota]');
    esegui(box.dataset.url, { action: btn.dataset.propostaDecidi, nota_decisione: nota ? nota.value : '' }, {
      dopo: function (esito) { say(esito.stato === 'ACCEPTED' ? 'Proposta accettata: è un punto.' : 'Proposta rifiutata.', false); }
    });
  }

  root.addEventListener('click', function (event) {
    var el = event.target.closest('button');
    if (!el || !root.contains(el)) { return; }
    if (el.id === 'prima-nuovo-btn') { aggiungi(); }
    else if (el.hasAttribute('data-odg-sposta')) { sposta(el); }
    else if (el.hasAttribute('data-odg-togli')) { togli(el); }
    else if (el.hasAttribute('data-odg-riporta')) { riporta(el); }
    else if (el.hasAttribute('data-proposta-decidi')) { decidi(el); }
  });

  root.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter') { return; }
    if (event.target.id === 'prima-nuovo-titolo') { event.preventDefault(); aggiungi(); }
  });

  /* Un punto aggiunto da un altro riquadro della scheda (copilota) entra subito in lista. */
  document.addEventListener('ko:odg-cambiato', function () { rileggi(); });
})();
