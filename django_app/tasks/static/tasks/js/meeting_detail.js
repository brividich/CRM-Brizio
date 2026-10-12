/* Dettaglio incontro: riapertura minuta, spunta punti, azioni rapide.
   Estratto dal template tasks/project_meeting_detail.html. */
var KO_MEETING_DETAIL_CFG = (document.currentScript && document.currentScript.dataset) || {};
(function () {
  'use strict';

  /* Riapertura minuta: il motivo e' obbligatorio e finisce nel registro azioni. */
  const reopenOpen = document.getElementById('minute-reopen-open');
  const reopenBox = document.getElementById('minute-reopen-box');
  if (reopenOpen && reopenBox) {
    reopenOpen.addEventListener('click', function () {
      reopenBox.hidden = false;
      reopenOpen.hidden = true;
      document.getElementById('minute-reopen-motivo')?.focus();
    });
  }

  const TOGGLE_BASE  = KO_MEETING_DETAIL_CFG.toggleBase;
  const CAN_MANAGE   = KO_MEETING_DETAIL_CFG.canManage === '1';

  /* ── CSRF ──────────────────────────────────────────────────────────── */
  function getCsrf() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
  }

  /* ── Agenda toggle ─────────────────────────────────────────────────── */
  window.toggleAgendaItem = function(itemId) {
    const row = document.getElementById('agenda-item-' + itemId);
    const btn = document.getElementById('toggle-btn-' + itemId);
    if (!row || !btn) return;

    btn.disabled = true;

    fetch(TOGGLE_BASE + itemId + '/', {
      method: 'POST',
      headers: { 'X-CSRFToken': getCsrf(), 'Content-Type': 'application/json' },
    })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) { btn.disabled = false; return; }

      const isDone = data.done;
      row.dataset.done = isDone ? 'true' : 'false';
      row.classList.toggle('done-item', isDone);
      btn.classList.toggle('done', isDone);
      btn.title = isDone ? 'Segna come non trattato' : 'Segna come trattato';

      // Aggiorna badge "Trattato" nel body
      const body = row.querySelector('.md-agenda-body');
      let badge = body.querySelector('.md-agenda-done-badge');
      if (isDone && !badge) {
        badge = document.createElement('div');
        badge.className = 'md-agenda-done-badge';
        badge.innerHTML = '<svg fill="none" viewBox="0 0 24 24" stroke-width="2.5" style="width:13px;height:13px;stroke:currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>Trattato';
        body.appendChild(badge);
      } else if (!isDone && badge) {
        badge.remove();
      }

      // Aggiorna counter nell'header
      updateAgendaCounter();
      btn.disabled = false;
    })
    .catch(() => { btn.disabled = false; });
  };

  function updateAgendaCounter() {
    const label = document.getElementById('agenda-progress-label');
    if (!label) return;
    const items = document.querySelectorAll('[id^="agenda-item-"]');
    const done  = document.querySelectorAll('[id^="agenda-item-"].done-item');
    if (items.length === 0) return;
    label.textContent = done.length === 0
      ? `${items.length} punt${items.length === 1 ? 'o' : 'i'}`
      : `${done.length}/${items.length} trattati`;
  }

  updateAgendaCounter();

  /* ── Copilota: commesse simili e punti proposti ──────────────────────── */
  const kaiBtn = document.getElementById('kai-btn');
  const kaiOut = document.getElementById('kai-out');
  if (kaiBtn && kaiOut) {
    kaiBtn.addEventListener('click', function () {
      const label = kaiBtn.textContent;
      kaiBtn.disabled = true;
      kaiBtn.textContent = 'Sto leggendo le commesse simili…';
      fetch(kaiBtn.dataset.url, { method: 'POST', headers: { 'X-CSRFToken': getCsrf() }, credentials: 'same-origin' })
        .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(html => { kaiOut.innerHTML = html; })
        .catch(() => { kaiOut.innerHTML = '<p class="kai-riga">Copilota non disponibile, riprova tra poco.</p>'; })
        .finally(() => { kaiBtn.disabled = false; kaiBtn.textContent = label; });
    });
    kaiOut.addEventListener('click', function (event) {
      const add = event.target.closest('[data-kai-add]');
      if (!add) return;
      const body = new FormData();
      body.append('titolo', add.dataset.titolo || '');
      body.append('nota', add.dataset.nota || '');
      body.append('durata_minuti', add.dataset.durata || '');
      body.append('source', 'ai');
      add.disabled = true;
      fetch(kaiBtn.dataset.addUrl, { method: 'POST', headers: { 'X-CSRFToken': getCsrf() }, body: body, credentials: 'same-origin' })
        .then(r => r.json())
        .then(data => { add.textContent = data.ok ? 'Aggiunto: lo vedi ricaricando la pagina' : 'Non aggiunto'; if (!data.ok) add.disabled = false; })
        .catch(() => { add.textContent = 'Non aggiunto'; add.disabled = false; });
    });
  }

})();
