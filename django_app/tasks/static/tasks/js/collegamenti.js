/* Riquadro «Collegamenti» dell'attività (scheda, form, pannello laterale).

   Stesso gesto per tutti i tipi: «+ tipo», si cerca per codice o nome, «Collega»;
   se il codice non c'è, «Aggiungi e collega». Ogni comando passa da
   tasks:collegamenti_azione e il server rimanda il riquadro rifatto. Nel form
   «+ Attività» l'attività non esiste ancora: le scelte restano in un campo
   nascosto (collegamenti_json) e si applicano al salvataggio.

   Lo script può essere caricato più volte (il pannello laterale lo riesegue):
   gli ascoltatori si montano una volta sola, sul documento. */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function dici(testo, errore) {
    if (window.hubFlash && testo) window.hubFlash.show([{ level: errore ? 'error' : 'success', text: testo }]);
  }
  function radice(el) { return el.closest ? el.closest('[data-kc]') : null; }
  function stato(root) {
    if (!root.__kc) root.__kc = { tipo: '', attesa: [], timer: null, giro: 0 };
    return root.__kc;
  }

  function invia(root, dati) {
    var corpo = new URLSearchParams(dati);
    return fetch(root.getAttribute('data-url'), {
      method: 'POST',
      headers: {
        'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': root.getAttribute('data-csrf'),
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      credentials: 'same-origin',
      body: corpo.toString()
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        j.ok = r.ok && j.ok !== false;
        return j;
      });
    }).then(function (j) {
      if (!j.ok) { dici(j.reason || j.error || 'Modifica non salvata.', true); return j; }
      if (j.html != null) {
        root.querySelector('[data-kc-corpo]').innerHTML = j.html;
        segnaTipo(root);
      }
      dici(j.messaggio);
      // Macchina già impegnata nel periodo: il collegamento è salvato, questo è solo un avviso.
      if (j.avviso && window.hubFlash) window.hubFlash.show([{ level: 'warning', text: j.avviso }]);
      document.dispatchEvent(new CustomEvent('kc:cambiato', { detail: { task: root.getAttribute('data-task'), risposta: j } }));
      return j;
    }).catch(function () {
      dici('Non riesco a salvare: controlla la connessione e riprova.', true);
      return { ok: false };
    });
  }

  /* Il chip del tipo aperto resta premuto anche dopo che il riquadro si è rifatto. */
  function segnaTipo(root) {
    var st = stato(root);
    root.querySelectorAll('[data-kc-tipo]').forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-kc-tipo') === st.tipo ? 'true' : 'false');
    });
  }

  function apri(root, tipo) {
    var st = stato(root), box = root.querySelector('[data-kc-cerca]');
    if (!box) return;
    st.tipo = st.tipo === tipo ? '' : tipo;
    segnaTipo(root);
    box.hidden = !st.tipo;
    if (!st.tipo) return;
    var bottone = root.querySelector('[data-kc-tipo="' + tipo + '"]');
    var nome = bottone ? bottone.getAttribute('data-kc-nome') : '';
    var q = box.querySelector('[data-kc-q]');
    q.value = '';
    q.setAttribute('aria-label', 'Cerca ' + nome);
    q.placeholder = (tipo === 'macchina' || tipo === 'incontro') ? 'Cerca per codice o nome'
      : tipo === 'fai' ? 'Numero del FAI'
      : 'Codice e descrizione: cerca in catalogo o scrivine uno nuovo';
    cerca(root);
    try { q.focus({ preventScroll: true }); } catch (e) { q.focus(); }
  }

  function cerca(root) {
    var st = stato(root), box = root.querySelector('[data-kc-cerca]');
    if (!box || !st.tipo) return;
    var lista = box.querySelector('[data-kc-ris]');
    var giro = ++st.giro, tipo = st.tipo;
    var url = root.getAttribute('data-cerca') + '?tipo=' + encodeURIComponent(tipo) +
      '&q=' + encodeURIComponent(box.querySelector('[data-kc-q]').value.trim()) +
      '&task=' + encodeURIComponent(root.getAttribute('data-task') || '');
    fetch(url, { headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (giro !== st.giro) return; // è partita una ricerca più recente
        if (!j.ok) { lista.innerHTML = '<li class="kc-vuoto">' + esc(j.reason || 'Ricerca non riuscita.') + '</li>'; return; }
        var scelti = st.attesa.filter(function (v) { return v.tipo === tipo && v.id; }).map(function (v) { return String(v.id); });
        var h = j.risultati.filter(function (r) { return scelti.indexOf(String(r.id)) < 0; }).map(function (r) {
          return '<li><span class="kc-desc"><b class="kc-codice">' + esc(r.codice) + '</b>' + (r.descrizione ? '<small>' + esc(r.descrizione) + '</small>' : '') + '</span>' +
            (r.stato ? '<span class="ts-chip ' + esc(r.tono) + '">' + esc(r.stato) + '</span>' : '') +
            (r.usi ? '<span class="ts-chip">' + esc(r.usi) + '</span>' : '') +
            (r.bloccato ? '' : '<button type="button" class="btn btn-sm" data-kc-collega="' + esc(r.id) + '" data-kc-codice="' + esc(r.codice) + '" data-kc-descrizione="' + esc(r.descrizione) + '">' + (tipo === 'incontro' ? 'Porta all\'ordine del giorno' : 'Collega') + '</button>') +
            '</li>';
        }).join('');
        if (j.nuovo) {
          h += '<li><span class="kc-desc">«<b>' + esc(j.nuovo_testo) + '</b>» ' + esc(j.nuovo_frase) + '</span>' +
            '<button type="button" class="btn btn-secondary btn-sm" data-kc-nuovo="' + esc(j.nuovo_testo) + '">' + esc(j.nuovo_etichetta) + '</button></li>';
        }
        lista.innerHTML = h || '<li class="kc-vuoto">' + esc(j.vuoto) + '</li>';
      })
      .catch(function () { lista.innerHTML = '<li class="kc-vuoto">Ricerca non riuscita.</li>'; });
  }

  /* --- Form «+ Attività»: scelte in attesa del salvataggio --- */
  function disegnaAttesa(root) {
    var st = stato(root), lista = root.querySelector('[data-kc-lista]');
    var campo = root.querySelector('[data-kc-json]');
    if (campo) {
      campo.value = JSON.stringify(st.attesa.map(function (v) {
        return v.id ? { tipo: v.tipo, id: v.id } : { tipo: v.tipo, testo: v.testo };
      }));
    }
    if (!lista) return;
    lista.innerHTML = st.attesa.map(function (v, i) {
      return '<li class="kc-voce"><span class="kc-tipo">' + esc(v.nome) + '</span><span class="kc-desc"><b class="kc-codice">' + esc(v.codice) + '</b>' +
        (v.descrizione ? '<small>' + esc(v.descrizione) + '</small>' : '') + '</span>' +
        (v.testo ? '<span class="ts-chip">nuovo</span>' : '') +
        '<button type="button" class="kc-x" data-kc-togli-attesa="' + i + '" aria-label="Togli ' + esc(v.nome) + ' ' + esc(v.codice) + '">&times;</button></li>';
    }).join('') || '<li class="kc-vuoto" data-kc-vuoto>Nessun collegamento.</li>';
  }
  function mettiInAttesa(root, voce) {
    var st = stato(root);
    // Macchine e programmi possono essere più d'uno; il FAI è uno solo: il nuovo prende il posto del vecchio.
    if (voce.tipo === 'fai') st.attesa = st.attesa.filter(function (v) { return v.tipo !== 'fai'; });
    // Lo stesso codice non entra due volte (doppio clic prima che la ricerca si aggiorni).
    if (st.attesa.some(function (v) { return v.tipo === voce.tipo && (voce.id ? String(v.id) === String(voce.id) : v.testo === voce.testo); })) return;
    st.attesa.push(voce);
    disegnaAttesa(root);
  }
  function nomeTipo(root, tipo) {
    var chip = root.querySelector('[data-kc-tipo="' + tipo + '"]');
    return chip ? chip.getAttribute('data-kc-nome') : '';
  }

  function dopo(root) {
    var q = root.querySelector('[data-kc-q]');
    if (q) { q.value = ''; cerca(root); }
  }

  function clic(e) {
    var el = e.target, root = radice(el), b;
    if (!root) return;
    var st = stato(root), attesa = root.hasAttribute('data-kc-attesa');
    if ((b = el.closest('[data-kc-tipo]'))) { apri(root, b.getAttribute('data-kc-tipo')); return; }
    if ((b = el.closest('[data-kc-collega]'))) {
      if (attesa) {
        mettiInAttesa(root, {
          tipo: st.tipo, nome: nomeTipo(root, st.tipo), id: b.getAttribute('data-kc-collega'),
          codice: b.getAttribute('data-kc-codice'), descrizione: b.getAttribute('data-kc-descrizione')
        });
        dopo(root);
        return;
      }
      b.disabled = true;
      invia(root, { action: 'collega', tipo: st.tipo, id: b.getAttribute('data-kc-collega') }).then(function () { dopo(root); });
      return;
    }
    if ((b = el.closest('[data-kc-nuovo]'))) {
      var testo = b.getAttribute('data-kc-nuovo');
      if (attesa) {
        var parti = testo.trim().split(/\s+/);
        mettiInAttesa(root, { tipo: st.tipo, nome: nomeTipo(root, st.tipo), testo: testo, codice: parti.shift(), descrizione: parti.join(' ') });
        dopo(root);
        return;
      }
      b.disabled = true;
      invia(root, { action: 'aggiungi', tipo: st.tipo, testo: testo }).then(function () { dopo(root); });
      return;
    }
    if ((b = el.closest('[data-kc-togli-attesa]'))) {
      st.attesa.splice(+b.getAttribute('data-kc-togli-attesa'), 1);
      disegnaAttesa(root);
      cerca(root);
      return;
    }
    if ((b = el.closest('[data-kc-togli]'))) {
      b.disabled = true;
      invia(root, { action: 'scollega', chiave: b.closest('[data-kc-voce]').getAttribute('data-kc-voce') }).then(function () { cerca(root); });
      return;
    }
    if ((b = el.closest('[data-kc-modifica]'))) {
      var form = b.closest('[data-kc-voce]').querySelector('[data-kc-form]');
      form.hidden = !form.hidden;
      b.setAttribute('aria-expanded', form.hidden ? 'false' : 'true');
      if (!form.hidden) form.querySelector('[data-kc-code]').focus();
      return;
    }
    if ((b = el.closest('[data-kc-salva]'))) {
      var voce = b.closest('[data-kc-voce]');
      b.disabled = true;
      invia(root, {
        action: 'aggiorna', chiave: voce.getAttribute('data-kc-voce'),
        code: voce.querySelector('[data-kc-code]').value, path: voce.querySelector('[data-kc-path]').value
      }).then(function () { b.disabled = false; });
    }
  }

  function avvia() {
    document.querySelectorAll('[data-kc]').forEach(function (root) {
      if (root.__kcPronto) return;
      root.__kcPronto = true;
      // Arrivando da «Assegna» del Percorso: si apre già sul collegamento che la tappa si aspetta.
      var tipo = root.getAttribute('data-kc-apri');
      if (tipo && root.querySelector('[data-kc-tipo="' + tipo + '"]')) apri(root, tipo);
    });
  }

  if (!window.__kcCollegamenti) {
    window.__kcCollegamenti = true;
    document.addEventListener('click', clic);
    document.addEventListener('input', function (e) {
      var root = e.target.matches && e.target.matches('[data-kc-q]') ? radice(e.target) : null;
      if (!root) return;
      var st = stato(root);
      clearTimeout(st.timer);
      st.timer = setTimeout(function () { cerca(root); }, 180);
    });
    document.addEventListener('change', function (e) {
      var el = e.target;
      if (!el.matches || !el.matches('[data-kc-fase]') || !el.value) return;
      var root = radice(el);
      if (!root) return;
      el.disabled = true;
      invia(root, { action: 'fase', chiave: el.closest('[data-kc-voce]').getAttribute('data-kc-voce'), valore: el.value })
        .then(function (j) { if (!j.ok) { el.disabled = false; el.value = ''; } });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' || !e.target.matches) return;
      var root = radice(e.target);
      if (!root) return;
      if (e.target.matches('[data-kc-q]')) {
        // Invio non manda il form che contiene il riquadro: sceglie la prima riga.
        e.preventDefault();
        var primo = root.querySelector('[data-kc-ris] button');
        if (primo) primo.click();
      } else if (e.target.matches('[data-kc-code], [data-kc-path]')) {
        e.preventDefault();
        var salva = e.target.closest('[data-kc-form]').querySelector('[data-kc-salva]');
        if (salva) salva.click();
      }
    });
  }
  window.kcAvvia = avvia;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', avvia);
  else avvia();
})();
