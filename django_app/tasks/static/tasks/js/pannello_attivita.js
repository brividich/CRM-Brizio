/* Pannello attività della commessa: stato e scadenza si cambiano sul posto.

   Ogni modifica passa dagli stessi indirizzi della scheda e di «Le mie attività
   KICK-OFF» (stesse regole e stessi permessi, decide il server). Dopo il
   salvataggio la pagina rilegge se stessa e aggiorna numeri, linea del tempo ed
   elenco senza ricaricare: quello che si vede è sempre lo stato salvato. */
(function () {
  'use strict';

  var pannello = document.querySelector('[data-ka-pannello]');
  if (!pannello || window.__kaPannello) return;
  window.__kaPannello = true;
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
        return { ok: r.ok && j.ok !== false, messaggio: j.message || j.messaggio || j.reason || j.error || '' };
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

  /* Chi non sposta subito chiede al capocommessa: sotto la data compare il motivo
     (facoltativo: aiuta chi decide, ma la richiesta parte anche senza). */
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
    motivo.placeholder = 'Motivo per il capocommessa (facoltativo)'; motivo.setAttribute('aria-label', 'Motivo dello spostamento');
    var chiedi = document.createElement('button');
    chiedi.type = 'button'; chiedi.className = 'btn btn-sm'; chiedi.textContent = 'Chiedi';
    var invio = function () {
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

  /* Nota dalla riga: si apre un riquadro sotto il titolo, «Salva la nota» la manda a task_nota. */
  document.addEventListener('click', function (e) {
    var apri = e.target.closest && e.target.closest('[data-ka-nota-apri]');
    if (!apri) return;
    e.preventDefault();
    var cella = apri.closest('td');
    var aperta = cella.querySelector('.ka-nota-riga');
    if (aperta) { aperta.remove(); return; }
    var box = document.createElement('div');
    box.className = 'ka-nota-riga';
    var testo = document.createElement('textarea');
    testo.className = 'input'; testo.rows = 3; testo.maxLength = 4000;
    testo.value = apri.getAttribute('data-nota') || '';
    testo.placeholder = "Cosa deve sapere chi fa l'attività";
    testo.setAttribute('aria-label', "Nota dell'attività");
    var salvaBtn = document.createElement('button');
    salvaBtn.type = 'button'; salvaBtn.className = 'btn btn-sm'; salvaBtn.textContent = 'Salva la nota';
    var annulla = document.createElement('button');
    annulla.type = 'button'; annulla.className = 'btn btn-secondary btn-sm'; annulla.textContent = 'Annulla';
    annulla.addEventListener('click', function () { box.remove(); });
    salvaBtn.addEventListener('click', function () {
      salva(salvaBtn, apri.getAttribute('data-url'), { nota: testo.value }, 'Nota salvata.');
    });
    box.appendChild(testo); box.appendChild(salvaBtn); box.appendChild(annulla);
    apri.closest('.ka-riga-extra').after(box);
    testo.focus();
  });

  /* Collegamento dalla riga: «Collega» sulla riga che viene dopo, poi clic (o trascinamento)
     sulla riga che viene prima. Stessa interazione del passo «Attività e incontro». */
  var aiuto = document.querySelector('[data-ka-colleg-aiuto]');
  var origine = null;
  function fineScelta() {
    if (origine) origine.classList.remove('is-origine');
    origine = null;
    document.documentElement.classList.remove('ka-sceglie');
    if (aiuto) aiuto.hidden = true;
    document.querySelectorAll('[data-ka-riga].is-bersaglio').forEach(function (r) { r.classList.remove('is-bersaglio'); });
  }
  function iniziaScelta(riga) {
    if (origine === riga) { fineScelta(); return; }
    fineScelta();
    origine = riga;
    riga.classList.add('is-origine');
    document.documentElement.classList.add('ka-sceglie');
    if (aiuto) aiuto.hidden = false;
  }
  function collegaA(bersaglio) {
    if (!origine || bersaglio === origine) return;
    var btn = origine.querySelector('[data-ka-colleg-riga]');
    if (bersaglio.getAttribute('data-progetto') !== origine.getAttribute('data-progetto')) {
      dici('Si collegano solo attività della stessa commessa.', true);
      return;
    }
    var dati = { predecessor_id: bersaglio.getAttribute('data-ka-riga'), successor_id: origine.getAttribute('data-ka-riga') };
    fineScelta();
    salva(btn, btn.getAttribute('data-url'), dati, 'Attività collegate.');
  }
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-ka-colleg-riga]');
    if (btn) { e.preventDefault(); e.stopPropagation(); iniziaScelta(btn.closest('[data-ka-riga]')); return; }
    if (e.target.closest && e.target.closest('[data-ka-colleg-annulla]')) { fineScelta(); return; }
    var scollega = e.target.closest && e.target.closest('[data-ka-scollega-riga]');
    if (scollega) { e.preventDefault(); e.stopPropagation(); salva(scollega, scollega.getAttribute('data-url'), {}, 'Collegamento tolto.'); return; }
    if (!origine) return;
    var riga = e.target.closest && e.target.closest('[data-ka-riga]');
    if (riga) { e.preventDefault(); e.stopPropagation(); collegaA(riga); }
  }, true);
  document.addEventListener('dragstart', function (e) {
    var btn = e.target.closest && e.target.closest('[data-ka-colleg-riga]');
    if (!btn) return;
    iniziaScelta(btn.closest('[data-ka-riga]'));
    e.dataTransfer.effectAllowed = 'link';
    try { e.dataTransfer.setData('text/plain', 'collega'); } catch (err) { /* vecchi browser */ }
  });
  document.addEventListener('dragover', function (e) {
    var riga = origine && e.target.closest && e.target.closest('[data-ka-riga]');
    if (!riga || riga === origine) return;
    e.preventDefault();
    riga.classList.add('is-bersaglio');
  });
  document.addEventListener('dragleave', function (e) {
    var riga = e.target.closest && e.target.closest('[data-ka-riga]');
    if (riga) riga.classList.remove('is-bersaglio');
  });
  document.addEventListener('drop', function (e) {
    var riga = origine && e.target.closest && e.target.closest('[data-ka-riga]');
    if (!riga) return;
    e.preventDefault();
    collegaA(riga);
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && origine) fineScelta(); });

  // Riga cliccabile, tranne sui controlli.
  document.addEventListener('click', function (e) {
    var riga = e.target.closest && e.target.closest('.tl-row-clickable');
    if (!riga || origine || e.target.closest('a, input, select, button, label, textarea, form')) return;
    var href = riga.getAttribute('data-href');
    if (href) window.location.href = href;
  });
})();
