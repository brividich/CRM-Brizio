/* Nuovo kickoff / Modifica kickoff.

   - Team: le persone scelte sono etichette; l'elenco di ogni ruolo è una
     tendina che si apre entrando nella ricerca (frecce, Invio, Esc).
   - Riepilogo a lato e barra in fondo: dicono in ogni momento cosa manca
     per creare il kickoff e per risultare pronto all'avvio.
   - Oggetto proposto: «Cliente · P/N · Descrizione pezzo».
   - Doppione: stesso P/N + revisione + versione di un kickoff esistente si
     vede mentre si scrive (endpoint tasks:identity_check), non dopo l'invio.

   Miglioria progressiva: senza questo file il form si compila e si invia lo
   stesso, e le regole le applica comunque il server (ProjectKickoffForm). */
(function () {
  'use strict';

  var form = document.getElementById('kc-form');
  if (!form) return;

  function campo(nome) { return form.querySelector('[name="' + nome + '"]'); }
  function testo(el) { return el ? String(el.value || '').trim() : ''; }

  var cliente = campo('client_name');
  var pn = campo('part_number');
  var descrizione = campo('descrizione_pezzo');
  var revisione = campo('revisione');
  var versione = campo('versione');
  var oggetto = campo('name');
  var invio = form.querySelector('[data-kn-invio]');
  var stato = form.querySelector('[data-kn-stato]');
  var etichettaInvio = form.getAttribute('data-etichetta-invio') || (invio ? invio.textContent : '');
  var doppione = null; // {name, url} quando P/N + rev + versione esistono già

  /* ── Team ─────────────────────────────────────────────────────────── */
  var ruoli = Array.prototype.map.call(form.querySelectorAll('[data-kn-role]'), function (box) {
    var pick = box.querySelector('[data-kn-pick]');
    var chips = box.querySelector('[data-kn-chips]');
    var cerca = box.querySelector('.kn-pick-search');
    var vuoto = box.querySelector('[data-kn-vuoto]');
    var opzioni = Array.prototype.slice.call(box.querySelectorAll('.kn-pick-opt'));
    var io = box.querySelector('[data-kn-me]');
    var cursore = -1;

    function nome(opt) { return opt.querySelector('span').textContent.trim(); }
    function spunta(opt) { return opt.querySelector('input[type="checkbox"]'); }
    function scelte() { return opzioni.filter(function (o) { return spunta(o).checked; }); }
    function visibili() { return opzioni.filter(function (o) { return !o.classList.contains('is-hidden'); }); }

    function imposta(opt, si) {
      var input = spunta(opt);
      if (input.checked === si) return;
      input.checked = si;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function disegna() {
      chips.replaceChildren();
      scelte().forEach(function (opt) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'kn-chip';
        chip.title = 'Togli ' + nome(opt);
        var etichetta = document.createElement('span');
        etichetta.textContent = nome(opt);
        var x = document.createElement('b');
        x.textContent = '×';
        x.setAttribute('aria-hidden', 'true');
        chip.append(etichetta, x);
        chip.addEventListener('click', function () { imposta(opt, false); cerca.focus(); });
        chips.appendChild(chip);
      });
      box.classList.toggle('is-ok', scelte().length > 0);
      if (io) {
        var mia = opzioni.filter(function (o) { return spunta(o).value === io.getAttribute('data-kn-me'); })[0];
        io.hidden = !mia || spunta(mia).checked;
      }
    }

    function muovi(passo) {
      var lista = visibili();
      opzioni.forEach(function (o) { o.classList.remove('is-cursor'); });
      if (!lista.length) { cursore = -1; return; }
      cursore = (cursore + passo + lista.length) % lista.length;
      lista[cursore].classList.add('is-cursor');
      lista[cursore].scrollIntoView({ block: 'nearest' });
    }

    function filtra() {
      var ago = cerca.value.trim().toLowerCase();
      opzioni.forEach(function (o) {
        o.classList.toggle('is-hidden', !!ago && nome(o).toLowerCase().indexOf(ago) === -1);
        o.classList.remove('is-cursor');
      });
      cursore = -1;
      if (vuoto) vuoto.hidden = !opzioni.length || visibili().length > 0;
    }

    function apri(si) {
      pick.classList.toggle('is-open', si);
      if (!si) { opzioni.forEach(function (o) { o.classList.remove('is-cursor'); }); cursore = -1; }
    }

    pick.classList.add('is-js');
    box.addEventListener('change', disegna);
    cerca.addEventListener('focus', function () { apri(true); });
    cerca.addEventListener('input', function () { apri(true); filtra(); });
    cerca.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); apri(true); muovi(1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); apri(true); muovi(-1); }
      else if (e.key === 'Escape') { apri(false); }
      else if (e.key === 'Enter') {
        // Invio sceglie, non invia il form a metà compilazione.
        e.preventDefault();
        var lista = visibili();
        var opt = cursore >= 0 ? lista[cursore] : (cerca.value.trim() && lista.length === 1 ? lista[0] : null);
        if (opt) { imposta(opt, !spunta(opt).checked); cerca.value = ''; filtra(); }
      } else if (e.key === 'Backspace' && !cerca.value) {
        var ultime = scelte();
        if (ultime.length) imposta(ultime[ultime.length - 1], false);
      }
    });
    document.addEventListener('click', function (e) { if (!box.contains(e.target)) apri(false); });
    box.addEventListener('focusout', function (e) {
      if (e.relatedTarget && !box.contains(e.relatedTarget)) apri(false);
    });
    if (io) {
      io.addEventListener('click', function () {
        var mia = opzioni.filter(function (o) { return spunta(o).value === io.getAttribute('data-kn-me'); })[0];
        if (mia) imposta(mia, true);
      });
    }
    disegna();

    return {
      chiave: box.getAttribute('data-kn-role'),
      etichetta: box.getAttribute('data-kn-etichetta'),
      quanti: function () { return scelte().length; },
      cerca: cerca
    };
  });

  /* ── Riepilogo, barra, oggetto proposto ───────────────────────────── */
  function oggettoProposto() {
    var codice = testo(pn);
    if (codice && testo(revisione)) codice += ' rev. ' + testo(revisione);
    return [testo(cliente), codice, testo(descrizione)].filter(Boolean).join(' · ');
  }

  function scrivi(sel, valore, vuoto) {
    var el = form.querySelector(sel);
    if (!el) return;
    el.textContent = valore || vuoto;
    el.classList.toggle('is-empty', !valore);
  }

  function segna(chiave, ok) {
    var el = form.querySelector('[data-kn-check="' + chiave + '"]');
    if (el) el.classList.toggle('is-ok', ok);
  }

  function mancanti() {
    var m = [];
    if (!testo(cliente)) m.push('il cliente');
    if (!ruoli.some(function (r) { return r.quanti() > 0; })) m.push('una persona del team');
    return m;
  }

  function aggiorna() {
    var proposto = oggettoProposto();
    if (oggetto) oggetto.placeholder = proposto || 'Si compone da cliente, P/N e descrizione pezzo';
    scrivi('[data-kn-anteprima]', testo(oggetto) || proposto, 'Si compone da cliente, P/N e descrizione pezzo');
    scrivi('[data-kn-dato="cliente"]', testo(cliente), '—');
    var codice = [testo(pn), testo(revisione) && 'rev. ' + testo(revisione), testo(versione) && 'v. ' + testo(versione)]
      .filter(Boolean).join(' · ');
    scrivi('[data-kn-dato="pn"]', codice, '—');
    var persone = ruoli.reduce(function (n, r) { return n + r.quanti(); }, 0);
    scrivi('[data-kn-dato="team"]', persone ? persone + (persone === 1 ? ' persona' : ' persone') : '', 'nessuno');

    segna('cliente', !!testo(cliente));
    segna('team', persone > 0);
    ruoli.forEach(function (r) { segna(r.chiave, r.quanti() > 0); });

    var revSenzaPn = form.querySelector('[data-kn-revpn]');
    if (revSenzaPn) revSenzaPn.hidden = !!testo(pn) || !(testo(revisione) || testo(versione));

    var m = mancanti();
    if (stato) {
      stato.classList.toggle('is-ko', m.length > 0);
      if (m.length) stato.textContent = 'Manca ' + m.join(' e ') + '.';
      else if (doppione) stato.textContent = 'Questo kickoff esiste già: si riapre quello.';
      else if (form.hasAttribute('data-check-url')) stato.textContent = 'Tutto pronto: poi si apre la scheda VRF.';
      else stato.textContent = 'Le modifiche valgono da quando salvi.';
    }
    if (invio) invio.textContent = doppione ? 'Riapri il kickoff esistente →' : etichettaInvio;
    // Corretto l'errore, il messaggio se ne va da solo.
    if (testo(cliente)) mostraErrore('cliente', false);
    if (persone > 0) mostraErrore('team', false);
  }

  function mostraErrore(chiave, si) {
    var zona = form.querySelector('[data-kn-campo="' + chiave + '"]');
    if (!zona) return;
    var msg = zona.querySelector('[data-kn-err]');
    if (msg) msg.hidden = !si;
    zona.classList.toggle('has-error', si);
  }

  /* Il controllo parte dal clic sul pulsante, non dal submit: un invio
     fermato qui non deve spegnere l'avviso «modifiche non salvate». */
  if (invio) {
    invio.addEventListener('click', function (e) {
      var senzaCliente = !testo(cliente);
      var senzaTeam = !ruoli.some(function (r) { return r.quanti() > 0; });
      if (!senzaCliente && !senzaTeam) return;
      e.preventDefault();
      mostraErrore('cliente', senzaCliente);
      mostraErrore('team', senzaTeam);
      var primo = senzaCliente ? cliente : (ruoli[0] && ruoli[0].cerca);
      if (primo) {
        primo.scrollIntoView({ behavior: 'smooth', block: 'center' });
        primo.focus({ preventScroll: true });
      }
    });
  }

  /* ── Doppione: stesso P/N + revisione + versione ──────────────────── */
  var urlControllo = form.getAttribute('data-check-url');
  var avviso = form.querySelector('[data-kn-doppione]');
  var richiesta = 0;
  var attesa = null;

  function mostraDoppione(dati) {
    doppione = dati && dati.exists ? dati : null;
    if (avviso) {
      avviso.hidden = !doppione;
      if (doppione) {
        avviso.querySelector('[data-kn-doppione-nome]').textContent = doppione.name || 'kickoff esistente';
        avviso.querySelector('[data-kn-doppione-link]').setAttribute('href', doppione.url);
      }
    }
    aggiorna();
  }

  function controlla() {
    if (!urlControllo) return;
    var mia = ++richiesta;
    if (!testo(pn)) { mostraDoppione(null); return; }
    var query = '?part_number=' + encodeURIComponent(testo(pn)) +
      '&revisione=' + encodeURIComponent(testo(revisione)) +
      '&versione=' + encodeURIComponent(testo(versione));
    fetch(urlControllo + query, {
      headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
      credentials: 'same-origin'
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (dati) { if (mia === richiesta) mostraDoppione(dati); })
      .catch(function () { /* accessorio: al salvataggio decide comunque il server */ });
  }

  [pn, revisione, versione].forEach(function (el) {
    if (!el) return;
    el.addEventListener('input', function () { clearTimeout(attesa); attesa = setTimeout(controlla, 300); });
    el.addEventListener('change', controlla);
  });

  form.addEventListener('input', aggiorna);
  form.addEventListener('change', aggiorna);
  aggiorna();
  controlla();

  /* ── Tipo di commessa: spunta le tappe del modello scelto ─────────── */
  var modello = document.getElementById('fl-modello');
  if (modello) {
    var modelli = {};
    try { modelli = JSON.parse(modello.dataset.modelli || '{}'); } catch (err) { modelli = {}; }
    modello.addEventListener('change', function () {
      var tappe = modelli[modello.value];
      if (!tappe) return;
      form.querySelectorAll('input[name="tappe_servono"]').forEach(function (c) {
        c.checked = tappe.indexOf(c.value) !== -1;
      });
    });
  }
})();
