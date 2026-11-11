/* Impostazioni KICK-OFF: schede Modelli, FAI e Registro modifiche.
   - form[data-salva-ajax]: si inviano senza ricaricare; «Salva» compare solo
     quando la riga e' cambiata; l'esito arriva in riga. Un pulsante con
     data-salva-pagina (Elimina, Duplica) invia la pagina come prima.
   - Modelli: ricerca, spenti nascosti, anteprima dei punti mentre si scrive.
   - FAI: sezioni a schede, ricerca e disattivate nascoste per gruppo.
   - Registro: i filtri a tendina inviano da soli. */
(function () {
  'use strict';

  function csrf() {
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el) return el.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  /* ─── Salvataggio in riga ─────────────────────────────────────────── */
  function firma(form) {
    return new URLSearchParams(new FormData(form)).toString();
  }

  function mostraEsito(form, testo, errore) {
    var esito = form.querySelector('[data-esito]');
    if (!esito) return;
    esito.textContent = testo;
    esito.classList.toggle('is-errore', !!errore);
    esito.hidden = false;
    clearTimeout(esito._t);
    if (!errore) esito._t = setTimeout(function () { esito.hidden = true; }, 2500);
  }

  document.querySelectorAll('form[data-salva-ajax]').forEach(function (form) {
    var salva = form.querySelector('[data-salva]');
    var iniziale = firma(form);
    function aggiorna() {
      var sporco = firma(form) !== iniziale;
      form.classList.toggle('is-modificata', sporco);
      if (salva) salva.hidden = !sporco;
    }
    form.addEventListener('input', aggiorna);
    form.addEventListener('change', aggiorna);
    aggiorna();

    form.addEventListener('submit', function (ev) {
      if (ev.submitter && ev.submitter.hasAttribute('data-salva-pagina')) return;
      ev.preventDefault();
      if (!form.reportValidity()) return;
      if (salva) salva.disabled = true;
      fetch(form.getAttribute('action') || window.location.href, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
      }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok && d.ok, dati: d }; }); })
        .then(function (res) {
          var msg = (res.dati && res.dati.messaggi && res.dati.messaggi.length) ? res.dati.messaggi[res.dati.messaggi.length - 1].testo : '';
          if (!res.ok) { mostraEsito(form, msg || 'Non salvato.', true); return; }
          iniziale = firma(form);
          aggiorna();
          mostraEsito(form, 'Salvato', false);
          form.dispatchEvent(new CustomEvent('impostazioni:salvato', { bubbles: true }));
        })
        .catch(function () { mostraEsito(form, 'Non salvato: riprova.', true); })
        .finally(function () { if (salva) salva.disabled = false; });
    });
  });

  /* ─── Modelli ODG ─────────────────────────────────────────────────── */
  function parsePunti(testo) {
    return (testo || '').split('\n').map(function (r) { return r.trim(); }).filter(Boolean).map(function (r) {
      var i = r.indexOf('|');
      var titolo = (i >= 0 ? r.slice(0, i) : r).trim();
      var min = i >= 0 ? parseInt(r.slice(i + 1).trim(), 10) : NaN;
      return { titolo: titolo, min: (min > 0 && min <= 480) ? min : null };
    }).filter(function (p) { return p.titolo; });
  }

  document.querySelectorAll('[data-tpl-punti]').forEach(function (area) {
    var box = area.closest('.tpl-punti');
    var ol = box && box.querySelector('[data-tpl-anteprima]');
    var cont = box && box.querySelector('[data-tpl-conteggio]');
    function render() {
      var punti = parsePunti(area.value);
      var tot = punti.reduce(function (a, p) { return a + (p.min || 0); }, 0);
      if (cont) cont.textContent = punti.length + (punti.length === 1 ? ' punto' : ' punti') + (tot ? ' · ' + tot + ' min' : '');
      if (!ol) return;
      ol.textContent = '';
      punti.forEach(function (p) {
        var li = document.createElement('li');
        li.textContent = p.titolo;
        if (p.min) { var s = document.createElement('small'); s.textContent = p.min + ' min'; li.appendChild(s); }
        ol.appendChild(li);
      });
    }
    area.addEventListener('input', render);
    render();
  });

  var modelli = document.querySelector('[data-modelli]');
  if (modelli) {
    var nuovo = modelli.querySelector('#tpl-nuovo');
    var btnNuovo = modelli.querySelector('[data-modelli-nuovo]');
    btnNuovo && btnNuovo.addEventListener('click', function () {
      nuovo.hidden = !nuovo.hidden;
      btnNuovo.setAttribute('aria-expanded', String(!nuovo.hidden));
      if (!nuovo.hidden) nuovo.querySelector('input[name=nome]').focus();
    });
    var annulla = modelli.querySelector('[data-modelli-annulla]');
    annulla && annulla.addEventListener('click', function () { nuovo.hidden = true; btnNuovo && btnNuovo.setAttribute('aria-expanded', 'false'); });

    var cerca = modelli.querySelector('[data-modelli-cerca]');
    var spenti = modelli.querySelector('[data-modelli-spenti]');
    var vuoto = modelli.querySelector('[data-modelli-vuoto]');
    var esito = modelli.querySelector('[data-modelli-esito]');
    var card = Array.prototype.slice.call(modelli.querySelectorAll('[data-modello]'));
    function filtra() {
      var q = (cerca ? cerca.value : '').trim().toLowerCase();
      var mostraSpenti = spenti ? spenti.checked : true;
      var visibili = 0;
      card.forEach(function (c) {
        var testo = c.querySelector('summary').textContent.toLowerCase();
        var ok = (!q || testo.indexOf(q) >= 0) && (mostraSpenti || c.getAttribute('data-attivo') === '1' || c.open);
        c.hidden = !ok;
        if (ok) visibili++;
      });
      if (vuoto) vuoto.hidden = visibili > 0;
      if (esito) {
        var nascosti = card.length - visibili;
        esito.hidden = !nascosti;
        esito.textContent = nascosti ? nascosti + ' nascost' + (nascosti === 1 ? 'o' : 'i') : '';
      }
    }
    cerca && cerca.addEventListener('input', filtra);
    spenti && spenti.addEventListener('change', filtra);
    /* Lo stato Attivo cambia dal form salvato in riga: la scheda si aggiorna senza ricaricare. */
    modelli.addEventListener('impostazioni:salvato', function (ev) {
      var c = ev.target.closest('[data-modello]');
      if (!c) return;
      var attivo = ev.target.querySelector('input[name=is_active]').checked;
      c.setAttribute('data-attivo', attivo ? '1' : '0');
      c.classList.toggle('tpl-card--spento', !attivo);
      var chip = c.querySelector('.tpl-chip--spento');
      if (!attivo && !chip) { chip = document.createElement('span'); chip.className = 'tpl-chip tpl-chip--spento'; chip.textContent = 'Spento'; c.querySelector('summary').appendChild(chip); }
      if (attivo && chip) chip.remove();
      var nome = c.querySelector('.tpl-summary-nome'); var inNome = ev.target.querySelector('input[name=nome]');
      if (nome && inNome) nome.textContent = inNome.value;
      var desc = c.querySelector('.tpl-summary-desc'); var inDesc = ev.target.querySelector('input[name=descrizione]');
      if (desc && inDesc) desc.textContent = inDesc.value;
    });
    filtra();
  }

  /* ─── Registro FAI ────────────────────────────────────────────────── */
  var faiNav = document.querySelector('[data-fai-nav]');
  if (faiNav) {
    var corpi = Array.prototype.slice.call(document.querySelectorAll('[data-fai-sezione-corpo]'));
    var tabs = Array.prototype.slice.call(faiNav.querySelectorAll('[data-fai-sezione]'));
    function apri(codice, salvaHash) {
      if (!tabs.some(function (t) { return t.getAttribute('data-fai-sezione') === codice; })) codice = 'scadenze';
      tabs.forEach(function (t) {
        var on = t.getAttribute('data-fai-sezione') === codice;
        t.classList.toggle('is-attiva', on);
        t.setAttribute('aria-selected', String(on));
      });
      corpi.forEach(function (c) { c.hidden = c.getAttribute('data-fai-sezione-corpo') !== codice; });
      if (salvaHash) history.replaceState(null, '', '#fai-' + codice);
    }
    tabs.forEach(function (t) { t.addEventListener('click', function () { apri(t.getAttribute('data-fai-sezione'), true); }); });
    var hash = (location.hash || '').replace(/^#fai-/, '');
    apri(hash || 'scadenze', false);

    document.querySelectorAll('[data-fai-gruppo]').forEach(function (gruppo) {
      var cerca = gruppo.querySelector('[data-fai-cerca]');
      var spente = gruppo.querySelector('[data-fai-spente]');
      var spenteN = gruppo.querySelector('[data-fai-spente-n]');
      var vuoto = gruppo.querySelector('[data-fai-vuoto]');
      var esito = gruppo.querySelector('[data-fai-esito]');
      var righe = Array.prototype.slice.call(gruppo.querySelectorAll('[data-fai-riga]'));
      function testoRiga(r) {
        return Array.prototype.map.call(r.querySelectorAll('input[type=text], select'), function (i) {
          return i.tagName === 'SELECT' ? (i.options[i.selectedIndex] || {}).text || '' : i.value;
        }).join(' ').toLowerCase();
      }
      function filtra() {
        var q = (cerca ? cerca.value : '').trim().toLowerCase();
        var mostraSpente = spente ? spente.checked : true;
        var visibili = 0, nSpente = 0;
        righe.forEach(function (r) {
          var attiva = r.querySelector('input[name=attiva]');
          var on = attiva ? attiva.checked : true;
          if (!on) nSpente++;
          var ok = (!q || testoRiga(r).indexOf(q) >= 0) && (mostraSpente || on || r.classList.contains('is-modificata'));
          r.hidden = !ok;
          if (ok) visibili++;
        });
        if (spenteN) spenteN.textContent = nSpente ? '(' + nSpente + ')' : '';
        if (vuoto) vuoto.hidden = visibili > 0 || !righe.length;
        if (esito) {
          var nascoste = righe.length - visibili;
          esito.hidden = !nascoste;
          esito.textContent = nascoste ? nascoste + ' nascost' + (nascoste === 1 ? 'a' : 'e') : '';
        }
      }
      cerca && cerca.addEventListener('input', filtra);
      spente && spente.addEventListener('change', filtra);
      gruppo.addEventListener('impostazioni:salvato', function (ev) {
        var attiva = ev.target.querySelector('input[name=attiva]');
        if (attiva) ev.target.classList.toggle('fai-opz-spenta', !attiva.checked);
        filtra();
      });
      filtra();
    });
  }

  /* ─── Registro modifiche ──────────────────────────────────────────── */
  var logFiltri = document.querySelector('[data-log-filtri]');
  if (logFiltri) {
    logFiltri.querySelectorAll('[data-invia-al-cambio]').forEach(function (campo) {
      campo.addEventListener('change', function () { logFiltri.requestSubmit ? logFiltri.requestSubmit() : logFiltri.submit(); });
    });
  }
})();
