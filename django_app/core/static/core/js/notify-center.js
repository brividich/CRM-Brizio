/* NOVICROM HUB — centro notifiche: popup live, lettura, «segna tutte come lette». URL da window.NHUB_NOTIFY.
 * Spostato da template inline (12/11/2026): caricato nello stesso punto e senza defer,
 * quindi si esegue come prima; il browser lo tiene in cache. */
(function () {
  var shell = document.querySelector('[data-notification-shell]');
  var panel = document.getElementById('notify-center-panel');
  if (!shell || !panel) return;
  var liveUrl = (window.NHUB_NOTIFY || {}).live;
  var ackUrl = (window.NHUB_NOTIFY || {}).ack;
  var pollMs = 15000;
  var pollTimer = null;
  var seenPopupIds = {};

  function csrf() {
    var meta = document.querySelector("meta[name='csrf-token']");
    return meta ? meta.getAttribute("content") : "";
  }
  function openPanel() { shell.classList.add('open'); }
  function closePanel() { shell.classList.remove('open'); }
  function displayCount(count) {
    count = Number(count || 0);
    return count > 99 ? "99+" : String(count);
  }
  function setNotificationBadges(count) {
    count = Math.max(0, Number(count || 0));
    document.querySelectorAll('[data-notification-badge-host]').forEach(function (host) {
      var badge = host.querySelector('[data-notification-badge]');
      if (count > 0) {
        if (!badge) {
          badge = document.createElement('span');
          badge.setAttribute('data-notification-badge', '');
          badge.setAttribute('aria-hidden', 'true');
          badge.className = host.classList.contains('sb-item') ? 'sb-item-badge' : 'nav-icon-badge';
          host.appendChild(badge);
        }
        badge.textContent = displayCount(count);
        host.setAttribute('aria-label', 'Notifiche: ' + count + ' non lette');
        host.setAttribute('title', 'Notifiche (' + count + ' non lette)');
      } else {
        if (badge) badge.remove();
        host.setAttribute('aria-label', 'Notifiche');
        host.setAttribute('title', 'Notifiche');
      }
    });
  }
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
  function toastStack() {
    var stack = document.querySelector('[data-notification-live-stack]');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'notify-live-stack';
      stack.setAttribute('data-notification-live-stack', '');
      stack.setAttribute('aria-live', 'polite');
      stack.setAttribute('aria-atomic', 'false');
      document.body.appendChild(stack);
    }
    return stack;
  }
  function removeToast(toast) {
    if (!toast) return;
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-8px)';
    setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 180);
  }
  function ackPopupIds(ids) {
    ids = (ids || []).filter(Boolean);
    if (!ids.length) return;
    fetch(ackUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf(),
        'X-Requested-With': 'XMLHttpRequest'
      },
      body: JSON.stringify({ ids: ids })
    }).catch(function () {});
  }
  function showLivePopups(items) {
    items = Array.isArray(items) ? items : [];
    var fresh = items.filter(function (item) {
      var id = Number(item && item.id);
      if (!id || seenPopupIds[id]) return false;
      seenPopupIds[id] = true;
      return true;
    });
    if (!fresh.length) return;

    var stack = toastStack();
    var ackIds = [];
    fresh.forEach(function (item) {
      var id = Number(item.id);
      ackIds.push(id);
      var typeClass = String(item.tipo || 'generico').replace(/[^a-z0-9_-]/gi, '_');
      var toast = document.createElement('article');
      toast.className = 'notify-live-toast notify-live-toast-' + typeClass;
      toast.setAttribute('data-notification-live-id', String(id));
      toast.innerHTML =
        '<span class="notify-live-dot" aria-hidden="true">' + escapeHtml(item.tipo_icona || '') + '</span>' +
        '<div class="notify-live-copy">' +
          '<div class="notify-live-kicker">' + escapeHtml(item.tipo_label || 'Notifica') + '</div>' +
          '<div class="notify-live-message">' + escapeHtml(item.messaggio || '') + '</div>' +
          (item.created_label ? '<div class="notify-live-meta">' + escapeHtml(item.created_label) + '</div>' : '') +
        '</div>' +
        '<div class="notify-live-actions">' +
          (item.url_azione ? '<a class="notify-live-open" data-notifica-open="' + id + '" href="' + escapeHtml(item.url_azione) + '">Apri</a>' : '') +
          '<button type="button" class="notify-live-close" aria-label="Chiudi notifica">&times;</button>' +
        '</div>';
      var closeBtn = toast.querySelector('.notify-live-close');
      if (closeBtn) closeBtn.addEventListener('click', function () { removeToast(toast); });
      stack.prepend(toast);
      setTimeout(function () { removeToast(toast); }, 14000);
    });
    ackPopupIds(ackIds);
  }
  function refreshPanel() {
    if (window.htmx) window.htmx.trigger(panel, 'refresh');
  }
  function pollLiveNotifications() {
    if (document.visibilityState === 'hidden') return;
    fetch(liveUrl, {
      headers: {
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
      },
      cache: 'no-store'
    }).then(function (response) {
      return response.ok ? response.json() : null;
    }).then(function (data) {
      if (!data || data.ok === false) return;
      setNotificationBadges(data.unread_count || 0);
      showLivePopups(data.popup_notifications || []);
      if ((data.popup_notifications || []).length) refreshPanel();
      if (data.poll_after_ms) pollMs = Math.max(5000, Number(data.poll_after_ms) || pollMs);
    }).catch(function () {});
  }
  document.querySelectorAll('[data-notifica-id]').forEach(function (node) {
    var id = Number(node.getAttribute('data-notifica-id'));
    if (id) seenPopupIds[id] = true;
  });

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-notification-toggle]')) {
      event.preventDefault();
      shell.classList.toggle('open');
      refreshPanel();
      return;
    }
    if (shell.classList.contains('open') && !event.target.closest('.notify-center-panel')) {
      closePanel();
    }
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closePanel();
  });
  document.addEventListener('click', function (event) {
    var btn = event.target.closest('[data-notification-mark-read]');
    if (!btn) return;
    btn.disabled = true;
    fetch((window.NHUB_NOTIFY || {}).readAll, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" }
    }).then(function () {
      setNotificationBadges(0);
      refreshPanel();
    }).finally(function () { btn.disabled = false; });
  });
  // «Apri» su una notifica (campanella, banner, popup, pagina) = letta.
  // keepalive: la richiesta sopravvive alla navigazione verso url_azione.
  var readUrlTpl = (window.NHUB_NOTIFY || {}).readOne;
  document.addEventListener('click', function (event) {
    var link = event.target.closest('[data-notifica-open]');
    if (!link) return;
    var id = Number(link.getAttribute('data-notifica-open'));
    if (!id) return;
    try {
      fetch(readUrlTpl.replace('/0/', '/' + id + '/'), {
        method: 'POST',
        keepalive: true,
        headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' }
      }).catch(function () {});
    } catch (e) {}
  });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') pollLiveNotifications();
  });

  pollLiveNotifications();
  pollTimer = setInterval(pollLiveNotifications, pollMs);
})();
