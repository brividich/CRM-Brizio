/* NOVICROM HUB — pulsanti di invio: stato di attesa e ripristino.
 * Spostato da template inline (12/11/2026): caricato nello stesso punto e senza defer,
 * quindi si esegue come prima; il browser lo tiene in cache. */
(function () {
  var pendingBtn = null;
  var resetTimer = null;

  document.addEventListener('mousedown', function (e) {
    var btn = e.target.closest('button[type="submit"], input[type="submit"]');
    if (btn && btn.classList.contains('btn') && !btn.disabled) pendingBtn = btn;
  }, true);

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || form.tagName !== 'FORM') return;

    var btn = (pendingBtn && form.contains(pendingBtn)) ? pendingBtn : null;
    if (!btn) btn = form.querySelector('button[type="submit"].btn:not([disabled])');
    pendingBtn = null;
    if (!btn || btn.disabled) return;

    btn.classList.add('btn-loading');
    // Preserve the submitter name/value via hidden input: disabled controls are
    // excluded from the form entry list, so without this the POST loses keys
    // like `action` used by <button name="action" value="save_draft">.
    if (btn.name) {
      var hidden = form.querySelector('input[type="hidden"][data-submitter-shim="1"]');
      if (!hidden) {
        hidden = document.createElement('input');
        hidden.type = 'hidden';
        hidden.setAttribute('data-submitter-shim', '1');
        form.appendChild(hidden);
      }
      hidden.name = btn.name;
      hidden.value = btn.value != null ? btn.value : '';
    }
    setTimeout(function () { btn.disabled = true; }, 0);

    if (resetTimer) clearTimeout(resetTimer);
    resetTimer = setTimeout(function () {
      btn.disabled = false;
      btn.classList.remove('btn-loading');
    }, 10000);
  });
})();
