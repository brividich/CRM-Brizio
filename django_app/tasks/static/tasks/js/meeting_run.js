/* Conduzione incontro: punti in sequenza, tempi, note in autosave, cattura rapida.
   Estratto dal template tasks/project_meeting_run.html. */
var KO_MEETING_RUN_CFG = (document.currentScript && document.currentScript.dataset) || {};
(function () {
  'use strict';

  const ITEM_URL = KO_MEETING_RUN_CFG.itemUpdateUrl;
  const CAPTURE_URL = KO_MEETING_RUN_CFG.quickCaptureUrl;
  const TASK_CREATE_URL = KO_MEETING_RUN_CFG.itemTaskCreateUrl;
  const TASK_DETAIL_URL_TEMPLATE = KO_MEETING_RUN_CFG.taskDetailUrl;

  let projectTasks = [];
  try {
    const el = document.getElementById('project-tasks-data');
    if (el) projectTasks = JSON.parse(el.textContent) || [];
  } catch (e) { projectTasks = []; }
  const PLANNED = Number(KO_MEETING_RUN_CFG.plannedMinutes || 0);

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

    let notaTimer = null;
    nota?.addEventListener('input', function () {
      clearTimeout(notaTimer);
      notaTimer = setTimeout(function () {
        post(ITEM_URL, { item_id: itemId, nota: nota.value }).then(flashSaved).catch(function () {});
      }, 800);
    });

    tempo?.addEventListener('change', function () {
      post(ITEM_URL, { item_id: itemId, tempo_effettivo_minuti: tempo.value || '0' })
        .then(flashSaved).catch(function () {});
    });

    toggle?.addEventListener('click', function () {
      const next = !card.classList.contains('done');
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
      if (!taskId) { taskLink.hidden = true; taskLink.removeAttribute('href'); return; }
      taskLink.href = TASK_DETAIL_URL_TEMPLATE.replace(/0(\/?)$/, String(taskId) + '$1');
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
        due_date: card.querySelector('[data-role=task-new-due]')?.value || '',
        priority: card.querySelector('[data-role=task-new-priority]')?.value || 'MEDIUM',
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
        projectTasks.push({ id: data.task_id, title: data.task_label, status: 'TODO' });
        document.querySelectorAll('[data-role=task-select]').forEach(function (sel) {
          const opt = document.createElement('option');
          opt.value = String(data.task_id);
          opt.textContent = data.task_label;
          sel.appendChild(opt);
        });
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
      tempoLabel.textContent = 'Tempo effettivo ';
      const tempo = document.createElement('input');
      tempo.className = 'input';
      tempo.type = 'number';
      tempo.min = '1';
      tempo.max = '480';
      tempo.style.width = '80px';
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

      card.appendChild(head);
      card.appendChild(nota);
      const taskBox = document.getElementById('run-task-box-template');
      if (taskBox) card.appendChild(taskBox.content.cloneNode(true));
      card.appendChild(actions);
      list.appendChild(card);
      window.bindRunItem(card);
      nota.focus();
    }
  };

  /* Cattura rapida */
  const kindEl = document.getElementById('capture-kind');
  const impattoEl = document.getElementById('capture-impatto');
  const dueEl = document.getElementById('capture-due');

  function syncCaptureFields() {
    const isDecision = kindEl && kindEl.value === 'decision';
    if (impattoEl) impattoEl.hidden = !isDecision;
    if (dueEl) dueEl.hidden = isDecision;
  }
  kindEl?.addEventListener('change', syncCaptureFields);
  syncCaptureFields();

  document.getElementById('capture-save')?.addEventListener('click', function () {
    const titoloEl = document.getElementById('capture-titolo');
    const ownerEl = document.getElementById('capture-owner');
    const titolo = titoloEl ? titoloEl.value.trim() : '';
    if (!titolo) { titoloEl?.focus(); return; }
    post(CAPTURE_URL, {
      kind: kindEl ? kindEl.value : 'action',
      titolo: titolo,
      owner_id: ownerEl ? ownerEl.value : '',
      due_date: dueEl && !dueEl.hidden ? dueEl.value : '',
      impatto: impattoEl && !impattoEl.hidden ? impattoEl.value : '',
    }).then(function (data) {
      if (!data || !data.ok) return;
      const log = document.getElementById('capture-log');
      if (log) {
        const li = document.createElement('li');
        li.textContent = data.label + ': ' + data.titolo;
        log.appendChild(li);
      }
      if (titoloEl) titoloEl.value = '';
      if (dueEl) dueEl.value = '';
      titoloEl?.focus();
    }).catch(function () {});
  });
})();
