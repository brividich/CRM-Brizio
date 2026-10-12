/* Esito incontro: punti trattati, note per punto, problemi, azioni, decisioni.
   Estratto dal template tasks/project_meeting_minutes.html. */
var KO_MEETING_MINUTES_CFG = (document.currentScript && document.currentScript.dataset) || {};
(function () {
  'use strict';

  let projectTasks = [];
  try {
    const el = document.getElementById('project-tasks-data');
    if (el) projectTasks = JSON.parse(el.textContent) || [];
  } catch (e) { projectTasks = []; }

  function esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function csrfToken() {
    const el = document.querySelector('#minutes-form [name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  /* Spunta dei punti agenda: stesso endpoint del dettaglio incontro. */
  const toggleBase = KO_MEETING_MINUTES_CFG.toggleBase;
  window.bindAgendaToggle = function (btn) {
    btn.addEventListener('click', function () {
      const itemId = btn.getAttribute('data-agenda-toggle');
      btn.disabled = true;
      fetch(toggleBase.replace('ITEM', encodeURIComponent(itemId)), {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
      })
        .then(r => r.json())
        .then(function (data) {
          if (!data || !data.ok) return;
          btn.textContent = data.done ? 'Trattato' : 'Da trattare';
          btn.classList.toggle('primary', !!data.done);
          btn.classList.toggle('ghost', !data.done);
        })
        .catch(function () {})
        .finally(function () { btn.disabled = false; });
    });
  };
  document.querySelectorAll('[data-agenda-toggle]').forEach(window.bindAgendaToggle);

  /* Nota del punto: salvata alla perdita del focus, stesso endpoint della conduzione. */
  const updateUrl = KO_MEETING_MINUTES_CFG.updateUrl;
  window.bindAgendaNota = function (area) {
    let saved = area.value;
    area.addEventListener('blur', function () {
      if (area.value === saved) return;
      const body = new URLSearchParams();
      body.set('item_id', area.getAttribute('data-agenda-nota'));
      body.set('nota', area.value);
      fetch(updateUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken(), 'X-Requested-With': 'XMLHttpRequest' },
        body: body,
      })
        .then(r => r.json())
        .then(function (data) { if (data && data.ok) saved = area.value; })
        .catch(function () {});
    });
  };
  document.querySelectorAll('[data-agenda-nota]').forEach(window.bindAgendaNota);

  /* Mini-form attivita' kickoff: il pannello e' l'include condiviso con la
     scheda incontro, qui serve solo il gancio che lo apre. */
  const openTaskModalBtn = document.getElementById('open-task-modal-btn');
  if (openTaskModalBtn) {
    openTaskModalBtn.addEventListener('click', function () {
      if (typeof window.openCreateTaskModal === 'function') { window.openCreateTaskModal('', null); }
    });
  }

  /* Nuovi problemi: righe ripetibili */
  function userOptionsHtml() {
    return '<option value="">Responsabile</option>' + document.getElementById('ko-minutes-responsabili').innerHTML;
  }

  function taskOptionsHtml() {
    if (!projectTasks.length) return '<option value="">Task collegato</option>';
    return '<option value="">Task collegato</option>' + projectTasks.map(t => `<option value="${t.id}">${esc(t.title)}</option>`).join('');
  }

  function addIssueRow() {
    const list = document.getElementById('new-issues-list');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'mf-new-issue-row';
    row.innerHTML = `
      <div>
        <input class="input" type="text" name="new_issue_title" maxlength="220" placeholder="Problema aperto" style="width:100%;box-sizing:border-box">
        <textarea class="input" name="new_issue_description" rows="2" placeholder="Dettaglio / contesto" style="width:100%;box-sizing:border-box;margin-top:6px"></textarea>
      </div>
      <div>
        <select class="input" name="new_issue_assigned_to" style="width:100%;box-sizing:border-box">${userOptionsHtml()}</select>
        <select class="input" name="new_issue_task" style="width:100%;box-sizing:border-box;margin-top:6px">${taskOptionsHtml()}</select>
      </div>
      <input class="input" type="date" name="new_issue_due_date" title="Scadenza">
      <button type="button" class="mf-new-issue-remove" title="Rimuovi problema">
        <svg fill="none" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>
      </button>
    `;
    row.querySelector('.mf-new-issue-remove')?.addEventListener('click', () => row.remove());
    list.appendChild(row);
    row.querySelector('input[name="new_issue_title"]')?.focus();
  }

  const addIssueBtn = document.getElementById('add-issue-btn');
  if (addIssueBtn) addIssueBtn.addEventListener('click', addIssueRow);

  /* Nuove azioni: stessa griglia dei problemi, campi propri */
  function addActionRow() {
    const list = document.getElementById('new-actions-list');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'mf-new-issue-row';
    row.innerHTML = `
      <div>
        <input class="input" type="text" name="new_action_title" maxlength="220" placeholder="Azione decisa" style="width:100%;box-sizing:border-box">
        <textarea class="input" name="new_action_description" rows="2" placeholder="Dettaglio / contesto" style="width:100%;box-sizing:border-box;margin-top:6px"></textarea>
      </div>
      <div>
        <select class="input" name="new_action_assigned_to" style="width:100%;box-sizing:border-box">${userOptionsHtml()}</select>
        <select class="input" name="new_action_task" style="width:100%;box-sizing:border-box;margin-top:6px">${taskOptionsHtml()}</select>
      </div>
      <input class="input" type="date" name="new_action_due_date" title="Scadenza">
      <button type="button" class="mf-new-issue-remove" title="Rimuovi azione">
        <svg fill="none" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>
      </button>
    `;
    row.querySelector('.mf-new-issue-remove')?.addEventListener('click', () => row.remove());
    list.appendChild(row);
    row.querySelector('input[name="new_action_title"]')?.focus();
  }
  document.getElementById('add-action-btn')?.addEventListener('click', addActionRow);

  /* Nuove decisioni */
  function impactOptionsHtml() {
    return document.getElementById('ko-minutes-impatti').innerHTML;
  }

  function addDecisionRow() {
    const list = document.getElementById('new-decisions-list');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'mf-new-issue-row';
    row.innerHTML = `
      <div>
        <input class="input" type="text" name="new_decision_testo" maxlength="400" placeholder="Decisione presa" style="width:100%;box-sizing:border-box">
        <textarea class="input" name="new_decision_dettaglio" rows="2" placeholder="Motivazione / contesto" style="width:100%;box-sizing:border-box;margin-top:6px"></textarea>
      </div>
      <div>
        <select class="input" name="new_decision_decisa_da" style="width:100%;box-sizing:border-box">${userOptionsHtml().replace('Responsabile', 'Decisa da')}</select>
        <select class="input" name="new_decision_impatto" style="width:100%;box-sizing:border-box;margin-top:6px">${impactOptionsHtml()}</select>
      </div>
      <span></span>
      <button type="button" class="mf-new-issue-remove" title="Rimuovi decisione">
        <svg fill="none" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>
      </button>
    `;
    row.querySelector('.mf-new-issue-remove')?.addEventListener('click', () => row.remove());
    list.appendChild(row);
    row.querySelector('input[name="new_decision_testo"]')?.focus();
  }
  document.getElementById('add-decision-btn')?.addEventListener('click', addDecisionRow);

  document.querySelectorAll('[data-issue-card]').forEach(function (card) {
    const checkbox = card.querySelector('.mf-issue-check');
    if (!checkbox) return;
    const syncCard = () => card.classList.toggle('resolved', checkbox.checked);
    checkbox.addEventListener('change', syncCard);
    syncCard();
  });

  /* Presenze: spunta/togli tutti */
  function setPresenze(checked) {
    document.querySelectorAll('#presenze-grid input[type=checkbox]').forEach(function (cb) {
      cb.checked = checked;
    });
  }
  document.getElementById('presenze-all')?.addEventListener('click', function () { setPresenze(true); });
  document.getElementById('presenze-none')?.addEventListener('click', function () { setPresenze(false); });

  /* Collassabile note legacy */
  const problemsToggle = document.getElementById('toggle-problems-note');
  const problemsBody = document.getElementById('problems-note');
  if (problemsToggle && problemsBody) {
    problemsToggle.addEventListener('click', function () {
      problemsBody.classList.toggle('open');
      problemsToggle.classList.toggle('open');
    });
  }

  const stepsToggle = document.getElementById('toggle-steps-note');
  const stepsBody = document.getElementById('steps-note');
  if (stepsToggle && stepsBody) {
    stepsToggle.addEventListener('click', function () {
      stepsBody.classList.toggle('open');
      stepsToggle.classList.toggle('open');
    });
    const field = document.querySelector('[name="next_steps"]');
    if (field && field.value.trim()) {
      stepsBody.classList.add('open');
      stepsToggle.classList.add('open');
    }
  }
})();
