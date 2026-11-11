/* Disponibilità del giorno delle sale (portale + Outlook) e dei partecipanti: form incontro KICK-OFF
 * e moduli della reception (più riquadri nella stessa pagina, anche dentro <details> chiusi).
 * Clic su un orario libero di una sala: sceglie la sala e l'ora. Nessun salvataggio qui:
 * la prenotazione vera parte al salvataggio del modulo.
 * data-fine-id (facoltativo): campo «Alle»; la durata è fine - inizio e il clic la conserva. */
(function () {
  'use strict';

  function avvia(box) {
  var grid = box.querySelector('[data-sl-grid]');
  var msg = box.querySelector('[data-sl-msg]');
  function el(id) { return id ? document.getElementById(id) : null; }
  var campoData = el(box.dataset.dataId);
  var campoOra = el(box.dataset.oraId);
  var campoSala = el(box.dataset.salaId);
  var campoOrganizer = el(box.dataset.organizerId);
  var campoEsterni = el(box.dataset.esterniId);
  var campoDurata = el(box.dataset.durataId);
  var campoFine = el(box.dataset.fineId);
  var dati = null;
  var giro = 0;
  var timer = null;

  function minuti(hhmm) {
    var p = String(hhmm || '').split(':');
    return p.length < 2 ? null : parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
  }
  function hhmm(min) {
    var h = Math.floor(min / 60), m = min % 60;
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }
  function esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function durata() {
    if (campoFine) {
      var a = campoOra && minuti(campoOra.value), b = minuti(campoFine.value);
      return a != null && b != null && !isNaN(a) && !isNaN(b) && b > a ? b - a : 60;
    }
    var scelta = campoDurata && parseInt(campoDurata.value, 10);
    if (scelta > 0) { return scelta; }
    var raw = document.getElementById('id_agenda_items_raw');
    var totale = 0;
    try {
      (JSON.parse(raw && raw.value || '[]') || []).forEach(function (i) { totale += parseInt(i && i.durata_minuti || 0, 10) || 0; });
    } catch (e) { totale = 0; }
    return totale || 60;
  }

  function utentiScelti() {
    return Array.prototype.map.call(
      document.querySelectorAll('input[name="partecipanti_utenti"]:checked'), function (c) { return c.value; }
    ).slice(0, 15);
  }

  function esterni() {
    return (campoEsterni && campoEsterni.value || '').split(/\s+/).filter(function (e) { return e.indexOf('@') > 0; }).slice(0, 10);
  }

  function scelta() {
    var inizio = campoOra && minuti(campoOra.value);
    return inizio == null || isNaN(inizio) ? null : { inizio: inizio, fine: inizio + durata() };
  }

  function blocchiHtml(blocchi, inizioGiorno, totale, classe) {
    return blocchi.map(function (b) {
      var s = Math.max(minuti(b.inizio) - inizioGiorno, 0), f = Math.min(minuti(b.fine) - inizioGiorno, totale);
      if (f <= 0 || s >= totale) { return ''; }
      return '<span class="sl-b sl-b--' + (classe || b.fonte) + '" style="left:' + (s / totale * 100) + '%;width:' +
        ((f - s) / totale * 100) + '%" title="' + esc(b.inizio + '–' + b.fine + ' ' + b.titolo) + '"></span>';
    }).join('');
  }

  function disegna() {
    if (!dati) { return; }
    var inizioGiorno = dati.ora_inizio * 60, totale = (dati.ora_fine - dati.ora_inizio) * 60;
    var sel = scelta(), salaScelta = campoSala ? campoSala.value : '';
    var testa = '<div class="sl-r sl-r--ore"><span class="sl-n"></span><span class="sl-t">';
    for (var h = dati.ora_inizio; h < dati.ora_fine; h++) {
      testa += '<span class="sl-ora" style="left:' + ((h * 60 - inizioGiorno) / totale * 100) + '%">' + h + '</span>';
    }
    testa += '</span></div>';
    var righe = dati.sale.map(function (s) {
      var attiva = String(s.id) === String(salaScelta);
      var overlay = '';
      if (sel && attiva) {
        overlay = blocchiHtml([{ inizio: hhmm(sel.inizio), fine: hhmm(sel.fine), titolo: 'Il tuo incontro' }], inizioGiorno, totale, 'scelta');
      }
      return '<div class="sl-r' + (attiva ? ' is-scelta' : '') + '" data-sl-sala="' + s.id + '">' +
        '<span class="sl-n">' + esc(s.nome) + (s.capienza ? ' <small>' + s.capienza + ' posti</small>' : '') +
        (s.email ? '' : ' <small title="Senza casella Microsoft 365 non si prenota in Outlook">solo portale</small>') + '</span>' +
        '<span class="sl-t" data-sl-track>' + blocchiHtml(s.blocchi, inizioGiorno, totale) + overlay + '</span></div>';
    }).join('');
    if (dati.partecipanti) {
      var overlayP = sel ? blocchiHtml([{ inizio: hhmm(sel.inizio), fine: hhmm(sel.fine), titolo: 'Il tuo incontro' }], inizioGiorno, totale, 'scelta') : '';
      righe += '<div class="sl-r sl-r--persone"><span class="sl-n">Partecipanti <small>' + dati.partecipanti.n + '</small></span>' +
        '<span class="sl-t">' + blocchiHtml(dati.partecipanti.blocchi, inizioGiorno, totale) + overlayP + '</span></div>';
    }
    grid.innerHTML = dati.sale.length ? testa + righe :
      '<p class="mf-hint">' + esc(box.dataset.vuoto || 'Nessuna sala configurata: si aggiungono in Impostazioni KICK-OFF → Configurazione.') + '</p>';
    avvisi(sel, salaScelta);
  }

  function avvisi(sel, salaScelta) {
    var testi = [], grave = false;
    if (dati.outlook_msg) { testi.push(dati.outlook_msg); }
    if (sel) {
      var sala = dati.sale.filter(function (s) { return String(s.id) === String(salaScelta); })[0];
      if (sala) {
        sala.blocchi.forEach(function (b) {
          if (sel.inizio < minuti(b.fine) && minuti(b.inizio) < sel.fine) {
            grave = true;
            testi.unshift(sala.nome + ' è occupata dalle ' + b.inizio + ' alle ' + b.fine + ' (' + b.titolo + ').');
          }
        });
      }
      if (dati.partecipanti) {
        var occupati = dati.partecipanti.blocchi.filter(function (b) { return sel.inizio < minuti(b.fine) && minuti(b.inizio) < sel.fine; });
        if (occupati.length) {
          testi.push('In quell\'orario: ' + occupati.map(function (b) { return b.titolo; }).join(', ') + '.');
        }
      }
      if (sala && !grave) { testi.unshift(sala.nome + ' libera dalle ' + hhmm(sel.inizio) + ' alle ' + hhmm(sel.fine) + '.'); }
    }
    msg.textContent = testi.join(' ');
    msg.className = 'sl-msg' + (grave ? ' is-grave' : (sel && salaScelta ? ' is-ok' : ''));
  }

  function carica() {
    if (!campoData || !campoData.value) { return; }
    var params = new URLSearchParams({ data: campoData.value });
    if (box.dataset.escludi) { params.set('escludi', box.dataset.escludi); }
    if (campoOrganizer && campoOrganizer.value) { params.set('organizer', campoOrganizer.value); }
    var u = utentiScelti(); if (u.length) { params.set('utenti', u.join(',')); }
    var x = esterni(); if (x.length) { params.set('esterni', x.join(',')); }
    var mio = ++giro;
    box.classList.add('is-loading');
    fetch(box.dataset.url + '?' + params.toString(), {
      credentials: 'same-origin', headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (mio !== giro) { return; }
      if (!j.ok) { grid.innerHTML = '<p class="mf-hint">' + esc(j.reason || 'Disponibilità non disponibile.') + '</p>'; return; }
      dati = j;
      disegna();
    }).catch(function () {
      if (mio === giro) { grid.innerHTML = '<p class="mf-hint">Disponibilità non raggiungibile: riprova.</p>'; }
    }).then(function () { if (mio === giro) { box.classList.remove('is-loading'); } });
  }

  function caricaPoi() { clearTimeout(timer); timer = setTimeout(carica, 500); }

  grid.addEventListener('click', function (e) {
    var track = e.target.closest('[data-sl-track]');
    var riga = e.target.closest('[data-sl-sala]');
    if (!track || !riga || !dati) { return; }
    var r = track.getBoundingClientRect();
    var quota = Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1);
    var min = dati.ora_inizio * 60 + Math.floor(quota * (dati.ora_fine - dati.ora_inizio) * 2) * 30;
    var d = durata();
    if (campoFine) { campoFine.value = hhmm(Math.min(min + d, 23 * 60 + 59)); campoFine.dispatchEvent(new Event('change', { bubbles: true })); }
    if (campoOra) { campoOra.value = hhmm(min); campoOra.dispatchEvent(new Event('change', { bubbles: true })); }
    if (campoSala) { campoSala.value = riga.getAttribute('data-sl-sala'); campoSala.dispatchEvent(new Event('change', { bubbles: true })); }
    disegna();
  });

  if (campoData) { campoData.addEventListener('change', carica); }
  [campoOra, campoSala, campoDurata, campoFine].forEach(function (c) { if (c) { c.addEventListener('change', disegna); c.addEventListener('input', disegna); } });
  if (campoOrganizer) { campoOrganizer.addEventListener('change', caricaPoi); }
  if (campoEsterni) { campoEsterni.addEventListener('change', caricaPoi); }
  document.addEventListener('change', function (e) {
    if (e.target && e.target.name === 'partecipanti_utenti') { caricaPoi(); }
  });
  /* L'ordine del giorno cambia la durata: si ridisegna quando si torna sulla griglia. */
  var ultimaDurata = null;
  box.addEventListener('mouseenter', function () {
    var d = durata();
    if (d !== ultimaDurata) { ultimaDurata = d; disegna(); }
  });
  var chiuso = box.closest('details');
  if (chiuso) {
    chiuso.addEventListener('toggle', function () { if (chiuso.open && !dati) { carica(); } });
    if (chiuso.open) { carica(); }
  } else {
    carica();
  }
  }

  Array.prototype.forEach.call(document.querySelectorAll('[data-sl]'), avvia);
})();
