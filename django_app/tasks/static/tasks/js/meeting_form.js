/* Convocazione incontro: agenda strutturata, partecipanti, CC, modelli ODG.
   Estratto dal template tasks/project_meeting_form.html. */
var KO_MEETING_FORM_CFG = (document.currentScript && document.currentScript.dataset) || {};
(function () {
  'use strict';

  /* ─── Sale riunioni → datalist ────────────────────────────────────── */
  try {
    const roomsEl = document.getElementById('meeting-rooms-data');
    const rooms = roomsEl ? (JSON.parse(roomsEl.textContent) || []) : [];
    const dl = document.getElementById('meeting-rooms-datalist');
    const luogoInput = document.getElementById(KO_MEETING_FORM_CFG.luogoId);
    if (dl && rooms.length > 0) {
      rooms.forEach(function(nome) {
        const opt = document.createElement('option');
        opt.value = nome;
        dl.appendChild(opt);
      });
      if (luogoInput) luogoInput.setAttribute('list', 'meeting-rooms-datalist');
    }
  } catch(e) {}

  /* ─── Dati tasks dal kickoff ──────────────────────────────────────── */
  let projectTasks = [];
  try {
    const el = document.getElementById('project-tasks-data');
    if (el) projectTasks = JSON.parse(el.textContent) || [];
  } catch(e) { projectTasks = []; }

  /* Popola il select task nel form aggiunta */
  const taskSelect = document.getElementById('new-agenda-task');
  if (taskSelect && projectTasks.length > 0) {
    projectTasks.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.id;
      opt.textContent = t.title;
      taskSelect.appendChild(opt);
    });
  }

  /* ─── Escape HTML ─────────────────────────────────────────────────── */
  function esc(str) {
    return String(str || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function normalizeCustomFields(fields) {
    if (!Array.isArray(fields)) return [];
    return fields
      .map(field => ({
        label: String(field?.label || '').trim(),
        value: String(field?.value || '').trim(),
      }))
      .filter(field => field.label && field.value)
      .slice(0, 12);
  }

  function addCustomFieldRow(label = '', value = '') {
    const container = document.getElementById('agenda-custom-fields');
    if (!container) return;
    if (container.querySelectorAll('.agenda-custom-row').length >= 12) return;

    const row = document.createElement('div');
    row.className = 'agenda-custom-row';

    const labelInput = document.createElement('input');
    labelInput.type = 'text';
    labelInput.className = 'input';
    labelInput.placeholder = 'Nome campo';
    labelInput.maxLength = 80;
    labelInput.value = label;
    labelInput.dataset.role = 'label';

    const valueInput = document.createElement('input');
    valueInput.type = 'text';
    valueInput.className = 'input';
    valueInput.placeholder = 'Valore';
    valueInput.maxLength = 500;
    valueInput.value = value;
    valueInput.dataset.role = 'value';

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'agenda-custom-remove';
    removeBtn.title = 'Rimuovi campo';
    removeBtn.innerHTML = '<svg fill="none" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>';
    removeBtn.addEventListener('click', () => row.remove());

    row.append(labelInput, valueInput, removeBtn);
    container.appendChild(row);
    labelInput.focus();
  }

  function resetCustomFieldRows() {
    const container = document.getElementById('agenda-custom-fields');
    if (container) container.innerHTML = '';
  }

  function collectCustomFields() {
    const rows = document.querySelectorAll('#agenda-custom-fields .agenda-custom-row');
    return Array.from(rows).map(row => {
      const label = row.querySelector('[data-role="label"]')?.value.trim() || '';
      const value = row.querySelector('[data-role="value"]')?.value.trim() || '';
      return { label, value };
    }).filter(field => field.label && field.value).slice(0, 12);
  }

  /* ─── Agenda builder ─────────────────────────────────────────────── */
  let agenda = [];

  function initAgenda() {
    const raw = document.getElementById('id_agenda_items_raw');
    if (raw && raw.value) {
      try { agenda = JSON.parse(raw.value) || []; } catch(e) { agenda = []; }
    }
    renderAgenda();
  }

  /* Id del punto: due punti aggiunti nello stesso millisecondo prendevano lo
     stesso id, e in conduzione la nota/spunta finiva sempre sul primo dei due. */
  function newAgendaItemId() {
    return String(Date.now()) + '-' + Math.random().toString(36).slice(2, 8);
  }

  function saveAgendaToHidden() {
    const raw = document.getElementById('id_agenda_items_raw');
    if (raw) raw.value = JSON.stringify(agenda);
  }

  function renderAgenda() {
    const container = document.getElementById('agenda-list');
    if (!container) return;

    if (agenda.length === 0) {
      container.innerHTML = `
        <div class="agenda-empty-state">
          <svg fill="none" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0ZM3.75 12h.007v.008H3.75V12Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm-.375 5.25h.007v.008H3.75v-.008Zm.375 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Z"/>
          </svg>
          Nessun punto aggiunto — clicca <strong>Aggiungi punto</strong> per strutturare l'ordine del giorno.
        </div>`;
      saveAgendaToHidden();
      return;
    }

    container.innerHTML = agenda.map((item, idx) => {
      const taskBadge = item.task_id
        ? `<span class="agenda-task-badge"><svg fill="none" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3"/></svg>${esc(item.task_label || ('Task #' + item.task_id))}</span>`
        : '';
      const issueBadge = item.issue_id
        ? `<span class="agenda-task-badge" style="background:var(--danger-bg);border-color:var(--danger-bg);color:var(--danger)">Problema tracciato</span>`
        : '';
      const respBadge = item.responsabile_label
        ? `<span class="agenda-task-badge"><svg fill="none" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0A17.933 17.933 0 0 1 12 21.75c-2.676 0-5.216-.584-7.499-1.632Z"/></svg>${esc(item.responsabile_label)}</span>`
        : '';
      const durataBadge = item.durata_minuti
        ? `<span class="agenda-task-badge">${esc(String(item.durata_minuti))} min</span>`
        : '';
      const nota = item.nota
        ? `<div class="agenda-nota">${esc(item.nota)}</div>`
        : '';
      const customFields = normalizeCustomFields(item.custom_fields);
      const customFieldsHtml = customFields.length
        ? `<div class="agenda-extra-fields">${customFields.map(field => `
            <div class="agenda-extra-field">
              <span>${esc(field.label)}</span>
              <strong>${esc(field.value)}</strong>
            </div>`).join('')}</div>`
        : '';
      return `
        <div class="agenda-item">
          <div class="agenda-num">${idx + 1}</div>
          <div class="agenda-body">
            <div class="agenda-title">${esc(item.titolo)}${issueBadge}${taskBadge}${respBadge}${durataBadge}</div>
            ${nota}
            ${customFieldsHtml}
          </div>
          ${item.locked ? '' : `
            <button type="button" class="agenda-del" onclick="removeAgendaItem('${esc(item.id)}')" title="Rimuovi punto">
              <svg fill="none" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>
            </button>
          `}
        </div>`;
    }).join('');

    saveAgendaToHidden();
  }

  window.removeAgendaItem = function(id) {
    agenda = agenda.filter(item => item.id !== id);
    renderAgenda();
  };

  function showAddForm() {
    const btn = document.getElementById('agenda-add-btn');
    const form = document.getElementById('agenda-add-form');
    if (btn) btn.style.display = 'none';
    if (form) form.classList.add('open');
    const t = document.getElementById('new-agenda-title');
    if (t) t.focus();
  }

  function hideAddForm() {
    const btn = document.getElementById('agenda-add-btn');
    const form = document.getElementById('agenda-add-form');
    if (btn) btn.style.display = '';
    if (form) form.classList.remove('open');
    const t = document.getElementById('new-agenda-title');
    const n = document.getElementById('new-agenda-nota');
    const k = document.getElementById('new-agenda-task');
    const r = document.getElementById('new-agenda-resp');
    const d = document.getElementById('new-agenda-durata');
    if (t) t.value = '';
    if (n) n.value = '';
    if (k) k.value = '';
    if (r) r.value = '';
    if (d) d.value = '';
    resetCustomFieldRows();
  }

  function confirmAddItem() {
    const titleEl = document.getElementById('new-agenda-title');
    const notaEl  = document.getElementById('new-agenda-nota');
    const taskEl  = document.getElementById('new-agenda-task');
    const respEl  = document.getElementById('new-agenda-resp');
    const durataEl = document.getElementById('new-agenda-durata');

    const title = titleEl ? titleEl.value.trim() : '';
    if (!title) { if (titleEl) { titleEl.focus(); titleEl.style.borderColor='var(--danger)'; } return; }
    if (titleEl) titleEl.style.borderColor = '';

    const taskId = taskEl ? taskEl.value : '';
    const taskLabel = taskId
      ? (projectTasks.find(t => String(t.id) === taskId)?.title || ('Task #' + taskId))
      : '';

    const respId = respEl ? respEl.value : '';
    const respLabel = respId ? (respEl.options[respEl.selectedIndex]?.textContent || '') : '';
    const durata = durataEl && durataEl.value ? parseInt(durataEl.value) : null;

    agenda.push({
      id: newAgendaItemId(),
      titolo: title,
      nota: notaEl ? notaEl.value.trim() : '',
      task_id: taskId ? parseInt(taskId) : null,
      task_label: taskLabel,
      responsabile_id: respId ? parseInt(respId) : null,
      responsabile_label: respLabel,
      durata_minuti: (durata && durata > 0) ? durata : null,
      custom_fields: collectCustomFields(),
      done: false,
    });

    renderAgenda();
    hideAddForm();
  }

  /* Wiring pulsanti agenda */
  const agendaAddBtn     = document.getElementById('agenda-add-btn');
  const agendaConfirmBtn = document.getElementById('agenda-confirm-btn');
  const agendaCancelBtn  = document.getElementById('agenda-cancel-btn');
  const agendaCustomAddBtn = document.getElementById('agenda-custom-add-btn');
  if (agendaAddBtn)     agendaAddBtn.addEventListener('click', showAddForm);
  if (agendaConfirmBtn) agendaConfirmBtn.addEventListener('click', confirmAddItem);
  if (agendaCancelBtn)  agendaCancelBtn.addEventListener('click', hideAddForm);
  if (agendaCustomAddBtn) agendaCustomAddBtn.addEventListener('click', () => addCustomFieldRow());

  /* ─── Suggerimenti ODG dagli incontri passati ─────────────────────── */
  let agendaSuggestions = [];
  try {
    const el = document.getElementById('agenda-suggestions-data');
    if (el) agendaSuggestions = JSON.parse(el.textContent) || [];
  } catch (e) { agendaSuggestions = []; }
  (function initAgendaSuggestions() {
    const dl = document.getElementById('agenda-suggestions-datalist');
    const titleEl = document.getElementById('new-agenda-title');
    if (!dl || !titleEl || agendaSuggestions.length === 0) return;
    agendaSuggestions.forEach(function (s) {
      const opt = document.createElement('option');
      opt.value = s.titolo;
      /* L'etichetta dice quanto e' ricorrente il punto: aiuta a scegliere fra
         due formulazioni simili senza aprire gli incontri passati. */
      const bits = [];
      if (s.usi > 1) bits.push('usato ' + s.usi + ' volte');
      if (s.durata_minuti) bits.push(s.durata_minuti + ' min');
      if (bits.length) opt.label = bits.join(' · ');
      dl.appendChild(opt);
    });
    document.getElementById('agenda-suggestions-hint')?.removeAttribute('hidden');

    /* Scegliendo un suggerimento si precompilano nota e durata, ma solo se
       vuote: quello che l'utente ha gia' scritto non si sovrascrive mai. */
    titleEl.addEventListener('input', function () {
      const scelto = titleEl.value.trim().toLowerCase();
      if (!scelto) return;
      const match = agendaSuggestions.find(function (s) {
        return String(s.titolo || '').trim().toLowerCase() === scelto;
      });
      if (!match) return;
      const notaEl = document.getElementById('new-agenda-nota');
      const durataEl = document.getElementById('new-agenda-durata');
      if (notaEl && !notaEl.value.trim() && match.nota) notaEl.value = match.nota;
      if (durataEl && !durataEl.value.trim() && match.durata_minuti) durataEl.value = match.durata_minuti;
    });
  })();

  /* Tasto Enter nel campo titolo aggiunge l'item */
  const newAgendaTitleEl = document.getElementById('new-agenda-title');
  if (newAgendaTitleEl) {
    newAgendaTitleEl.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); confirmAddItem(); }
    });
  }

  /* Salva prima del submit */
  const meetingFormEl = document.getElementById('meeting-form');
  if (meetingFormEl) meetingFormEl.addEventListener('submit', saveAgendaToHidden);

  /* Init da dati esistenti (edit) */
  initAgenda();

  /* ─── Modelli ODG e duplica dall'incontro precedente ──────────────── */
  function readJsonScript(id) {
    try {
      const el = document.getElementById(id);
      return el ? (JSON.parse(el.textContent) || []) : [];
    } catch (e) { return []; }
  }
  const agendaTemplates = readJsonScript('agenda-templates-data');
  const previousAgenda = readJsonScript('previous-agenda-data');

  /* I punti caricati sono normali item: modificabili e rimovibili come gli altri. */
  function appendAgendaItems(items) {
    let added = 0;
    (items || []).forEach(function (raw, i) {
      const titolo = String(raw.titolo || '').trim();
      if (!titolo) return;
      agenda.push({
        id: newAgendaItemId(),
        titolo: titolo,
        nota: String(raw.nota || '').trim(),
        task_id: null,
        task_label: '',
        responsabile_id: null,
        responsabile_label: '',
        durata_minuti: raw.durata_minuti || null,
        custom_fields: [],
        done: false,
      });
      added += 1;
    });
    if (added) renderAgenda();
    return added;
  }

  document.getElementById('agenda-template-apply')?.addEventListener('click', function () {
    const select = document.getElementById('agenda-template-select');
    const index = select ? parseInt(select.value, 10) : NaN;
    if (Number.isNaN(index) || !agendaTemplates[index]) return;
    appendAgendaItems(agendaTemplates[index].items);
    if (select) select.value = '';
  });

  document.getElementById('agenda-duplicate-prev')?.addEventListener('click', function () {
    appendAgendaItems(previousAgenda);
  });

  /* ─── Responsabile punto ODG = solo convocati ─────────────────────── */
  const respSelect = document.getElementById('new-agenda-resp');
  const respOptionsAll = respSelect
    ? Array.from(respSelect.options)
        .filter(opt => opt.value)
        .map(opt => ({ value: String(opt.value), label: opt.textContent }))
    : [];

  function selectedParticipantIds() {
    const ids = new Set();
    document.querySelectorAll('#mf-user-grid input[type=checkbox]:checked').forEach(cb => {
      ids.add(String(cb.value));
    });
    return ids;
  }

  /* Il responsabile di un punto all'ordine del giorno deve essere uno dei
     convocati: ricostruiamo le option a ogni cambio di partecipanti. */
  function syncResponsabileOptions() {
    if (!respSelect) return;
    const ids = selectedParticipantIds();
    const current = String(respSelect.value || '');
    const available = respOptionsAll.filter(opt => ids.has(opt.value));

    respSelect.innerHTML = '';
    const none = document.createElement('option');
    none.value = '';
    none.textContent = available.length
      ? '— nessuno —'
      : '— seleziona prima i partecipanti —';
    respSelect.appendChild(none);
    available.forEach(opt => {
      const el = document.createElement('option');
      el.value = opt.value;
      el.textContent = opt.label;
      respSelect.appendChild(el);
    });

    respSelect.value = ids.has(current) ? current : '';
    respSelect.disabled = available.length === 0;
  }

  /* ─── Ricerca invitati ────────────────────────────────────────────── */
  function updateParticipantTags() {
    const tags = document.getElementById('participant-tags');
    if (!tags) return;
    const selected = [];
    document.querySelectorAll('#mf-user-grid input[type=checkbox]:checked').forEach(cb => {
      const label = cb.closest('label');
      if (label) selected.push(label.textContent.trim());
    });
    if (selected.length === 0) {
      tags.innerHTML = '<span class="mf-ptag-none">Nessun utente selezionato</span>';
    } else {
      tags.innerHTML = selected.map(name => {
        const initials = name.trim().split(/\s+/).map(w => w[0]?.toUpperCase() || '').join('').slice(0, 2);
        return `<span class="mf-ptag"><span class="mf-ptag-avatar">${esc(initials)}</span>${esc(name)}</span>`;
      }).join('');
    }
  }

  function filterUserGrid(query, gridId, emptyId, countId) {
    const grid = document.getElementById(gridId);
    const emptyMsg = document.getElementById(emptyId);
    const countEl = document.getElementById(countId);
    if (!grid) return;

    const q = query.toLowerCase().trim();
    let visible = 0;
    grid.querySelectorAll('label').forEach(label => {
      const match = !q || label.textContent.toLowerCase().includes(q);
      label.classList.toggle('mf-hidden', !match);
      if (match) visible++;
    });

    const total = grid.querySelectorAll('label').length;
    if (emptyMsg) emptyMsg.style.display = (q && visible === 0) ? '' : 'none';
    if (countEl) countEl.textContent = q ? `${visible}/${total}` : '';
  }

  const searchInput = document.getElementById('participant-search');
  if (searchInput) {
    searchInput.addEventListener('input', () => filterUserGrid(
      searchInput.value, 'mf-user-grid', 'grid-empty', 'search-count'));
  }

  const ccSearchInput = document.getElementById('cc-search');
  if (ccSearchInput) {
    ccSearchInput.addEventListener('input', () => filterUserGrid(
      ccSearchInput.value, 'mf-cc-grid', 'cc-grid-empty', 'cc-search-count'));
  }

  document.querySelectorAll('#mf-user-grid input[type=checkbox]').forEach(cb => {
    cb.addEventListener('change', () => {
      updateParticipantTags();
      updateAttendeesPreview();
      syncResponsabileOptions();
    });
  });

  updateParticipantTags();
  syncResponsabileOptions();

  /* ─── Outlook toggle ──────────────────────────────────────────────── */
  function updateAttendeesPreview() {
    const toggle = document.querySelector('.mf-toggle');
    if (!toggle || !toggle.checked) return;
    const preview = document.getElementById('mf-attendees-preview');
    if (!preview) return;

    const emails = [];
    document.querySelectorAll('#mf-user-grid input[type=checkbox]:checked').forEach(cb => {
      const label = cb.closest('label');
      if (label) emails.push(label.textContent.trim());
    });
    const extraField = document.querySelector('[name="partecipanti_email_extra"]');
    if (extraField) {
      extraField.value.split('\n').forEach(line => {
        const e = line.trim();
        if (e && e.includes('@')) emails.push(e);
      });
    }

    if (emails.length === 0) {
      preview.style.display = 'none';
    } else {
      preview.style.display = '';
      preview.innerHTML =
        `<div style="font-size:.75rem;font-weight:700;margin-bottom:6px;opacity:.7">INVITATI (${emails.length})</div>` +
        emails.map(e => `<div class="mf-at-row"><span class="mf-at-dot"></span>${esc(e)}</div>`).join('');
    }
  }

  function updateOutlookVisibility() {
    const toggle = document.querySelector('.mf-toggle');
    const body   = document.getElementById('outlook-body');
    if (!toggle || !body) return;
    body.classList.toggle('open', toggle.checked);
    updateAttendeesPreview();
  }

  /* ─── Outlook toggle ──────────────────────────────────────────────── */
  const outlookToggleRow = document.getElementById('outlook-toggle-row');
  if (outlookToggleRow) {
    outlookToggleRow.addEventListener('click', function() {
      const toggle = document.querySelector('.mf-toggle');
      if (toggle) { toggle.checked = !toggle.checked; toggle.dispatchEvent(new Event('change')); }
    });
  }
  const mfToggle = document.querySelector('.mf-toggle');
  if (mfToggle) mfToggle.addEventListener('change', updateOutlookVisibility);
  const emailExtraField = document.querySelector('[name="partecipanti_email_extra"]');
  if (emailExtraField) emailExtraField.addEventListener('input', updateAttendeesPreview);
  updateOutlookVisibility();

  /* ─── Collassabili ─────────────────────────────────────────────────── */
  function wireCollapsible(toggleId, bodyId) {
    const btn  = document.getElementById(toggleId);
    const body = document.getElementById(bodyId);
    if (!btn || !body) return;
    btn.addEventListener('click', function() {
      body.classList.toggle('open');
      btn.classList.toggle('open');
    });
  }
  wireCollapsible('toggle-part-note', 'part-note');
  wireCollapsible('toggle-cc',        'cc-body');
  wireCollapsible('toggle-odg-note',  'odg-note');

  /* Apri il blocco CC se l'incontro ne ha gia' (edit): un destinatario in copia
     nascosto in una sezione chiusa e' un destinatario che non si controlla. */
  (function openCcIfFilled() {
    const ccExtra = document.querySelector('[name="cc_email_extra"]');
    const ccChecked = document.querySelector('[name="cc_utenti"]:checked');
    if (!ccChecked && !(ccExtra && ccExtra.value.trim())) return;
    const body = document.getElementById('cc-body');
    const btn  = document.getElementById('toggle-cc');
    if (body) body.classList.add('open');
    if (btn)  btn.classList.add('open');
  })();

  /* Apri automaticamente note ODG se il campo ha già contenuto (edit) */
  const odgField = document.querySelector('[name="ordine_del_giorno"]');
  if (odgField && odgField.value.trim()) {
    const odgBody   = document.getElementById('odg-note');
    const odgToggle = document.getElementById('toggle-odg-note');
    if (odgBody)   odgBody.classList.add('open');
    if (odgToggle) odgToggle.classList.add('open');
  }

})();
