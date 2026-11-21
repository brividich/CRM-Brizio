/* Pannello attività della commessa: stato e scadenza si cambiano sul posto.

   Ogni modifica passa dagli stessi indirizzi della scheda e di «Le mie attività
   KICK-OFF» (stesse regole e stessi permessi, decide il server). Dopo il
   salvataggio la pagina rilegge se stessa e aggiorna numeri, linea del tempo ed
   elenco senza ricaricare: quello che si vede è sempre lo stato salvato. */
(function () {
  'use strict';

  var pannello = document.querySelector('[data-ka-pannello]');
  if (!pannello) return;
  var esito = document.querySelector('[data-ka-esito]');
  var timer = null;

  function dici(testo, errore) {
    if (!esito) return;
    esito.textContent = testo;
    esito.classList.toggle('is-ko', !!errore);
    esito.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(function () { esito.hidden = true; }, errore ? 9000 : 4000);
  }

  function invia(url, dati) {
    var corpo = new URLSearchParams(dati);
    return fetch(url, {
      method: 'POST',
      headers: {
        'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': pannello.getAttribute('data-csrf'),
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      credentials: 'same-origin',
      body: corpo.toString()
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        return { ok: r.ok && j.ok !== false, messaggio: j.message || j.messaggio || j.reason || '' };
      });
    });
  }

  /* Rilegge la pagina e sostituisce solo le zone vive: numeri, striscia, righe. */
  function rileggi() {
    return fetch(window.location.href, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(); })
      .then(function (html) {
        var nuovo = new DOMParser().parseFromString(html, 'text/html');
        document.querySelectorAll('[data-ka-live]').forEach(function (zona) {
          var fresca = nuovo.querySelector('[data-ka-live="' + zona.getAttribute('data-ka-live') + '"]');
          if (!fresca) return;
          zona.innerHTML = fresca.innerHTML;
          zona.className = fresca.className; // es. la striscia che compare con la prima data
        });
      })
      .catch(function () { window.location.reload(); });
  }

  function salva(controllo, url, dati, fallback) {
    controllo.disabled = true;
    invia(url, dati).then(function (res) {
      if (res.ok) dici(res.messaggio || fallback);
      else dici(res.messaggio || 'Modifica non salvata.', true);
      return rileggi();
    }).catch(function () {
      dici('Non riesco a salvare: controlla la connessione e riprova.', true);
      controllo.disabled = false;
    });
  }

  document.addEventListener('change', function (e) {
    var el = e.target;
    if (el.matches && el.matches('[data-ka-stato]')) {
      salva(el, el.getAttribute('data-url'), { action: el.value }, 'Stato aggiornato.');
    } else if (el.matches && el.matches('[data-ka-fine]')) {
      if (el.value === el.getAttribute('data-prima')) { chiudiMotivo(el); return; }
      if (el.hasAttribute('data-motivo')) { chiediMotivo(el); return; }
      salva(el, el.getAttribute('data-url'), { azione: 'date', inizio: el.getAttribute('data-inizio') || '', fine: el.value }, 'Scadenza aggiornata.');
    }
  });

  /* Chi non sposta subito chiede al capocommessa: sotto la data compare il motivo. */
  function chiudiMotivo(el) {
    var box = el.parentNode.querySelector('.ka-motivo');
    if (box) box.remove();
  }
  function chiediMotivo(el) {
    if (el.parentNode.querySelector('.ka-motivo')) { el.parentNode.querySelector('.ka-motivo input').focus(); return; }
    var box = document.createElement('div');
    box.className = 'ka-motivo';
    var motivo = document.createElement('input');
    motivo.className = 'input'; motivo.type = 'text'; motivo.maxLength = 500;
    motivo.placeholder = 'Motivo per il capocommessa'; motivo.setAttribute('aria-label', 'Motivo dello spostamento');
    var chiedi = document.createElement('button');
    chiedi.type = 'button'; chiedi.className = 'btn btn-sm'; chiedi.textContent = 'Chiedi';
    var invio = function () {
      if (!motivo.value.trim()) { motivo.focus(); dici('Scrivi il motivo dello spostamento: lo legge il capocommessa che decide.', true); return; }
      chiedi.disabled = true;
      salva(el, el.getAttribute('data-url'), {
        azione: 'date', inizio: el.getAttribute('data-inizio') || '', fine: el.value, motivo: motivo.value
      }, 'Richiesta inviata al capocommessa.');
    };
    chiedi.addEventListener('click', invio);
    motivo.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); invio(); } });
    box.appendChild(motivo); box.appendChild(chiedi);
    el.parentNode.appendChild(box);
    motivo.focus();
  }

  // Riga cliccabile, tranne sui controlli.
  document.addEventListener('click', function (e) {
    var riga = e.target.closest && e.target.closest('.tl-row-clickable');
    if (!riga || e.target.closest('a, input, select, button, label')) return;
    var href = riga.getAttribute('data-href');
    if (href) window.location.href = href;
  });
})();
