/* Gantt di commessa: zoom, trascinamento delle barre (mouse, dito, penna), dipendenze.
   Dopo il rilascio la pagina NON si ricarica: il server risponde in JSON con lo stato
   del diagramma e lo script aggiorna barre, date e numeri sul posto. Se il periodo
   mostrato cambia, rilegge la pagina via fetch e sostituisce solo le parti segnate
   con data-g-region. I messaggi passano dai toast del portale (core/js/hub-flash.js). */
(function () {
  var root = document.querySelector('.ts-gantt-cm');
  if (!root) return;
  var zoom = document.getElementById('g_zoom_cm');
  var cascadeEl = document.getElementById('g_cascade_cm');
  var GIORNO = 86400000;

  function sc() { return root.querySelector('.gscroll'); }
  function cw() { var s = sc(); return (s && parseInt(getComputedStyle(s).getPropertyValue('--cw'), 10)) || 30; }
  function csrf() {
    var m = document.querySelector("meta[name='csrf-token']");
    if (m) return m.getAttribute('content');
    var i = document.querySelector('[name=csrfmiddlewaretoken]');
    return i ? i.value : '';
  }
  function leftCalc(idx) { return 'calc(var(--cw) * ' + idx + ')'; }
  function widthCalc(span) { return 'calc(var(--cw) * ' + span + ' - 4px)'; }
  function avviso(livello, testo) {
    if (window.hubFlash) window.hubFlash.show([{ level: livello, text: testo }]);
    else if (window.console) console.warn(testo);
  }
  function giorno(iso) {
    if (!iso) return null;
    var p = iso.split('-');
    return Math.round(Date.UTC(+p[0], +p[1] - 1, +p[2]) / GIORNO);
  }
  function riga(id) { return root.querySelector('.grow.gbody[data-task-id="' + id + '"]'); }
  function posiziona(bar, start, span) { bar.style.left = leftCalc(start); bar.style.width = widthCalc(span); }

  // Il periodo riempie la larghezza disponibile: prima a schermo largo restava mezzo pannello vuoto.
  (function adatta() {
    var scroll = sc();
    if (!scroll) return;
    var head = scroll.querySelector('.ghead .gtrack');
    var mac = scroll.querySelector('.ghead .gmac');
    var giorni = head ? head.children.length : 0;
    if (!giorni || !mac) return;
    var libero = scroll.clientWidth - mac.offsetWidth - 2;
    var ideale = Math.min(64, Math.floor(libero / giorni));
    if (ideale > cw()) {
      scroll.style.setProperty('--cw', ideale + 'px');
      if (zoom) zoom.value = ideale;
    }
  })();

  // Zoom live (non ricarica)
  if (zoom) zoom.addEventListener('input', function () { var s = sc(); if (s) s.style.setProperty('--cw', zoom.value + 'px'); });

  // ── Piano in memoria: serve all'anteprima mentre si trascina ──
  // Stesse regole di tasks/services/gantt_piano.py (inizio_minimo, propaga_dipendenze):
  // il server resta l'unico che decide, qui si mostra solo cosa succederà.
  function leggiPiano() {
    var piano = { att: {}, deps: [] };
    var scroll = sc();
    try { piano.deps = JSON.parse((scroll && scroll.getAttribute('data-deps')) || '[]'); } catch (e) { piano.deps = []; }
    root.querySelectorAll('.grow.gbody[data-task-id]').forEach(function (r) {
      var bar = r.querySelector('.gbar');
      if (!bar) return;
      piano.att[r.getAttribute('data-task-id')] = {
        ini: giorno(r.getAttribute('data-ini')), fin: giorno(r.getAttribute('data-fin')),
        stato: r.getAttribute('data-stato') || '', bar: bar,
        start: parseInt(bar.getAttribute('data-start'), 10) || 0,
        span: parseInt(bar.getAttribute('data-span'), 10) || 1,
      };
    });
    return piano;
  }
  function inizioDi(a) { return a.ini !== null ? a.ini : a.fin; }
  function fineDi(a) { return a.fin !== null ? a.fin : a.ini; }
  function inizioMinimo(id, att, deps) {
    var a = att[id], ini = inizioDi(a), fin = fineDi(a);
    var durata = (ini !== null && fin !== null) ? fin - ini : 0;
    var minimo = null;
    deps.forEach(function (d) {
      if (String(d.s) !== String(id)) return;
      var p = att[d.p];
      if (!p || p.stato === 'CANCELED') return;
      var pIni = inizioDi(p), pFin = fineDi(p);
      if (pIni === null) return;
      var lag = d.lag || 0, c;
      if (d.t === 'SS') c = pIni + lag;
      else if (d.t === 'FF') c = pFin + lag - durata;
      else if (d.t === 'SF') c = pIni + lag - durata;
      else c = pFin + 1 + lag;
      if (minimo === null || c > minimo) minimo = c;
    });
    return minimo;
  }
  // Giorni di slittamento in avanti di ogni successiva (solo in avanti, chiuse escluse).
  function cascata(idMosso, att, deps) {
    var spinte = {}, coda = [String(idMosso)], passi = 0;
    var n = Object.keys(att).length, limite = Math.max(10, n * n);
    while (coda.length && passi < limite) {
      passi += 1;
      var corrente = coda.shift();
      deps.forEach(function (d) {
        if (String(d.p) !== corrente) return;
        var s = att[d.s];
        if (!s || s.stato === 'DONE' || s.stato === 'CANCELED') return;
        var minimo = inizioMinimo(d.s, att, deps), ini = inizioDi(s);
        if (minimo === null || ini === null || ini >= minimo) return;
        var gg = minimo - ini;
        if (s.ini !== null) s.ini += gg;
        if (s.fin !== null) s.fin += gg;
        spinte[d.s] = (spinte[d.s] || 0) + gg;
        coda.push(String(d.s));
      });
    }
    return spinte;
  }
  function copia(att) {
    var c = {};
    Object.keys(att).forEach(function (k) { var a = att[k]; c[k] = { ini: a.ini, fin: a.fin, stato: a.stato }; });
    return c;
  }

  // ── Trascinamento (Pointer Events: mouse, dito, penna) ──
  var drag = null;
  var salvataggio = false;
  var fineTrascinamento = 0;

  function modo(g) { return g.edge === 'start' ? 'resize_start' : (g.edge === 'end' ? 'resize_end' : 'shift'); }

  // Stessi limiti del server: non prima del vincolo «dopo …», la fine non scavalca l'inizio.
  function limita(g, d) {
    var a = g.piano.att[g.id];
    if (!a) return d;
    var ini = inizioDi(a), fin = fineDi(a);
    if (g.edge !== 'end' && g.minimo !== null && ini !== null && d < g.minimo - ini) d = g.minimo - ini;
    if (g.edge === 'start' && ini !== null && fin !== null) d = Math.min(d, fin - ini);
    if (g.edge === 'end' && ini !== null && fin !== null) d = Math.max(d, ini - fin);
    return d;
  }

  function anteprima(g, d) {
    if (g.edge === 'start') {
      var dd = Math.min(d, g.origSpan - 1);
      posiziona(g.bar, g.origStart + dd, g.origSpan - dd);
    } else if (g.edge === 'end') {
      posiziona(g.bar, g.origStart, Math.max(1, g.origSpan + d));
    } else {
      posiziona(g.bar, g.origStart + d, g.origSpan);
    }
    // Le barre collegate che verrebbero spinte seguono già durante il trascinamento.
    var spinte = {};
    if (d && cascadeEl && cascadeEl.checked && g.piano.deps.length) {
      var att = copia(g.piano.att), a = att[g.id];
      if (g.edge === 'start') a.ini = inizioDi(a) + d;
      else if (g.edge === 'end') a.fin = fineDi(a) + d;
      else { if (a.ini !== null) a.ini += d; if (a.fin !== null) a.fin += d; }
      spinte = cascata(g.id, att, g.piano.deps);
    }
    Object.keys(g.piano.att).forEach(function (id) {
      if (id === g.id) return;
      var o = g.piano.att[id], gg = spinte[id] || 0;
      if (!gg && !o.bar.classList.contains('is-anteprima')) return;
      // Senza data di inizio il server sposta solo la fine: la barra si allunga.
      if (o.ini !== null) posiziona(o.bar, o.start + gg, o.span);
      else posiziona(o.bar, o.start, o.span + gg);
      o.bar.classList.toggle('is-anteprima', gg > 0);
    });
  }

  function ripristina(g) {
    Object.keys(g.piano.att).forEach(function (id) {
      var o = g.piano.att[id];
      o.bar.classList.remove('is-anteprima');
      posiziona(o.bar, o.start, o.span);
    });
  }

  function chiudi(g) {
    g.bar.classList.remove('dragging');
    document.body.classList.remove('g-trascina');
    try { g.bar.releasePointerCapture(g.pid); } catch (e) { /* già rilasciato */ }
  }

  root.addEventListener('pointerdown', function (e) {
    if (drag || salvataggio) return;
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    var bar = e.target.closest('.gbar');
    if (!bar) return;
    var row = bar.closest('.grow.gbody');
    if (!row || !row.getAttribute('data-shift-url')) return;
    e.preventDefault();
    var piano = leggiPiano();
    var id = row.getAttribute('data-task-id');
    drag = {
      bar: bar, row: row, id: id, pid: e.pointerId, piano: piano, startX: e.clientX, giorni: 0,
      edge: e.target.classList.contains('ghandle') ? e.target.getAttribute('data-edge') : null,
      origStart: parseInt(bar.getAttribute('data-start'), 10) || 0,
      origSpan: parseInt(bar.getAttribute('data-span'), 10) || 1,
      minimo: piano.att[id] ? inizioMinimo(id, piano.att, piano.deps) : null,
      w: cw(),
    };
    // La barra tiene il puntatore: su telefono e tablet la pagina non scorre mentre si trascina.
    try { bar.setPointerCapture(e.pointerId); } catch (err) { /* puntatore non catturabile */ }
    bar.classList.add('dragging');
    document.body.classList.add('g-trascina');
  });

  document.addEventListener('pointermove', function (e) {
    if (!drag || e.pointerId !== drag.pid) return;
    var d = limita(drag, Math.round((e.clientX - drag.startX) / drag.w));
    if (d === drag.giorni) return;
    drag.giorni = d;
    anteprima(drag, d);
  });

  function rilascio(e, annulla) {
    if (!drag || (e && e.pointerId !== undefined && e.pointerId !== drag.pid)) return;
    var g = drag; drag = null;
    chiudi(g);
    var days = annulla ? 0 : limita(g, Math.round((e.clientX - g.startX) / g.w));
    if (!days) { ripristina(g); return; }
    fineTrascinamento = Date.now();
    salva(g, days);
  }
  document.addEventListener('pointerup', function (e) { rilascio(e, false); });
  document.addEventListener('pointercancel', function (e) { rilascio(e, true); });
  document.addEventListener('keydown', function (e) { if (drag && e.key === 'Escape') rilascio(null, true); });
  // Niente trascinamento nativo (selezione o immagine fantasma) sulle barre.
  root.addEventListener('dragstart', function (e) { if (e.target.closest && e.target.closest('.gbar')) e.preventDefault(); });

  // ── Salvataggio senza ricarica ──
  function salva(g, days) {
    var casc = cascadeEl ? (cascadeEl.checked ? '1' : '0') : '0';
    var salvato = false;
    salvataggio = true;
    g.bar.classList.add('is-salvando');
    fetch(g.row.getAttribute('data-shift-url') + window.location.search, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
      body: new URLSearchParams({ mode: modo(g), shift_days: days, cascade: casc }).toString(),
    }).then(function (r) {
      var daHeader = !!r.headers.get('X-Hub-Flash');
      return r.json().then(function (j) { return { j: j, daHeader: daHeader }; });
    }).then(function (esito) {
      var j = esito.j;
      if (!j || !j.ok) {
        ripristina(g);
        avviso('error', (j && j.messaggio) || 'Spostamento non salvato.');
        return null;
      }
      if (j.richiesta) {
        // L'incaricato non sposta: nasce una richiesta e la barra torna al suo posto.
        ripristina(g);
        if (!esito.daHeader && j.messaggio) avviso('info', j.messaggio);
        return null;
      }
      salvato = true;
      if (!applica(j, g)) return rileggi();
      return null;
    }).catch(function () {
      if (salvato) {
        // Salvato ma non mostrabile: ultima spiaggia, si ricarica la pagina.
        window.location.reload();
        return;
      }
      ripristina(g);
      avviso('error', 'Spostamento non salvato: errore di rete. Riprova.');
    }).then(function () {
      salvataggio = false;
      g.bar.classList.remove('is-salvando');
    });
  }

  // Aggiorna sul posto barre, date nelle righe, numeri in testa e modifica rapida.
  // False = il periodo mostrato è cambiato (o manca una riga): va riletto il diagramma.
  function applica(j, g) {
    var scroll = sc();
    if (!scroll || !j.finestra || !j.righe) return false;
    if (scroll.getAttribute('data-inizio') !== j.finestra.inizio ||
        String(scroll.getAttribute('data-giorni')) !== String(j.finestra.giorni)) return false;
    if (j.righe.length !== root.querySelectorAll('.grow.gbody[data-task-id]').length) return false;
    for (var i = 0; i < j.righe.length; i++) { if (!riga(j.righe[i].id)) return false; }
    if (g) ripristina(g);
    j.righe.forEach(function (r) {
      var row = riga(r.id), bar = row.querySelector('.gbar');
      row.setAttribute('data-ini', r.inizio);
      row.setAttribute('data-fin', r.fine);
      if (bar) {
        bar.setAttribute('data-start', r.start_index);
        bar.setAttribute('data-span', r.span);
        posiziona(bar, r.start_index, r.span);
        bar.setAttribute('title', r.titolo);
        bar.classList.toggle('is-overdue', !!r.scaduta);
        bar.classList.toggle('is-invalid-range', !!r.date_invertite);
      }
      var meta = row.querySelector('[data-g-meta]');
      if (meta && meta.innerHTML.trim() !== r.meta_html.trim()) meta.innerHTML = r.meta_html;
    });
    (j.attivita || []).forEach(function (a) {
      var row = riga(a.id), bar = row && row.querySelector('.gbar');
      if (bar) {
        bar.classList.remove('is-spostata');
        void bar.offsetWidth; // fa ripartire l'animazione
        bar.classList.add('is-spostata');
      }
      // Modifica rapida: le date del modulo seguono la barra.
      var ini = document.getElementById('id_task_' + a.id + '-next_step_due');
      var fin = document.getElementById('id_task_' + a.id + '-due_date');
      if (ini) ini.value = a.inizio;
      if (fin) fin.value = a.fine;
    });
    Object.keys(j.numeri || {}).forEach(function (k) {
      var el = document.querySelector('[data-g-num="' + k + '"]');
      if (el) el.textContent = j.numeri[k];
    });
    return true;
  }

  // Rilegge la pagina via fetch e sostituisce solo le parti che dipendono dal piano.
  function rileggi() {
    return fetch(window.location.href, { credentials: 'same-origin', headers: { 'Accept': 'text/html' } })
      .then(function (r) {
        if (!r.ok) throw new Error('pagina non letta');
        return r.text();
      })
      .then(function (html) {
        var nuovo = new DOMParser().parseFromString(html, 'text/html');
        if (!nuovo.querySelector('[data-g-region="diagramma"]')) throw new Error('diagramma mancante');
        var scroll = sc();
        var prima = scroll ? {
          cw: scroll.style.getPropertyValue('--cw'), left: scroll.scrollLeft, top: scroll.scrollTop,
          inizio: giorno(scroll.getAttribute('data-inizio')), w: cw(),
        } : null;
        var scelta = root.querySelector('.grow.gbody.is-selected');
        var sceltaId = scelta ? scelta.getAttribute('data-task-id') : null;
        document.querySelectorAll('[data-g-region]').forEach(function (vecchio) {
          var n = nuovo.querySelector('[data-g-region="' + vecchio.getAttribute('data-g-region') + '"]');
          if (!n) return;
          if (vecchio.tagName === 'DETAILS' && n.hasAttribute('open')) vecchio.setAttribute('open', '');
          vecchio.innerHTML = n.innerHTML;
        });
        var dopo = sc();
        if (dopo && prima) {
          if (prima.cw) dopo.style.setProperty('--cw', prima.cw);
          // Se il periodo parte prima o dopo, la vista resta sugli stessi giorni.
          var scarto = (prima.inizio !== null) ? prima.inizio - giorno(dopo.getAttribute('data-inizio')) : 0;
          dopo.scrollLeft = Math.max(0, prima.left + scarto * prima.w);
          dopo.scrollTop = prima.top;
        }
        if (sceltaId) selectTask(sceltaId);
      });
  }
  // Usata anche dalle dipendenze (sotto): aggiorna senza ricaricare, ricarica solo se non riesce.
  window.ganttRileggi = function () {
    return rileggi().catch(function () { window.location.reload(); });
  };

  // ── Click riga -> modifica rapida ──
  function selectTask(taskId) {
    var placeholder = document.getElementById('quick-edit-placeholder');
    document.querySelectorAll('.quick-edit-item[data-task-id]').forEach(function (f) {
      f.classList.toggle('is-visible', taskId !== null && f.dataset.taskId === String(taskId));
    });
    if (placeholder) placeholder.style.display = taskId ? 'none' : '';
    root.querySelectorAll('.grow.gbody').forEach(function (r) {
      r.classList.toggle('is-selected', taskId !== null && r.getAttribute('data-task-id') === String(taskId));
    });
  }
  root.addEventListener('click', function (e) {
    // Il rilascio di un trascinamento non è un clic sulla riga.
    if (Date.now() - fineTrascinamento < 400) return;
    if (e.target.closest('a, button, .gord') || e.target.classList.contains('ghandle')) return;
    var row = e.target.closest('.grow.gbody');
    // Tutta la riga apre la modifica rapida, non solo la barra (prima bisognava centrarla).
    if (!row) return;
    var taskId = row.getAttribute('data-task-id');
    if (!document.querySelector('.quick-edit-item[data-task-id="' + String(taskId) + '"]')) return;
    var already = row.classList.contains('is-selected');
    selectTask(already ? null : taskId);
    if (!already) {
      var sec = document.querySelector('.quick-edit-item.is-visible') || document.querySelector('.quick-edit-grid');
      if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  });

  // Scroll automatico alla colonna di OGGI
  (function () {
    var scroll = sc();
    if (!scroll) return;
    var oggi = parseInt(scroll.getAttribute('data-oggi-idx'), 10);
    if (oggi >= 0) { var w0 = cw(); scroll.scrollLeft = Math.max(0, oggi * w0 - 3 * w0); }
  })();
})();

// ── Dipendenze AJAX ──────────────────────────────────
function getCsrfToken() {
  const el = document.querySelector("[name=csrfmiddlewaretoken]");
  return el ? el.value : "";
}

function ganttAvviso(livello, testo) {
  if (window.hubFlash) window.hubFlash.show([{ level: livello, text: testo }]);
}

function ganttDopoDipendenza() {
  if (window.ganttRileggi) return window.ganttRileggi();
  window.location.reload();
}

async function addDependency(event, form) {
  event.preventDefault();
  const url = form.dataset.addUrl;
  const data = new FormData(form);
  const body = new URLSearchParams(data);
  try {
    const resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": getCsrfToken(), "X-Requested-With": "XMLHttpRequest" },
      body: body.toString(),
    });
    const json = await resp.json();
    if (json.ok) {
      await ganttDopoDipendenza();
    } else {
      ganttAvviso("error", json.error || "Dipendenza non aggiunta.");
    }
  } catch (e) {
    ganttAvviso("error", "Dipendenza non aggiunta: errore di rete. Riprova.");
  }
}

async function removeDependency(btn) {
  const url = btn.dataset.removeUrl;
  if (!url) return;
  if (!(await hubConfirm("Rimuovere questa dipendenza?"))) return;
  try {
    const resp = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": getCsrfToken(), "X-Requested-With": "XMLHttpRequest" },
      body: new URLSearchParams({ csrfmiddlewaretoken: getCsrfToken() }).toString(),
    });
    const json = await resp.json();
    if (json.ok) {
      await ganttDopoDipendenza();
    } else {
      ganttAvviso("error", json.error || "Dipendenza non rimossa.");
    }
  } catch (e) {
    ganttAvviso("error", "Dipendenza non rimossa: errore di rete. Riprova.");
  }
}
