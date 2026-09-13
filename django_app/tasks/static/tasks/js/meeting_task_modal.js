/* Mini-form «attività kickoff» dell'incontro (include _meeting_task_modal.html).
 *
 * Stesso pannello per dettaglio incontro e registrazione esito: la logica sta
 * qui invece che duplicata nei due template, cosi' un ritocco al flusso non
 * va rifatto due volte.
 *
 * Il template ospite deve definire, prima di caricare questo file:
 *   window.MEETING_TASK_MODAL = { url: <endpoint task-da-step> }
 * e stampare le attivita' del kickoff con
 *   {{ project_tasks_json|json_script:"project-tasks-data" }}
 */
(function () {
  'use strict';

  var config = window.MEETING_TASK_MODAL || {};

  /* Le attivita' passano da json_script, non da una variabile interpolata a
   * mano: un apostrofo in un titolo romperebbe lo script inline. */
  function loadTasks() {
    var node = document.getElementById('project-tasks-data');
    if (!node) { return []; }
    try { return JSON.parse(node.textContent) || []; } catch (error) { return []; }
  }
  var knownTasks = null;
  var activeStepIndex = null;
  var activeStepButtonId = null;

  function el(id) { return document.getElementById(id); }

  function getCsrf() {
    var input = document.querySelector('#ctm-form [name="csrfmiddlewaretoken"]');
    if (input) { return input.value; }
    var match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  /* Le modalita' attrezzatura chiedono campi diversi: mostrarli tutti sempre
   * rendeva il pannello illeggibile proprio nel momento in cui serve, a
   * riunione in corso. */
  function syncToolingFields() {
    var mode = el('ctm-tooling-mode') ? el('ctm-tooling-mode').value : 'none';
    var show = {
      'ctm-tooling-existing-field': mode === 'link_existing',
      'ctm-tooling-pn-field': mode === 'request_new' || mode === 'verification_required',
      'ctm-tooling-code-field': mode === 'request_new',
      'ctm-tooling-note-field': mode === 'request_new' || mode === 'verification_required'
    };
    Object.keys(show).forEach(function (id) {
      var node = el(id);
      if (node) { node.hidden = !show[id]; }
    });
  }

  /* In aggiornamento il titolo non e' piu' obbligatorio: si sta correggendo
   * un'attivita' che esiste gia'. */
  function syncExistingMode() {
    var select = el('ctm-existing');
    var title = el('ctm-title');
    var submit = el('ctm-submit');
    var heading = el('ctm-heading');
    if (!select) { return; }
    var chosen = select.value;
    if (title) { title.required = !chosen; }
    if (chosen) {
      var option = select.options[select.selectedIndex];
      if (title && !title.value.trim()) { title.value = option ? option.dataset.title || '' : ''; }
      if (submit) { submit.lastChild.nodeValue = ' Aggiorna attività'; }
      if (heading) { heading.textContent = 'Aggiorna attività kickoff'; }
    } else {
      if (submit) { submit.lastChild.nodeValue = ' Crea attività'; }
      if (heading) { heading.textContent = "Attività kickoff dall'incontro"; }
    }
  }

  function fillExistingTasks() {
    var select = el('ctm-existing');
    if (!select) { return; }
    if (knownTasks === null) { knownTasks = loadTasks(); }
    while (select.options.length > 1) { select.remove(1); }
    knownTasks.forEach(function (task) {
      var option = document.createElement('option');
      option.value = task.id;
      option.textContent = task.title;
      option.dataset.title = task.title;
      select.appendChild(option);
    });
  }

  window.openCreateTaskModal = function (stepText, stepIndex, options) {
    var overlay = el('ctm-overlay');
    if (!overlay) { return; }
    options = options || {};
    activeStepIndex = typeof stepIndex === 'number' ? stepIndex : null;
    activeStepButtonId = options.buttonId || (activeStepIndex !== null ? 'step-btn-' + activeStepIndex : null);

    var preview = el('ctm-step-preview');
    var label = el('ctm-step-label');
    if (preview) { preview.textContent = stepText || ''; }
    if (preview) { preview.hidden = !stepText; }
    if (label) { label.hidden = !stepText; }

    var form = el('ctm-form');
    if (form) { form.reset(); }
    fillExistingTasks();
    var title = el('ctm-title');
    if (title) { title.value = stepText || ''; }
    syncToolingFields();
    syncExistingMode();

    var err = el('ctm-error');
    if (err) { err.textContent = ''; err.style.display = 'none'; }
    var viewLink = el('ctm-view-link');
    if (viewLink) { viewLink.style.display = 'none'; }
    var submit = el('ctm-submit');
    if (submit) { submit.disabled = false; }

    overlay.style.display = 'flex';
    setTimeout(function () { if (title) { title.focus(); } }, 80);
  };

  window.closeCreateTaskModal = function () {
    var overlay = el('ctm-overlay');
    if (overlay) { overlay.style.display = 'none'; }
    activeStepIndex = null;
    activeStepButtonId = null;
  };

  window.closeCreateTaskModalOutside = function (event) {
    if (event.target === el('ctm-overlay')) { window.closeCreateTaskModal(); }
  };

  window.submitCreateTask = function (event) {
    event.preventDefault();
    var form = el('ctm-form');
    var err = el('ctm-error');
    var viewLink = el('ctm-view-link');
    var submit = el('ctm-submit');
    var title = el('ctm-title');
    var existing = el('ctm-existing');
    if (!form) { return; }

    if (!existing.value && !title.value.trim()) { title.focus(); return; }

    submit.disabled = true;
    var previousLabel = submit.lastChild.nodeValue;
    submit.lastChild.nodeValue = ' Salvataggio…';
    if (err) { err.style.display = 'none'; }

    fetch(config.url, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf(), 'X-Requested-With': 'XMLHttpRequest' },
      body: new URLSearchParams(new FormData(form))
    })
      .then(function (response) { return response.json().catch(function () { return { ok: false }; }); })
      .then(function (data) {
        if (!data.ok) {
          if (err) {
            err.textContent = data.reason || 'Errore durante il salvataggio.';
            err.style.display = '';
          }
          submit.disabled = false;
          submit.lastChild.nodeValue = previousLabel;
          return;
        }
        if (viewLink) {
          viewLink.href = data.task_url;
          viewLink.style.display = '';
          viewLink.textContent = 'Apri "' + data.title + '" →';
        }
        submit.lastChild.nodeValue = data.created ? ' ✓ Creata' : ' ✓ Aggiornata';

        /* L'attivita' appena creata entra subito nel menu «attività già
         * creata»: senza questo, per correggerne la data inizio bisognava
         * ricaricare la pagina. */
        if (data.created) {
          if (knownTasks === null) { knownTasks = loadTasks(); }
          knownTasks.push({ id: data.task_id, title: data.title });
        }

        if (activeStepButtonId) {
          var button = el(activeStepButtonId);
          if (button) {
            button.classList.add('created');
            button.innerHTML = '<svg fill="none" viewBox="0 0 24 24" stroke-width="2.5" style="width:13px;height:13px;stroke:currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg> ' + (data.created ? 'Creata' : 'Aggiornata');
          }
        }
        setTimeout(window.closeCreateTaskModal, 1600);
      })
      .catch(function () {
        if (err) { err.textContent = 'Errore di rete. Riprova.'; err.style.display = ''; }
        submit.disabled = false;
        submit.lastChild.nodeValue = previousLabel;
      });
  };

  document.addEventListener('DOMContentLoaded', function () {
    fillExistingTasks();
    var mode = el('ctm-tooling-mode');
    if (mode) { mode.addEventListener('change', syncToolingFields); }
    var existing = el('ctm-existing');
    if (existing) { existing.addEventListener('change', syncExistingMode); }
    syncToolingFields();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { window.closeCreateTaskModal(); }
  });
})();
