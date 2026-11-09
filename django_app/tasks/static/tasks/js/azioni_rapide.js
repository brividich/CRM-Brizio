/* Menu «⋯» su un incarico: date (o richiesta di spostamento), responsabile, priorità, annulla, riapri.
 * Bottone: <button data-ar-task="ID">. Le regole le decide il server: il menu mostra solo quello che puoi fare. */
(function () {
  'use strict';
  if (window.__azioniRapide) { return; }
  window.__azioniRapide = true;

  var pop = null;
  var corrente = null;

  function csrf() {
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input) { return input.value; }
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function url(id) { return '/tasks/' + id + '/azione-rapida/'; }

  var velo = null;

  function chiudi() {
    if (pop) { pop.remove(); pop = null; }
    if (velo) { velo.remove(); velo = null; }
    document.documentElement.classList.remove('ar-aperto');
    if (corrente) { corrente.setAttribute('aria-expanded', 'false'); corrente = null; }
  }

  function toast(testo) {
    var box = document.querySelector('.ar-toast');
    if (!box) {
      box = document.createElement('div');
      box.className = 'ar-toast';
      box.setAttribute('role', 'status');
      document.body.appendChild(box);
    }
    box.textContent = testo;
    box.hidden = false;
    clearTimeout(box._t);
    box._t = setTimeout(function () { box.hidden = true; }, 4000);
  }

  function disegna(d) {
    var p = d.permessi, html = '<div class="ar-head"><strong>' + esc(d.titolo) + '</strong><button type="button" class="ar-x" data-ar-chiudi aria-label="Chiudi">×</button></div>';
    if (p.date) {
      html += '<div class="ar-sez"><span class="ar-tit">' + (p.date_subito ? 'Date' : 'Chiedi lo spostamento') + '</span>' +
        '<div class="ar-riga"><label>Inizio<input class="input" type="date" data-ar="inizio" value="' + esc(d.inizio) + '"></label>' +
        '<label>Fine<input class="input" type="date" data-ar="fine" value="' + esc(d.fine) + '"></label></div>' +
        (p.date_subito ? '' : '<input class="input" type="text" data-ar="motivo-date" maxlength="500" placeholder="Motivo (lo legge il capocommessa)">') +
        (d.spostamento_aperto ? '<small class="ar-nota">C\'è già una richiesta in attesa: la nuova la sostituisce.</small>' : '') +
        '<button type="button" class="btn btn-sm" data-ar-azione="date">' + (p.date_subito ? 'Salva date' : 'Chiedi') + '</button></div>';
    }
    if (p.responsabile) {
      var opts = '<option value="">Da assegnare</option>', gruppo = '';
      d.utenti.forEach(function (u) {
        if (u.gruppo !== gruppo) { opts += (gruppo ? '</optgroup>' : '') + '<optgroup label="' + (u.gruppo === 'team' ? 'Team' : 'Altri') + '">'; gruppo = u.gruppo; }
        opts += '<option value="' + u.id + '"' + (String(u.id) === String(d.responsabile) ? ' selected' : '') + '>' + esc(u.nome) + '</option>';
      });
      if (gruppo) { opts += '</optgroup>'; }
      html += '<div class="ar-sez"><span class="ar-tit">Responsabile</span><div class="ar-riga"><select class="input" data-ar="responsabile">' + opts + '</select>' +
        '<button type="button" class="btn btn-secondary btn-sm" data-ar-azione="responsabile">Cambia</button></div></div>';
    }
    if (p.priorita) {
      html += '<div class="ar-sez"><span class="ar-tit">Priorità</span><div class="ar-chips">' + d.priorita_scelte.map(function (c) {
        return '<button type="button" class="ar-chip' + (c[0] === d.priorita ? ' is-on' : '') + '" data-ar-azione="priorita" data-ar-valore="' + c[0] + '">' + esc(c[1]) + '</button>';
      }).join('') + '</div></div>';
    }
    if (p.annulla) {
      html += '<div class="ar-sez"><span class="ar-tit">Annulla l\'attività</span><div class="ar-riga"><input class="input" type="text" data-ar="motivo" maxlength="300" placeholder="Motivo (obbligatorio)">' +
        '<button type="button" class="btn btn-secondary btn-sm ar-danger" data-ar-azione="annulla">Annulla</button></div></div>';
    }
    if (p.riapri) {
      html += '<div class="ar-sez"><button type="button" class="btn btn-secondary btn-sm" data-ar-azione="riapri">Riapri l\'attività</button></div>';
    }
    if (!p.date && !p.responsabile && !p.priorita && !p.annulla && !p.riapri) {
      html += '<p class="ar-nota">Su questa attività non puoi cambiare niente: decide il capocommessa.</p>';
    }
    html += '<p class="ar-err" data-ar="err" hidden></p><a class="ar-link" href="/tasks/' + d.id + '/">Apri la scheda e lo storico →</a>';
    pop.innerHTML = html;
  }

  /* Pannello laterale a destra (a tutta larghezza sullo smartphone): mai ancorato al pulsante. */
  function posiziona() { /* il posto lo decide il CSS */ }

  function apri(btn) {
    chiudi();
    corrente = btn;
    btn.setAttribute('aria-expanded', 'true');
    velo = document.createElement('div');
    velo.className = 'ar-velo';
    velo.setAttribute('data-ar-chiudi', '');
    document.body.appendChild(velo);
    document.documentElement.classList.add('ar-aperto');
    pop = document.createElement('div');
    pop.className = 'ar-pop';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-modal', 'true');
    pop.innerHTML = '<p class="ar-nota">Carico…</p>';
    document.body.appendChild(pop);
    posiziona(btn);
    fetch(url(btn.dataset.arTask), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (pop && d.ok) { disegna(d); posiziona(btn); } })
      .catch(function () { if (pop) { pop.innerHTML = '<p class="ar-err">Non riesco a leggere l\'attività.</p>'; } });
  }

  function invia(azione, valore) {
    var id = corrente.dataset.arTask;
    var dati = new FormData();
    dati.append('azione', azione);
    function v(nome) { var el = pop.querySelector('[data-ar="' + nome + '"]'); return el ? el.value : ''; }
    if (azione === 'date') { dati.append('inizio', v('inizio')); dati.append('fine', v('fine')); dati.append('motivo', v('motivo-date')); }
    if (azione === 'responsabile') { dati.append('responsabile', v('responsabile')); }
    if (azione === 'priorita') { dati.append('priorita', valore); }
    if (azione === 'annulla') { dati.append('motivo', v('motivo')); }
    fetch(url(id), { method: 'POST', body: dati, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          var err = pop.querySelector('[data-ar="err"]');
          if (err) { err.textContent = d.reason || 'Non salvato.'; err.hidden = false; }
          return;
        }
        chiudi();
        try { sessionStorage.setItem('ar-msg', d.messaggio || 'Salvato.'); } catch (e) { /* niente */ }
        window.location.reload();
      })
      .catch(function () { toast('Connessione non riuscita: riprova.'); });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-ar-task]');
    if (btn) { e.preventDefault(); if (corrente === btn) { chiudi(); } else { apri(btn); } return; }
    if (!pop) { return; }
    if (e.target.closest('[data-ar-chiudi]') || e.target === velo) { chiudi(); return; }
    var az = e.target.closest('[data-ar-azione]');
    if (az && pop.contains(az)) { invia(az.dataset.arAzione, az.dataset.arValore); return; }
    if (!pop.contains(e.target)) { chiudi(); }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { chiudi(); } });

  try {
    var msg = sessionStorage.getItem('ar-msg');
    if (msg) { sessionStorage.removeItem('ar-msg'); document.addEventListener('DOMContentLoaded', function () { toast(msg); }); if (document.readyState !== 'loading') { toast(msg); } }
  } catch (e) { /* niente */ }
})();
