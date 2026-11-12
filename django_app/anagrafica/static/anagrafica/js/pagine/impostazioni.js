/* NOVICROM HUB — da anagrafica/pages/impostazioni.html (blocco 1), spostato dall'inline il 12/11/2026: stesso punto, ora in cache. */
/* Testate di sezione: filtro dell'elenco e «+ Nuovo …» (il form di aggiunta resta
   chiuso finché non serve). Iniettati via JS: senza JS i form restano aperti e la
   pagina funziona uguale (additivo, fail-safe). */
(function () {
  // Contenitore azioni della testata; se manca lo crea e ci sposta i link già presenti.
  function headActions(head) {
    var box = head.querySelector(':scope > .imp-card-head-actions');
    if (box) return box;
    box = document.createElement('div');
    box.className = 'imp-card-head-actions';
    Array.prototype.slice.call(head.children, 1).forEach(function (c) { box.appendChild(c); });
    head.appendChild(box);
    return box;
  }
  // Testata della sezione di un elemento: quella della sua card o della card subito prima.
  function headFor(el) {
    var card = el.closest('.imp-card');
    if (!card) return null;
    var head = card.querySelector(':scope > .imp-card-head');
    if (head) return head;
    var prev = card.previousElementSibling;
    while (prev && !prev.matches('.imp-card')) prev = prev.previousElementSibling;
    return prev ? prev.querySelector(':scope > .imp-card-head') : null;
  }

  function initAddToggles(scope) {
    scope.querySelectorAll('.imp-add-form, .imp-workflow-form').forEach(function (el) {
      if (el.closest('.imp-modal-overlay') || el.dataset.addInit) return;
      var box = el.closest('.imp-subsec') || el.closest('form') || el;
      var head = headFor(box);
      if (!head) return;
      el.dataset.addInit = '1';
      var kicker = box.querySelector('.imp-kicker');
      var label = el.dataset.addLabel || (kicker && kicker.textContent.replace(/^\s*\+\s*/, '').trim()) || 'Aggiungi';
      if (kicker) kicker.hidden = true;
      // Subito sotto la testata, così si apre dove si è cliccato.
      if (box.parentNode === head.parentNode && head.nextElementSibling !== box) head.insertAdjacentElement('afterend', box);
      box.classList.add('imp-add-box');

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'imp-btn imp-btn-green imp-btn-sm imp-add-toggle';
      btn.innerHTML = '<svg class="imp-i" aria-hidden="true"><use href="#imp-i-plus"/></svg>';
      btn.appendChild(document.createTextNode(label));
      headActions(head).appendChild(btn);

      // Aperto se la sezione è vuota o se il form torna con un errore.
      var section = box.closest('.dpi-sub-section') || box.closest('.imp-panel') || scope;
      var empty = !section.querySelector('.imp-row, .imp-table tbody tr, .imp-dpi-tipo');
      var open = empty || !!box.querySelector('.errorlist, .imp-form-error');
      function setOpen(v, focus) {
        box.hidden = !v;
        btn.setAttribute('aria-expanded', v ? 'true' : 'false');
        if (v && focus) {
          var first = box.querySelector('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea');
          if (first) first.focus();
        }
      }
      setOpen(open, false);
      btn.addEventListener('click', function () { setOpen(box.hidden, true); });
    });
  }

  function initPanelSearch(panel) {
    var lists = panel.querySelectorAll('.imp-list');
    if (!lists.length) return;
    var rows = panel.querySelectorAll('.imp-list .imp-row');
    if (rows.length < 4) return;  // liste cortissime: niente filtro

    var wrap = document.createElement('label');
    wrap.className = 'imp-head-search';
    wrap.innerHTML = '<svg class="imp-i" aria-hidden="true"><use href="#imp-i-search"/></svg>';
    var input = document.createElement('input');
    input.type = 'search';
    input.placeholder = 'Filtra…';
    input.setAttribute('aria-label', 'Filtra elenco');
    var info = document.createElement('span');
    info.className = 'imp-search-info';
    wrap.appendChild(input);
    wrap.appendChild(info);

    // Nella testata della sezione dell'elenco (o dove la scheda lo chiede).
    var target = panel.querySelector('[data-imp-search-here]');
    var head = target ? null : headFor(lists[0]) || panel.querySelector('.imp-card-head');
    if (!target && head) target = headActions(head);
    if (target) {
      target.insertBefore(wrap, target.firstChild);
    } else {
      lists[0].parentNode.insertBefore(wrap, lists[0]);
    }

    input.addEventListener('input', function () {
      var q = input.value.trim().toLowerCase();
      var shown = 0, tot = 0;
      lists.forEach(function (list) {
        list.querySelectorAll('.imp-row').forEach(function (row) {
          tot++;
          var match = !q || (row.textContent || '').toLowerCase().indexOf(q) !== -1;
          row.style.display = match ? '' : 'none';
          if (match) shown++;
        });
      });
      // Nascondi i titoli di categoria la cui lista non ha più righe visibili.
      panel.querySelectorAll('.imp-cat-title').forEach(function (t) {
        var nxt = t.nextElementSibling;
        if (nxt && nxt.classList.contains('imp-list')) {
          var vis = Array.prototype.some.call(nxt.querySelectorAll('.imp-row'), function (r) {
            return r.style.display !== 'none';
          });
          t.style.display = vis ? '' : 'none';
        }
      });
      // Gruppi richiudibili: con un filtro attivo si aprono quelli con risultati.
      if (q) {
        panel.querySelectorAll('details.imp-card').forEach(function (d) {
          d.open = Array.prototype.some.call(d.querySelectorAll('.imp-row'), function (r) {
            return r.style.display !== 'none';
          });
        });
      }
      info.textContent = q ? (shown + ' / ' + tot) : '';
    });
  }

  document.querySelectorAll('.imp-panel').forEach(function (panel) {
    initAddToggles(panel);
    initPanelSearch(panel);
  });

  // Il pannello Visite mediche rigenera il proprio contenuto via HTMX (crea/
  // modifica/elimina/modifica-massiva): filtro e «+ Nuovo» stavano nella testata
  // rimpiazzata e vanno reinseriti.
  document.body.addEventListener('htmx:afterSwap', function (e) {
    if (!e.detail || !e.detail.target || e.detail.target.id !== 'visite-mediche-panel-content') return;
    var panel = document.getElementById('tab-visite-mediche');
    if (!panel) return;
    initAddToggles(panel);
    initPanelSearch(panel);
  });
})();
