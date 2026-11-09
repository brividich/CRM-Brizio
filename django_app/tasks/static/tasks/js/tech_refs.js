/* Programmi CAM, CMM e FAI (_tech_refs.html): riga rapida, Invio salva senza ricaricare.
 * Clic su un percorso di rete: i browser non aprono file:// da una pagina web, quindi
 * il percorso viene anche copiato, pronto da incollare in Esplora risorse. */
(function () {
  'use strict';

  function csrf() {
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input) { return input.value; }
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function avviso(testo) {
    var box = document.querySelector('.tr-toast');
    if (!box) {
      box = document.createElement('div');
      box.className = 'tr-toast';
      box.setAttribute('role', 'status');
      document.body.appendChild(box);
    }
    box.textContent = testo;
    box.hidden = false;
    clearTimeout(box._timer);
    box._timer = setTimeout(function () { box.hidden = true; }, 6000);
  }

  function copiaVecchioStile(testo) {
    var area = document.createElement('textarea');
    area.value = testo;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    area.remove();
    return ok;
  }

  function copia(testo) {
    var fine = function (ok) {
      avviso(ok
        ? 'Percorso copiato. Premi Win+E, poi Ctrl+L, Ctrl+V e Invio.'
        : 'Percorso da aprire in Esplora risorse: ' + testo);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(testo).then(function () { fine(true); }, function () { fine(copiaVecchioStile(testo)); });
    } else {
      fine(copiaVecchioStile(testo));
    }
  }

  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('[data-tr-open]');
    if (link) { copia(link.getAttribute('data-tr-open')); }
  });

  function collega(block) {
    var inCorso = false;
    var modifica = null;
    var saltaResponsabile = false;

    function f(nome) { return block.querySelector('[data-tr="' + nome + '"]'); }

    function errore(testo) {
      var err = f('err');
      if (!err) { avviso(testo); return; }
      err.textContent = testo;
      err.hidden = !testo;
    }

    function invia(url, dati, dopo) {
      if (inCorso) { return; }
      inCorso = true;
      if (block.dataset.meeting) { dati.append('meeting_id', block.dataset.meeting); }
      fetch(url, {
        method: 'POST',
        body: dati,
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' }
      }).then(function (r) {
        return r.json().catch(function () { return { ok: false, reason: 'Risposta non valida dal portale.' }; });
      }).then(function (esito) {
        inCorso = false;
        if (!esito.ok) { errore(esito.reason || esito.error || 'Salvataggio non riuscito.'); return; }
        block.innerHTML = esito.html;
        modifica = null;
        impostaResponsabile();
        if (dopo) { dopo(); }
      }).catch(function () {
        inCorso = false;
        errore('Portale non raggiungibile: riprova.');
      });
    }

    /* Il programmatore è proposto per CAM e CMM, finché non si sceglie a mano. */
    function impostaResponsabile() {
      var form = block.querySelector('[data-tr-form]');
      var owner = f('owner');
      if (!form || !owner || saltaResponsabile || modifica) { return; }
      owner.value = f('kind').value === 'FAI' ? '' : (form.dataset.defaultOwner || '');
    }

    function salva() {
      var ultimoTipo = f('kind').value;
      var ultimoResp = f('owner').value;
      var teniResp = saltaResponsabile;
      var dati = new FormData();
      dati.append('kind', ultimoTipo);
      dati.append('code', f('code').value);
      dati.append('path', f('path').value);
      dati.append('assigned_to', ultimoResp);
      dati.append('due_date', f('due').value);
      if (modifica) { dati.append('ref_id', modifica); }
      errore('');
      var eraNuovo = !modifica;
      invia(block.dataset.saveUrl, dati, function () {
        /* Dopo un inserimento la riga resta aperta: i codici si inseriscono di fila. */
        if (eraNuovo) {
          var form = block.querySelector('[data-tr-form]');
          var hint = block.querySelector('[data-tr-hint]');
          if (form) { form.hidden = false; }
          if (hint) { hint.hidden = false; }
        }
        if (f('kind')) {
          f('kind').value = ultimoTipo;
          saltaResponsabile = teniResp;
          if (teniResp) { f('owner').value = ultimoResp; } else { impostaResponsabile(); }
          f('code').focus();
        }
      });
    }

    function apriModifica(riga) {
      modifica = riga.dataset.trRef;
      block.querySelector('[data-tr-form]').hidden = false;
      f('kind').value = riga.dataset.kind;
      f('code').value = riga.dataset.code;
      f('path').value = riga.dataset.path;
      f('owner').value = riga.dataset.owner;
      f('due').value = riga.dataset.due;
      /* Tipo, responsabile e data di una riga nata da un'attività si cambiano sull'attività. */
      var collegata = Boolean(riga.dataset.task);
      f('kind').disabled = collegata;
      f('owner').disabled = collegata;
      f('due').disabled = collegata;
      f('save').textContent = 'Salva';
      f('code').focus();
    }

    block.addEventListener('click', function (e) {
      /* La riga di inserimento resta chiusa finché non serve. */
      if (e.target.closest('[data-tr-apri]')) {
        var form = block.querySelector('[data-tr-form]');
        var hint = block.querySelector('[data-tr-hint]');
        form.hidden = !form.hidden;
        if (hint) { hint.hidden = form.hidden; }
        if (!form.hidden && f('code')) { f('code').focus(); }
        return;
      }
      if (e.target.closest('[data-tr="save"]')) { salva(); return; }
      var sceltaFai = e.target.closest('[data-tr-fai]');
      if (sceltaFai) {
        var valori = new FormData();
        valori.append('valore', sceltaFai.getAttribute('data-tr-fai'));
        invia(block.dataset.actionBase + 'fai-non-richiesto/', valori);
        return;
      }
      var riga = e.target.closest('[data-tr-ref]');
      if (!riga) { return; }
      if (e.target.closest('[data-tr-edit]')) { apriModifica(riga); return; }
      var bottone = e.target.closest('[data-tr-action]');
      if (!bottone) { return; }
      var azione = bottone.getAttribute('data-tr-action');
      /* Elimina chiede conferma nel bottone stesso: secondo clic. */
      if (azione === 'delete' && !bottone.dataset.conferma) {
        bottone.dataset.conferma = '1';
        bottone.textContent = 'Conferma';
        return;
      }
      var dati = new FormData();
      dati.append('action', azione);
      invia(block.dataset.actionBase + riga.dataset.trRef + '/azione/', dati);
    });

    block.addEventListener('keydown', function (e) {
      /* Nell'esito il blocco sta dentro un form: Invio non deve registrare l'incontro. */
      if (e.key === 'Enter' && e.target.closest('[data-tr-form]') && e.target.tagName === 'INPUT') {
        e.preventDefault();
        salva();
      }
    });

    block.addEventListener('change', function (e) {
      if (e.target.matches('[data-tr="kind"]')) { impostaResponsabile(); }
      if (e.target.matches('[data-tr="owner"]')) { saltaResponsabile = true; }
    });

    impostaResponsabile();
  }

  document.querySelectorAll('[data-tr-block]').forEach(collega);
})();
