/* RENTRI: popup «Elimina» (annulla o elimina definitivamente) e «Consolida filo».
   Pulsanti: [data-rimuovi="<url>"] con i dati della riga, [data-consolida-filo="<url>"].
   Ascolto in cattura: i pulsanti stanno anche nell'intestazione del filo, che al clic si apre/chiude. */
(function () {
  function qui() { return location.pathname + location.search; }

  function chiudibile(dlg) {
    if (!dlg || dlg._rnPronto) return;
    dlg._rnPronto = true;
    dlg.addEventListener('click', function (e) {
      if (e.target === dlg || e.target.closest('[data-chiudi]')) dlg.close();
    });
  }

  function apriRimuovi(btn) {
    var dlg = document.getElementById('rn-rimuovi');
    if (!dlg) return;
    chiudibile(dlg);
    var d = btn.dataset;
    var form = dlg.querySelector('form');
    form.action = d.rimuovi;
    form.querySelector('[name="next"]').value = qui();
    form.querySelector('[name="motivo"]').value = '';
    dlg.querySelector('[data-campo="titolo"]').textContent = 'Elimina ' + (d.num || 'registrazione');
    var righe = [d.tipo, d.num, d.data, d.codice, d.qta ? 'quantità ' + d.qta : '', d.fir ? 'FIR ' + d.fir : '']
      .filter(Boolean);
    dlg.querySelector('[data-campo="riepilogo"]').textContent = righe.join(' · ');
    var figli = dlg.querySelector('[data-campo="figli"]');
    figli.hidden = !d.figli;
    figli.textContent = d.figli
      ? 'Movimenti collegati: ' + d.figli + '. Annullando, restano con il riferimento come traccia ma non risultano più collegati.'
      : '';
    var elimina = dlg.querySelector('input[value="elimina"]');
    var modoElimina = elimina.closest('.rn-dlg-modo');
    var nota = dlg.querySelector('[data-campo="elimina-nota"]');
    var si = d.eliminabile === '1';
    elimina.disabled = !si;
    modoElimina.classList.toggle('is-off', !si);
    nota.textContent = si
      ? 'Solo per una bozza inserita per errore: sparisce dal registro, il numero non viene riusato. Dati e motivo restano nel registro delle attività.'
      : 'Non disponibile: ' + (d.perche || 'la registrazione non è una bozza isolata') + '.';
    dlg.querySelector('input[value="annulla"]').checked = true;
    aggiornaConferma(dlg);
    dlg.showModal();
    form.querySelector('[name="motivo"]').focus();
  }

  function aggiornaConferma(dlg) {
    var elimina = dlg.querySelector('input[value="elimina"]').checked;
    var btn = dlg.querySelector('[data-campo="conferma"]');
    btn.textContent = elimina ? 'Elimina definitivamente' : 'Annulla registrazione';
  }

  function apriFilo(btn) {
    var dlg = document.getElementById('rn-filo');
    if (!dlg) return;
    chiudibile(dlg);
    var corpo = dlg.querySelector('.rn-dlg-box');
    corpo.innerHTML = '<div class="rn-dlg-nota">Caricamento del filo…</div>';
    dlg.showModal();
    var url = btn.dataset.consolidaFilo + '?next=' + encodeURIComponent(qui());
    fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status === 403 ? 'Non hai i permessi per consolidare.' : 'Errore ' + r.status);
        return r.text();
      })
      .then(function (html) { corpo.innerHTML = html; })
      .catch(function (err) {
        corpo.innerHTML = '';
        var p = document.createElement('div');
        p.className = 'rn-dlg-avviso';
        p.textContent = 'Anteprima non caricata: ' + err.message;
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'rn-dlg-btn'; b.setAttribute('data-chiudi', ''); b.textContent = 'Chiudi';
        corpo.appendChild(p); corpo.appendChild(b);
      });
  }

  document.addEventListener('click', function (e) {
    var r = e.target.closest('[data-rimuovi]');
    var f = e.target.closest('[data-consolida-filo]');
    if (!r && !f) return;
    e.preventDefault();
    e.stopPropagation();
    if (r) apriRimuovi(r); else apriFilo(f);
  }, true);

  document.addEventListener('change', function (e) {
    var dlg = e.target.closest && e.target.closest('#rn-rimuovi');
    if (dlg && e.target.name === 'modo') aggiornaConferma(dlg);
  });
})();
