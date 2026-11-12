/* NOVICROM HUB — barra laterale: apri/chiudi e salvataggio della preferenza (URL da data-toggle-url).
 * Spostato da template inline (12/11/2026): caricato nello stesso punto e senza defer,
 * quindi si esegue come prima; il browser lo tiene in cache. */
(function () {
  var sidebar = document.getElementById('sidebar');
  var toggle = document.getElementById('sb-toggle');
  var body = document.body;
  if (!sidebar || !toggle) return;

  var TOGGLE_URL = sidebar ? sidebar.getAttribute('data-toggle-url') : '';
  var LS_KEY = 'sb_collapsed';
  var CSRF_RE = /csrftoken=([^;]+)/;

  function csrf() { return (document.cookie.match(CSRF_RE) || [])[1] || ''; }

  function syncToggleState() {
    toggle.setAttribute('aria-expanded', body.classList.contains('sb-collapsed') ? 'false' : 'true');
  }

  function persistCollapsed(collapsed) {
    try { localStorage.setItem(LS_KEY, collapsed ? '1' : '0'); } catch (e) {}
    fetch(TOGGLE_URL, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf() },
      body: new URLSearchParams({ sidebar_collapsed: collapsed ? '1' : '0' })
    }).catch(function () {});
  }

  syncToggleState();

  toggle.addEventListener('click', function () {
    var nowCollapsed = body.classList.toggle('sb-collapsed');
    syncToggleState();
    persistCollapsed(nowCollapsed);
  });

  sidebar.querySelectorAll('.sb-cat-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var cat = btn.closest('.sb-category');
      if (!cat) return;
      var isOpen = cat.classList.contains('open');

      sidebar.querySelectorAll('.sb-category.open:not(.active)').forEach(function (el) {
        if (el !== cat) {
          el.classList.remove('open');
          el.querySelector('.sb-cat-btn').setAttribute('aria-expanded', 'false');
        }
      });

      cat.classList.toggle('open', !isOpen);
      btn.setAttribute('aria-expanded', !isOpen ? 'true' : 'false');

      if (!isOpen && body.classList.contains('sb-collapsed')) {
        body.classList.remove('sb-collapsed');
        syncToggleState();
        persistCollapsed(false);
      }
    });
  });

  sidebar.querySelectorAll('.sb-mod-toggle').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      var mod = btn.closest('.sb-module');
      if (!mod) return;
      var isOpen = mod.classList.toggle('open');
      btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      if (isOpen && body.classList.contains('sb-collapsed')) {
        body.classList.remove('sb-collapsed');
        syncToggleState();
        persistCollapsed(false);
      }
    });
  });

  document.addEventListener('click', function (e) {
    if (
      body.classList.contains('sb-mobile-open') &&
      !sidebar.contains(e.target) &&
      e.target.id !== 'sb-mobile-toggle' &&
      !e.target.closest('#sb-mobile-toggle')
    ) {
      body.classList.remove('sb-mobile-open');
    }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && body.classList.contains('sb-mobile-open')) {
      body.classList.remove('sb-mobile-open');
    }
  });
})();
