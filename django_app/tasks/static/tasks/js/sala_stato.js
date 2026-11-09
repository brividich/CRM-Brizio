/* Dettaglio incontro: «Verifica» chiede a Outlook se la sala ha accettato la prenotazione. */
(function () {
  'use strict';
  var box = document.querySelector('[data-sala-stato]');
  if (!box) { return; }
  var btn = box.querySelector('[data-sala-verifica]');
  var chip = box.querySelector('[data-sala-chip]');
  if (!btn) { return; }
  function csrf() {
    var input = document.querySelector('[name=csrfmiddlewaretoken]');
    if (input) { return input.value; }
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  btn.addEventListener('click', function () {
    btn.disabled = true;
    btn.textContent = 'Verifico…';
    fetch(box.dataset.url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrf(), 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j.ok && j.label) { chip.textContent = j.label; chip.className = 'ts-chip ' + (j.classe || ''); }
      else if (!j.ok) { chip.textContent = j.reason || 'Verifica non riuscita'; chip.className = 'ts-chip warn'; }
    }).catch(function () {
      chip.textContent = 'Verifica non riuscita'; chip.className = 'ts-chip warn';
    }).then(function () { btn.disabled = false; btn.textContent = 'Verifica'; });
  });
})();
