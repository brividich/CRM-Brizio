/* Conduzione incontro: punti in sequenza, tempi, note in autosave, cattura rapida.
   Estratto dal template tasks/project_meeting_run.html. */
var KO_MEETING_RUN_CFG = (document.currentScript && document.currentScript.dataset) || {};
(function () {
  'use strict';

  const ITEM_URL = KO_MEETING_RUN_CFG.itemUpdateUrl;
  const CAPTURE_URL = KO_MEETING_RUN_CFG.quickCaptureUrl;
  const TASK_CREATE_URL = KO_MEETING_RUN_CFG.itemTaskCreateUrl;
  const TASK_DETAIL_URL_TEMPLATE = KO_MEETING_RUN_CFG.taskDetailUrl;
  const ITEM_DELETE_URL = KO_MEETING_RUN_CFG.itemDeleteUrl;

  let projectTasks = [];
  try {
    const el = document.getElementById('project-tasks-data');
    if (el) projectTasks = JSON.parse(el.textContent) || [];
  } catch (e) { projectTasks = []; }
  const PLANNED = Number(KO_MEETING_RUN_CFG.plannedMinutes || 0);

  /* Una nuova attività entra nei menu di tutti i punti, senza ricaricare. */
  function aggiungiAiMenu(id, titolo) {
    projectTasks.push({ id: id, title: titolo, status: 'TODO' });
    document.querySelectorAll('[data-role=task-select]').forEach(function (sel) {
      const opt = document.createElement('option');
      opt.value = String(id);
      opt.textContent = titolo;
      sel.appendChild(opt);
    });
  }

  function csrfToken() {
    const el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el) return el.value;
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function post(url, data) {
    const body = new URLSearchParams(data);
    return fetch(url, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken(),
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: body.toString(),
    }).then(r => r.json());
  }

  /* Cronometro della riunione: parte all'apertura della pagina. */
  const started = Date.now();
  const elapsedEl = document.getElementById('run-elapsed');
  const overrunEl = document.getElementById('run-overrun');
  setInterval(function () {
    const minutes = Math.floor((Date.now() - started) / 60000);
    if (elapsedEl) elapsedEl.textContent = minutes + ' min';
    if (overrunEl && PLANNED > 0) overrunEl.hidden = minutes <= PLANNED;
  }, 15000);

  function refreshDoneCount() {
    const el = document.getElementById('run-done-count');
    if (el) el.textContent = String(document.querySelectorAll('.run-item.done').length);
  }

  /* Tempo effettivo «live»: il cronometro di un punto parte alla prima modifica (nota, attività,
     nuova attività) e si ferma con «Segna trattato». Un punto alla volta: iniziarne un altro mette
     in pausa il precedente. Resiste al ricaricamento (memoria del browser) e salva ogni minuto. */
  const CRONO_KEY = 'ko-crono:' + (ITEM_URL || location.pathname);
  function cronoLeggi() {
    try { return JSON.parse(localStorage.getItem(CRONO_KEY) || '{}'); } catch (e) { return {}; }
  }
  function cronoScrivi(stato) {
    try { localStorage.setItem(CRONO_KEY, JSON.stringify(stato)); } catch (e) { /* senza memoria vale la sessione */ }
  }
  const crono = cronoLeggi();           /* { itemId: {ms: accumulati, da: inizio|null, manuale: bool} } */
  const cronoCards = {};

  function cronoMs(id) {
    const c = crono[id];
    if (!c) return 0;
    return (c.ms || 0) + (c.da ? Date.now() - c.da : 0);
  }
  function cronoMostra(id) {
    const card = cronoCards[id];
    if (!card) return;
    const ms = cronoMs(id);
    const c = crono[id] || {};
    const badge = card.querySelector('[data-role=crono]');
    const tempo = card.querySelector('[data-role=tempo]');
    if (badge) {
      const sec = Math.floor(ms / 1000);
      badge.hidden = !ms && !c.da;
      badge.textContent = (c.da ? '⏱ ' : '⏸ ') + String(Math.floor(sec / 60)).padStart(2, '0') + ':' + String(sec % 60).padStart(2, '0') + (c.da ? ' in corso' : ' in pausa');
      badge.classList.toggle('is-live', !!c.da);
    }
    if (tempo && !c.manuale && ms) {
      const min = Math.max(1, Math.ceil(ms / 60000));
      if (String(tempo.value) !== String(min)) tempo.value = String(min);
    }
  }
  function cronoSalva(id) {
    const card = cronoCards[id];
    const c = crono[id];
    if (!card || !c || c.manuale) return;
    const min = Math.max(1, Math.ceil(cronoMs(id) / 60000));
    post(ITEM_URL, { item_id: id, tempo_effettivo_minuti: String(min) }).catch(function () {});
  }
  function cronoPausa(id) {
    const c = crono[id];
    if (!c || !c.da) return;
    c.ms = (c.ms || 0) + (Date.now() - c.da);
    c.da = null;
    cronoScrivi(crono);
    cronoMostra(id);
    cronoSalva(id);
  }
  function cronoAvvia(id) {
    const card = cronoCards[id];
    if (!card || card.classList.contains('done')) return;
    const c = crono[id] = crono[id] || { ms: 0, da: null, manuale: false };
    if (c.manuale || c.da) return;
    Object.keys(crono).forEach(function (altro) { if (altro !== id) cronoPausa(altro); });
    c.da = Date.now();
    cronoScrivi(crono);
    cronoMostra(id);
  }
  setInterval(function () { Object.keys(crono).forEach(function (id) { if (crono[id].da) cronoMostra(id); }); }, 1000);
  setInterval(function () { Object.keys(crono).forEach(function (id) { if (crono[id].da) cronoSalva(id); }); }, 60000);
  window.addEventListener('beforeunload', function () { cronoScrivi(crono); });

  /* Un punto per volta: nota in autosave, spunta e tempo effettivo. */
  window.bindRunItem = function (card) {
    const itemId = card.getAttribute('data-item-id');
    const saved = card.querySelector('[data-role=saved]');
    const state = card.querySelector('[data-role=state]');
    const toggle = card.querySelector('[data-role=toggle-done]');
    const nota = card.querySelector('[data-role=nota]');
    const tempo = card.querySelector('[data-role=tempo]');

    function flashSaved() {
      if (!saved) return;
      saved.hidden = false;
      setTimeout(function () { saved.hidden = true; }, 1500);
    }

    cronoCards[itemId] = card;
    /* Badge del cronometro accanto al tempo effettivo. */
    if (tempo && !card.querySelector('[data-role=crono]')) {
      const badge = document.createElement('span');
      badge.className = 'run-crono';
      badge.setAttribute('data-role', 'crono');
      badge.hidden = true;
      const label = tempo.closest('label') || tempo;
      label.insertAdjacentElement('afterend', badge);
      badge.addEventListener('click', function () {
        const c = crono[itemId];
        if (c && c.da) { cronoPausa(itemId); } else { cronoAvvia(itemId); }
      });
      badge.title = 'Clic per mettere in pausa o riprendere';
    }
    cronoMostra(itemId);
    /* Prima modifica di un campo del punto: parte il suo cronometro. */
    card.addEventListener('input', function (e) {
      if (e.target === tempo) return;
      cronoAvvia(itemId);
    });
    card.addEventListener('change', function (e) {
      if (e.target === tempo) return;
      cronoAvvia(itemId);
    });

    let notaTimer = null;
    nota?.addEventListener('input', function () {
      clearTimeout(notaTimer);
      notaTimer = setTimeout(function () {
        post(ITEM_URL, { item_id: itemId, nota: nota.value }).then(flashSaved).catch(function () {});
      }, 800);
    });

    tempo?.addEventListener('change', function (e) {
      /* Scritto a mano: il cronometro di questo punto si ferma e vale il numero inserito. */
      if (e.isTrusted) {
        const c = crono[itemId] = crono[itemId] || { ms: 0, da: null };
        c.manuale = true;
        c.da = null;
        cronoScrivi(crono);
        cronoMostra(itemId);
      }
      post(ITEM_URL, { item_id: itemId, tempo_effettivo_minuti: tempo.value || '0' })
        .then(flashSaved).catch(function () {});
    });

    toggle?.addEventListener('click', function () {
      const next = !card.classList.contains('done');
      /* Trattato: il cronometro si ferma e il tempo viene salvato. */
      if (next) { cronoPausa(itemId); }
      toggle.disabled = true;
      post(ITEM_URL, { item_id: itemId, done: next ? '1' : '0' })
        .then(function (data) {
          if (!data || !data.ok) return;
          card.classList.toggle('done', !!data.done);
          if (state) state.textContent = data.done ? 'Trattato' : 'Da trattare';
          toggle.textContent = data.done ? 'Segna da trattare' : 'Segna trattato';
          refreshDoneCount();
          flashSaved();
        })
        .catch(function () {})
        .finally(function () { toggle.disabled = false; });
    });

    /* ─── Attività collegata al punto ──────────────────────────────── */
    const taskSelect = card.querySelector('[data-role=task-select]');
    const taskLink = card.querySelector('[data-role=task-link]');
    const newBox = card.querySelector('[data-role=task-new]');
    const newTitle = card.querySelector('[data-role=task-new-title]');

    function paintTaskLink(taskId) {
      if (!taskLink) return;
      if (!taskId) { taskLink.hidden = true; taskLink.removeAttribute('href'); taskLink.removeAttribute('data-preview'); return; }
      taskLink.href = TASK_DETAIL_URL_TEMPLATE.replace(/0(\/?)$/, String(taskId) + '$1');
      /* «Apri» mostra la scheda nel pannello laterale: si resta in riunione. */
      taskLink.setAttribute('data-preview', taskLink.href);
      taskLink.hidden = false;
    }

    if (taskSelect) {
      /* Il menu si popola qui e non nel markup: le attività sono le stesse per
         tutti i punti, ripeterle nel template moltiplicherebbe il DOM. */
      projectTasks.forEach(function (t) {
        const opt = document.createElement('option');
        opt.value = String(t.id);
        opt.textContent = t.title;
        taskSelect.appendChild(opt);
      });
      const current = card.getAttribute('data-task-id') || '';
      if (current) taskSelect.value = current;
      paintTaskLink(current);

      taskSelect.addEventListener('change', function () {
        post(ITEM_URL, { item_id: itemId, task_id: taskSelect.value })
          .then(function (data) {
            if (!data || !data.ok) { return; }
            card.setAttribute('data-task-id', data.task_id ? String(data.task_id) : '');
            paintTaskLink(data.task_id);
            flashSaved();
          })
          .catch(function () {});
      });
    }

    card.querySelector('[data-role=task-new-toggle]')?.addEventListener('click', function () {
      if (!newBox) return;
      newBox.hidden = !newBox.hidden;
      if (!newBox.hidden && newTitle) {
        /* Il titolo del punto è quasi sempre il titolo dell'attività: si parte da lì. */
        if (!newTitle.value.trim()) {
          newTitle.value = (card.querySelector('.run-item-title')?.textContent || '').trim();
        }
        newTitle.focus();
      }
    });

    /* Tappa «da assegnare» che in questa riunione non serve: via dall'ordine
       del giorno. Secondo clic entro pochi secondi per confermare, niente finestre. */
    const delBtn = card.querySelector('[data-role=item-delete]');
    let delTimer = null;
    delBtn?.addEventListener('click', function () {
      if (!delBtn.classList.contains('is-confirm')) {
        delBtn.classList.add('is-confirm');
        delBtn.textContent = 'Conferma: elimina il punto';
        delTimer = setTimeout(function () { delBtn.classList.remove('is-confirm'); delBtn.textContent = 'Elimina'; }, 5000);
        return;
      }
      clearTimeout(delTimer);
      delBtn.disabled = true;
      post(ITEM_DELETE_URL, { item_id: itemId }).then(function (data) {
        if (!data || !data.ok) { delBtn.disabled = false; return; }
        if (crono[itemId]) { delete crono[itemId]; cronoScrivi(crono); }
        card.remove();
        document.querySelectorAll('.run-item').forEach(function (c, i) {
          c.setAttribute('data-num', String(i + 1));
          const n = c.querySelector('.run-item-num'); if (n) n.textContent = String(i + 1);
        });
        refreshDoneCount();
      }).catch(function () { delBtn.disabled = false; });
    });

    card.querySelector('[data-role=task-new-cancel]')?.addEventListener('click', function () {
      if (newBox) newBox.hidden = true;
    });

    card.querySelector('[data-role=task-new-save]')?.addEventListener('click', function (ev) {
      const btn = ev.currentTarget;
      const title = newTitle ? newTitle.value.trim() : '';
      if (!title) { newTitle?.focus(); return; }
      btn.disabled = true;
      post(TASK_CREATE_URL, {
        item_id: itemId,
        title: title,
        assigned_to: card.querySelector('[data-role=task-new-owner]')?.value || '',
        next_step_due: card.querySelector('[data-role=task-new-start]')?.value || '',
        due_date: card.querySelector('[data-role=task-new-due]')?.value || '',
        asset: card.querySelector('[data-role=task-new-asset]')?.value || '',
        testo: card.querySelector('[data-role=task-new-testo]')?.value || '',
      }).then(function (data) {
        const err = card.querySelector('[data-role=task-new-err]');
        if (!data || !data.ok) {
          /* Il kickoff bloccato per VRF mancante e' un no motivato, non un
             silenzio: senza messaggio il pulsante sembrava non funzionare. */
          if (err) {
            err.textContent = (data && data.message) || 'Attività non creata.';
            err.hidden = false;
          }
          return;
        }
        if (err) err.hidden = true;
        /* La nuova attività entra anche nei menu degli altri punti: senza
           questo, per collegarla altrove bisognava ricaricare la pagina. */
        aggiungiAiMenu(data.task_id, data.task_label);
        if (taskSelect) taskSelect.value = String(data.task_id);
        card.setAttribute('data-task-id', String(data.task_id));
        paintTaskLink(data.task_id);
        if (newBox) newBox.hidden = true;
        if (newTitle) newTitle.value = '';
        flashSaved();
      }).catch(function () {}).finally(function () { btn.disabled = false; });
    });
  };
  document.querySelectorAll('.run-item').forEach(window.bindRunItem);

  /* Punto aggiunto a riunione in corso: la scheda si costruisce qui, con gli
     stessi ruoli di quelle stampate dal server, e viene subito agganciata. */
  window.MEETING_AGENDA_ADD = {
    onAdded: function (item) {
      const list = document.getElementById('run-items');
      if (!list) { window.location.reload(); return; }
      document.getElementById('run-empty')?.remove();

      const card = document.createElement('article');
      card.className = 'run-item';
      card.setAttribute('data-item-id', item.id);

      const head = document.createElement('header');
      head.className = 'run-item-head';
      const num = document.createElement('span');
      num.className = 'run-item-num';
      num.textContent = list.children.length + 1;
      const title = document.createElement('h3');
      title.className = 'run-item-title';
      title.textContent = item.titolo;
      head.appendChild(num);
      head.appendChild(title);
      if (item.responsabile_label) {
        const who = document.createElement('span');
        who.className = 'mf-issue-chip';
        who.textContent = item.responsabile_label;
        head.appendChild(who);
      }
      if (item.durata_minuti) {
        const mins = document.createElement('span');
        mins.className = 'mf-issue-chip';
        mins.textContent = item.durata_minuti + ' min previsti';
        head.appendChild(mins);
      }
      const state = document.createElement('span');
      state.className = 'run-item-state';
      state.setAttribute('data-role', 'state');
      state.textContent = 'Da trattare';
      head.appendChild(state);

      const nota = document.createElement('textarea');
      nota.className = 'input run-item-nota';
      nota.setAttribute('data-role', 'nota');
      nota.rows = 3;
      nota.placeholder = 'Cosa \u00e8 emerso su questo punto (si salva da solo)';

      const actions = document.createElement('div');
      actions.className = 'run-item-actions';
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'mf-btn-sm primary';
      toggle.setAttribute('data-role', 'toggle-done');
      toggle.textContent = 'Segna trattato';
      const tempoLabel = document.createElement('label');
      tempoLabel.className = 'tpl-inline';
      tempoLabel.textContent = 'Tempo ';
      const tempo = document.createElement('input');
      tempo.className = 'input';
      tempo.type = 'number';
      tempo.min = '1';
      tempo.max = '480';
      tempo.style.width = '72px';
      tempo.setAttribute('data-role', 'tempo');
      tempoLabel.appendChild(tempo);
      tempoLabel.appendChild(document.createTextNode(' min'));
      const saved = document.createElement('span');
      saved.className = 'run-item-saved';
      saved.setAttribute('data-role', 'saved');
      saved.hidden = true;
      actions.appendChild(toggle);
      actions.appendChild(tempoLabel);
      actions.appendChild(saved);

      const addTpl = document.getElementById('run-item-add-template');
      if (addTpl) actions.appendChild(addTpl.content.cloneNode(true));
      card.setAttribute('data-num', String(list.children.length + 1));
      card.id = 'punto-' + item.id;

      card.appendChild(head);
      card.appendChild(nota);
      const taskBox = document.getElementById('run-task-box-template');
      if (taskBox) card.appendChild(taskBox.content.cloneNode(true));
      card.appendChild(actions);
      list.appendChild(card);
      window.bindRunItem(card);
      /* Il punto nuovo si può scegliere anche nel registro dell'incontro. */
      const sel = document.getElementById('capture-punto');
      if (sel) {
        const opt = document.createElement('option');
        opt.value = item.id;
        opt.textContent = list.children.length + '. ' + item.titolo;
        sel.appendChild(opt);
      }
      nota.focus();
    }
  };

  /* ─── Registro dell'incontro ──────────────────────────────────────
     Problemi, azioni, decisioni e attività registrati mentre si parla,
     legati al punto in discussione (l'ultimo toccato o quello scelto). */
  const impattoEl = document.getElementById('capture-impatto');
  const dueEl = document.getElementById('capture-due');
  const puntoEl = document.getElementById('capture-punto');
  const titoloEl = document.getElementById('capture-titolo');
  const KIND_UI = {
    issue: { list: 'cat-problema', ph: 'Cosa non torna? Scrivi e premi Invio' },
    action: { list: 'cat-azione', ph: 'Chi fa cosa? Scrivi e premi Invio' },
    decision: { list: '', ph: 'Cosa è stato deciso? Scrivi e premi Invio' },
    task: { list: 'cat-attivita', ph: 'Nuova attività del piano: scrivi e premi Invio' },
  };

  function getKind() {
    const el = document.querySelector('input[name=capture-kind]:checked');
    return el ? el.value : 'issue';
  }
  function setKind(kind) {
    const el = document.querySelector('input[name=capture-kind][value="' + kind + '"]');
    if (el) { el.checked = true; syncCaptureFields(); }
  }
  function syncCaptureFields() {
    const kind = getKind();
    const isDecision = kind === 'decision';
    if (impattoEl) impattoEl.hidden = !isDecision;
    if (dueEl) dueEl.hidden = isDecision;
    const ui = KIND_UI[kind] || KIND_UI.issue;
    if (titoloEl) {
      titoloEl.placeholder = ui.ph;
      if (ui.list) titoloEl.setAttribute('list', ui.list); else titoloEl.removeAttribute('list');
    }
  }
  document.querySelectorAll('input[name=capture-kind]').forEach(function (el) {
    el.addEventListener('change', syncCaptureFields);
  });
  syncCaptureFields();

  /* Punto in discussione: l'ultimo su cui si è scritto o cliccato. */
  function segnaCorrente(card) {
    document.querySelectorAll('.run-item.is-current').forEach(function (c) { if (c !== card) c.classList.remove('is-current'); });
    card.classList.add('is-current');
    if (puntoEl) puntoEl.value = card.getAttribute('data-item-id') || '';
  }
  document.getElementById('run-items')?.addEventListener('focusin', function (ev) {
    const card = ev.target.closest('.run-item');
    if (card) segnaCorrente(card);
  });

  function testo(tag, cls, value) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value != null) el.textContent = value;
    return el;
  }

  /* Riga «voce» costruita qui con le stesse classi di _meeting_voce.html. */
  function voceLi(voce, mostraPunto) {
    const li = testo('li', 'mvoce mvoce--' + voce.kind + (voce.chiusa ? ' is-closed' : ''));
    li.setAttribute('data-voce', voce.kind + '-' + voce.id);
    li.appendChild(testo('span', 'mvoce-tipo', voce.label));
    const main = testo('span', 'mvoce-main');
    main.appendChild(testo('span', 'mvoce-titolo', voce.titolo));
    const meta = testo('span', 'mvoce-meta');
    if (voce.chi) meta.appendChild(testo('span', '', voce.chi));
    if (voce.scadenza) meta.appendChild(testo('span', '', 'entro ' + voce.scadenza.slice(0, 5)));
    if (mostraPunto && voce.punto_num) {
      const p = testo('span', 'mvoce-punto', 'punto ' + voce.punto_num);
      p.title = voce.punto_titolo || '';
      meta.appendChild(p);
    }
    meta.appendChild(testo('span', 'mvoce-stato', voce.stato));
    main.appendChild(meta);
    li.appendChild(main);
    if (voce.url && voce.kind !== 'decision') {
      const btn = testo('button', 'mf-btn-sm primary', voce.kind === 'issue' ? 'Risolto' : 'Fatta');
      btn.type = 'button';
      btn.setAttribute('data-voce-toggle', '');
      btn.setAttribute('data-url', voce.url);
      btn.setAttribute('data-kind', voce.kind);
      btn.setAttribute('data-chiusa', '0');
      li.appendChild(btn);
    }
    return li;
  }

  function aggiornaConteggio(kind, delta) {
    const el = document.getElementById('reg-count-' + kind);
    if (el) el.textContent = String(Number(el.textContent || 0) + delta);
    const tot = document.getElementById('reg-totale');
    if (tot) {
      const n = document.querySelectorAll('#run-registro .run-reg-group li').length;
      tot.textContent = n + (n === 1 ? ' voce' : ' voci');
    }
  }

  function registraCattura() {
    const ownerEl = document.getElementById('capture-owner');
    const errEl = document.getElementById('capture-err');
    const titolo = titoloEl ? titoloEl.value.trim() : '';
    if (!titolo) { titoloEl?.focus(); return; }
    const kind = getKind();
    const punto = puntoEl ? puntoEl.value : '';
    post(CAPTURE_URL, {
      kind: kind,
      titolo: titolo,
      item_id: punto,
      owner_id: ownerEl ? ownerEl.value : '',
      due_date: dueEl && !dueEl.hidden ? dueEl.value : '',
      impatto: impattoEl && !impattoEl.hidden ? impattoEl.value : '',
    }).then(function (data) {
      if (!data || !data.ok) {
        if (errEl) {
          errEl.textContent = (data && data.message) || 'Non registrato: riprova.';
          errEl.hidden = false;
        }
        return;
      }
      if (errEl) errEl.hidden = true;
      const card = data.punto ? document.querySelector('.run-item[data-item-id="' + CSS.escape(data.punto) + '"]') : null;
      if (data.kind === 'task') {
        aggiungiAiMenu(data.id, data.titolo);
        const group = document.getElementById('reg-task-group');
        if (group) group.hidden = false;
        document.getElementById('reg-task')?.appendChild(voceLi({ kind: 'task', id: data.id, label: 'Attività', titolo: data.titolo, stato: 'Nel piano', punto_num: card ? card.getAttribute('data-num') : null }, true));
        aggiornaConteggio('task', 1);
        if (card && data.task_collegata) {
          const sel = card.querySelector('[data-role=task-select]');
          if (sel) sel.value = String(data.id);
          card.setAttribute('data-task-id', String(data.id));
          const link = card.querySelector('[data-role=task-link]');
          if (link) { link.href = TASK_DETAIL_URL_TEMPLATE.replace(/0(\/?)$/, String(data.id) + '$1'); link.setAttribute('data-preview', link.href); link.hidden = false; }
        }
      } else if (data.voce) {
        document.getElementById('reg-' + data.kind)?.appendChild(voceLi(data.voce, true));
        aggiornaConteggio(data.kind, 1);
        if (card) {
          const ul = card.querySelector('[data-role=emersi]');
          if (ul) { ul.appendChild(voceLi(data.voce, false)); ul.hidden = false; }
          cronoAvvia(card.getAttribute('data-item-id'));
        }
      }
      if (titoloEl) titoloEl.value = '';
      if (dueEl) dueEl.value = '';
      titoloEl?.focus();
    }).catch(function () {
      if (errEl) {
        errEl.textContent = 'Connessione assente: non registrato.';
        errEl.hidden = false;
      }
    });
  }

  document.getElementById('capture-save')?.addEventListener('click', registraCattura);
  titoloEl?.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { ev.preventDefault(); registraCattura(); }
  });

  /* «+ Problema / + Azione / + Decisione» su un punto: il registro si prepara per quel punto. */
  document.getElementById('run-items')?.addEventListener('click', function (ev) {
    const btn = ev.target.closest('[data-capture]');
    if (!btn) return;
    const card = btn.closest('.run-item');
    if (card) segnaCorrente(card);
    setKind(btn.getAttribute('data-capture'));
    const box = document.getElementById('run-capture');
    if (box && window.matchMedia('(max-width: 1100px)').matches) box.scrollIntoView({ behavior: 'smooth', block: 'center' });
    titoloEl?.focus({ preventScroll: true });
  });

  /* Chiudere o riaprire un problema/un'azione senza lasciare la pagina. */
  document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('[data-voce-toggle]');
    if (!btn) return;
    const kind = btn.getAttribute('data-kind');
    const chiusa = btn.getAttribute('data-chiusa') === '1';
    const azione = chiusa ? 'reopen' : (kind === 'issue' ? 'resolve' : 'done');
    const li = btn.closest('[data-voce]');
    const key = li ? li.getAttribute('data-voce') : '';
    btn.disabled = true;
    post(btn.getAttribute('data-url'), { action: azione }).then(function (data) {
      if (!data || !data.ok) return;
      document.querySelectorAll('[data-voce="' + key + '"]').forEach(function (row) {
        row.classList.toggle('is-closed', !!data.chiusa);
        const stato = row.querySelector('.mvoce-stato');
        if (stato) stato.textContent = data.stato;
        const b = row.querySelector('[data-voce-toggle]');
        if (b) {
          b.setAttribute('data-chiusa', data.chiusa ? '1' : '0');
          b.textContent = data.chiusa ? 'Riapri' : (kind === 'issue' ? 'Risolto' : 'Fatta');
          b.classList.toggle('primary', !data.chiusa);
          b.classList.toggle('ghost', !!data.chiusa);
        }
        /* Il punto che riporta il problema o l'azione segue il loro stato. */
        if (row.parentElement && row.parentElement.classList.contains('run-collegata')) {
          const card = row.closest('.run-item');
          if (card) {
            card.classList.toggle('done', !!data.chiusa);
            const st = card.querySelector('[data-role=state]');
            if (st) st.textContent = data.chiusa ? 'Trattato' : 'Da trattare';
            const tg = card.querySelector('[data-role=toggle-done]');
            if (tg) tg.textContent = data.chiusa ? 'Segna da trattare' : 'Segna trattato';
            if (data.chiusa) cronoPausa(card.getAttribute('data-item-id'));
            refreshDoneCount();
          }
        }
      });
    }).catch(function () {}).finally(function () { btn.disabled = false; });
  });
})();
