/* Gantt di commessa: scroll, drag per spostare/ridimensionare le barre, dipendenze.
   Estratto dal template tasks/project_gantt.html. */
(function () {
  var scroll = document.querySelector('.ts-gantt-cm .gscroll');
  if (!scroll) return;
  var zoom = document.getElementById('g_zoom_cm');
  var cascadeEl = document.getElementById('g_cascade_cm');

  function cw() { return parseInt(getComputedStyle(scroll).getPropertyValue('--cw'), 10) || 30; }
  function csrf() {
    var m = document.querySelector("meta[name='csrf-token']");
    if (m) return m.getAttribute('content');
    var i = document.querySelector("[name=csrfmiddlewaretoken]");
    return i ? i.value : '';
  }
  function leftCalc(idx) { return 'calc(var(--cw) * ' + idx + ')'; }
  function widthCalc(span) { return 'calc(var(--cw) * ' + span + ' - 4px)'; }

  // Zoom live (non ricarica)
  if (zoom) zoom.addEventListener('input', function () { scroll.style.setProperty('--cw', zoom.value + 'px'); });

  // ── Drag/resize barre ──
  var drag = null;
  scroll.addEventListener('mousedown', function (e) {
    var bar = e.target.closest('.gbar');
    if (!bar) return;
    var row = bar.closest('.grow.gbody');
    if (!row || !row.getAttribute('data-shift-url')) return;
    e.preventDefault();
    var edge = e.target.classList.contains('ghandle') ? e.target.getAttribute('data-edge') : null;
    drag = {
      bar: bar, row: row, edge: edge, startX: e.clientX, moved: false,
      origStart: parseInt(bar.getAttribute('data-start'), 10) || 0,
      origSpan: parseInt(bar.getAttribute('data-span'), 10) || 1,
      w: cw(),
    };
    bar.classList.add('dragging');
  });
  document.addEventListener('mousemove', function (e) {
    if (!drag) return;
    var d = Math.round((e.clientX - drag.startX) / drag.w);
    if (d !== 0) drag.moved = true;
    if (drag.edge === 'start') {
      var maxd = drag.origSpan - 1;
      var dd = Math.min(d, maxd);
      drag.bar.style.left = leftCalc(drag.origStart + dd);
      drag.bar.style.width = widthCalc(drag.origSpan - dd);
    } else if (drag.edge === 'end') {
      drag.bar.style.width = widthCalc(Math.max(1, drag.origSpan + d));
    } else {
      drag.bar.style.left = leftCalc(drag.origStart + d);
    }
  });
  function reset(g) { g.bar.style.left = leftCalc(g.origStart); g.bar.style.width = widthCalc(g.origSpan); }
  function postShift(g, mode, days) {
    var casc = cascadeEl ? (cascadeEl.checked ? '1' : '0') : '0';
    return fetch(g.row.getAttribute('data-shift-url'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
      body: new URLSearchParams({ mode: mode, shift_days: days, cascade: casc }).toString(),
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j && j.ok) { window.location.reload(); }
      else { reset(g); alert((j && j.error) || 'Errore nello spostamento.'); }
    }).catch(function () { reset(g); alert('Errore di rete.'); });
  }
  document.addEventListener('mouseup', function (e) {
    if (!drag) return;
    var g = drag; drag = null;
    g.bar.classList.remove('dragging');
    var days = Math.round((e.clientX - g.startX) / g.w);
    if (!days) { reset(g); return; }
    var mode = g.edge === 'start' ? 'resize_start' : (g.edge === 'end' ? 'resize_end' : 'shift');
    postShift(g, mode, days);
  });

  // ── Click barra -> quick edit accordion ──
  var forms = document.querySelectorAll('.quick-edit-item[data-task-id]');
  var placeholder = document.getElementById('quick-edit-placeholder');
  function selectTask(taskId) {
    forms.forEach(function (f) { f.classList.toggle('is-visible', taskId !== null && f.dataset.taskId === String(taskId)); });
    if (placeholder) placeholder.style.display = taskId ? 'none' : '';
    scroll.querySelectorAll('.grow.gbody').forEach(function (r) { r.classList.toggle('is-selected', taskId !== null && r.getAttribute('data-task-id') === String(taskId)); });
  }
  scroll.addEventListener('click', function (e) {
    if (e.target.closest('a') || e.target.classList.contains('ghandle')) return;
    var row = e.target.closest('.grow.gbody');
    if (!row || !e.target.closest('.gbar')) return;
    var taskId = row.getAttribute('data-task-id');
    if (!document.querySelector('.quick-edit-item[data-task-id="' + String(taskId) + '"]')) return;
    var already = row.classList.contains('is-selected');
    selectTask(already ? null : taskId);
    if (!already) {
      var sec = document.querySelector('.quick-edit-grid');
      if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });

  // Scroll automatico alla colonna di OGGI
  var oggi = parseInt(scroll.getAttribute('data-oggi-idx'), 10);
  if (oggi >= 0) { var w0 = cw(); scroll.scrollLeft = Math.max(0, oggi * w0 - 3 * w0); }
})();

// ── Dipendenze AJAX ──────────────────────────────────
function getCsrfToken() {
  const el = document.querySelector("[name=csrfmiddlewaretoken]");
  return el ? el.value : "";
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
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": getCsrfToken() },
      body: body.toString(),
    });
    const json = await resp.json();
    if (json.ok) {
      window.location.reload();
    } else {
      alert(json.error || "Errore nell'aggiunta della dipendenza.");
    }
  } catch (e) {
    alert("Errore di rete.");
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
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": getCsrfToken() },
      body: new URLSearchParams({ csrfmiddlewaretoken: getCsrfToken() }).toString(),
    });
    const json = await resp.json();
    if (json.ok) {
      window.location.reload();
    } else {
      alert(json.error || "Errore nella rimozione.");
    }
  } catch (e) {
    alert("Errore di rete.");
  }
}
