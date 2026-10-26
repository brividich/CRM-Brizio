/* Finestra di conferma del portale, al posto di window.confirm().
 * - nel markup: data-hub-confirm="Eliminare X? Spiegazione." su un <form>, sul
 *   suo pulsante di invio, su un link o su un pulsante d'azione (facoltativi
 *   data-hub-confirm-ok="Etichetta" e data-hub-confirm-tone="danger|primary");
 * - hx-confirm="..." di HTMX apre la stessa finestra;
 * - da script: hubConfirm(testo, {ok, tone}).then(function (si) { ... }).
 * La prima frase che finisce con «?» fa da titolo, il resto da spiegazione.
 * Va caricato nel <head>: ascolta gli invii in fase di cattura sul documento,
 * quindi vale anche per i frammenti arrivati con HTMX. Senza <dialog> ripiega
 * sulla finestra del browser. */
(function () {
  if (window.hubConfirm) return;

  var VIA_LIBERA = '__hubConfirmOk';
  var VERBI = {
    eliminare: 'Elimina', rimuovere: 'Rimuovi', togliere: 'Togli', scollegare: 'Scollega',
    disattivare: 'Disattiva', riattivare: 'Riattiva', annullare: 'Sì, annulla', chiudere: 'Chiudi',
    applicare: 'Applica', generare: 'Genera', iscrivere: 'Iscrivi', dividere: 'Dividi',
    riprendere: 'Riprendi', registrare: 'Registra', avviare: 'Avvia', unire: 'Unisci',
    ripristinare: 'Ripristina', rimettere: 'Rimetti in forza', rendere: 'Rendi anonimi',
    confermare: 'Conferma', scartare: 'Scarta', cancellare: 'Cancella', stoppare: 'Ferma',
    segnare: 'Segna', inviare: 'Invia', collegare: 'Collega', sostituire: 'Sostituisci',
    riportare: 'Riporta', rigenerare: 'Rigenera', rifiutare: 'Rifiuta', riaprire: 'Riapri',
    pubblicare: 'Pubblica', eseguire: 'Esegui', convertire: 'Converti', archiviare: 'Archivia',
    approvare: 'Approva', abilitare: 'Abilita', disabilitare: 'Disabilita', copiare: 'Copia', riavviare: 'Riavvia',
    creare: 'Crea', spostare: 'Sposta', inserire: 'Inserisci', reimpostare: 'Reimposta',
    svuotare: 'Svuota', ottimizzare: 'Ottimizza', interrogare: 'Interroga'
  };
  var PERICOLO = /^(eliminare|rimuovere|togliere|scollegare|disattivare|disabilitare|annullare|scartare|cancellare|svuotare|rendere anonim|attenzione)/i;
  var dialog = null;
  var inAttesa = null;

  function opzioniDa(el) {
    return {
      ok: el.getAttribute('data-hub-confirm-ok') || '',
      tone: el.getAttribute('data-hub-confirm-tone') || ''
    };
  }

  function costruisci() {
    dialog = document.createElement('dialog');
    dialog.className = 'hub-confirm';
    dialog.setAttribute('aria-labelledby', 'hub-confirm-titolo');
    dialog.setAttribute('aria-describedby', 'hub-confirm-testo');
    dialog.innerHTML =
      '<div class="hub-confirm-box">' +
        '<p class="hub-confirm-titolo" id="hub-confirm-titolo"></p>' +
        '<p class="hub-confirm-testo" id="hub-confirm-testo"></p>' +
        '<div class="hub-confirm-azioni">' +
          '<button type="button" class="hub-confirm-no" data-esito="">Annulla</button>' +
          '<button type="button" class="hub-confirm-si" data-esito="si">Conferma</button>' +
        '</div>' +
      '</div>';
    dialog.addEventListener('click', function (ev) {
      var b = ev.target.closest('[data-esito]');
      if (b) dialog.close(b.getAttribute('data-esito'));
      else if (ev.target === dialog) dialog.close('');   // clic fuori dal riquadro
    });
    dialog.addEventListener('close', function () {
      var fine = inAttesa;
      inAttesa = null;
      if (fine) fine(dialog.returnValue === 'si');
    });
    document.body.appendChild(dialog);
  }

  function hubConfirm(testo, opz) {
    testo = String(testo || '');
    opz = opz || {};
    if (typeof HTMLDialogElement !== 'function' || !document.body) {
      return Promise.resolve(window.confirm(testo));
    }
    if (!dialog || !dialog.isConnected) costruisci();   // anche se uno swap l'ha tolta dalla pagina
    if (dialog.open) return Promise.resolve(false);       // una domanda alla volta

    var m = /^([\s\S]*?\?)\s+([\s\S]+)$/.exec(testo);
    var verbo = (testo.match(/^\s*([a-zà-ù]+)/i) || [])[1] || '';
    var okLabel = opz.ok || VERBI[verbo.toLowerCase()] || 'Conferma';
    var pericolo = opz.tone ? opz.tone === 'danger' : PERICOLO.test(testo.trim());

    dialog.querySelector('.hub-confirm-titolo').textContent = m ? m[1] : testo;
    var spiega = dialog.querySelector('.hub-confirm-testo');
    spiega.textContent = m ? m[2] : '';
    spiega.hidden = !m;
    var si = dialog.querySelector('.hub-confirm-si');
    var no = dialog.querySelector('.hub-confirm-no');
    si.textContent = okLabel;
    no.textContent = /^sì, annulla/i.test(okLabel) ? 'Indietro' : 'Annulla';
    dialog.classList.toggle('hub-confirm-pericolo', pericolo);

    return new Promise(function (resolve) {
      inAttesa = resolve;
      dialog.returnValue = '';
      dialog.showModal();
      // Sulle azioni distruttive Invio non deve confermare per sbaglio.
      (pericolo ? no : si).focus();
    });
  }

  function reinvia(form, pulsante) {
    form[VIA_LIBERA] = true;
    setTimeout(function () { form[VIA_LIBERA] = false; }, 0);   // invio bloccato dalla validazione
    if (form.requestSubmit) {
      if (pulsante && pulsante.form === form) form.requestSubmit(pulsante);
      else form.requestSubmit();
      return;
    }
    if (pulsante && pulsante.name) {
      var h = document.createElement('input');
      h.type = 'hidden';
      h.name = pulsante.name;
      h.value = pulsante.value;
      form.appendChild(h);
    }
    form.submit();
  }

  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (!(form instanceof HTMLFormElement)) return;
    var pulsante = ev.submitter || null;
    var fonte = pulsante && pulsante.hasAttribute('data-hub-confirm') ? pulsante
      : (form.hasAttribute('data-hub-confirm') ? form : null);
    if (!fonte) return;
    if (form[VIA_LIBERA]) { form[VIA_LIBERA] = false; return; }
    ev.preventDefault();
    ev.stopImmediatePropagation();
    hubConfirm(fonte.getAttribute('data-hub-confirm'), opzioniDa(fonte)).then(function (si) {
      if (si) reinvia(form, pulsante);
    });
  }, true);

  // Link e pulsanti che non inviano un form (azioni da script): si ferma il clic,
  // si chiede e, se confermato, si ripete il clic con il via libera.
  document.addEventListener('click', function (ev) {
    var el = ev.target.closest && ev.target.closest('[data-hub-confirm]');
    if (!el || el instanceof HTMLFormElement) return;
    if ((el.type === 'submit' || el.type === 'image') && el.form) return;   // ci pensa l'ascolto dell'invio
    if (!/^(A|BUTTON|INPUT)$/.test(el.tagName)) return;
    if (el[VIA_LIBERA]) { el[VIA_LIBERA] = false; return; }
    ev.preventDefault();
    ev.stopImmediatePropagation();
    hubConfirm(el.getAttribute('data-hub-confirm'), opzioniDa(el)).then(function (si) {
      if (!si) return;
      el[VIA_LIBERA] = true;
      setTimeout(function () { el[VIA_LIBERA] = false; }, 0);
      el.click();
    });
  }, true);

  // hx-confirm di HTMX: stessa finestra al posto di quella del browser.
  document.addEventListener('htmx:confirm', function (ev) {
    var d = ev.detail || {};
    if (!d.question || typeof d.issueRequest !== 'function') return;
    ev.preventDefault();
    hubConfirm(d.question, d.elt ? opzioniDa(d.elt) : {}).then(function (si) {
      if (si) d.issueRequest(true);
    });
  });

  window.hubConfirm = hubConfirm;
})();
