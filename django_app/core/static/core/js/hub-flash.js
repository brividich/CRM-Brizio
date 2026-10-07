/* Messaggi flash del portale (toast). Consegna lato server in core/flash_messages.py:
 * - pagina intera: toast già nel markup ([data-hub-flash-stack]);
 * - HTMX/fetch/XHR: header X-Hub-Flash (JSON), letto intercettando fetch e XHR;
 * - download: cookie hub_flash (base64url JSON), letto dalla pagina rimasta aperta.
 * Va caricato nel <head>, prima di qualunque richiesta asincrona. */
(function () {
  if (window.hubFlash) return;

  var MAX_VISIBLE = 5;
  var AUTO_CLOSE_MS = 7000;
  var LONG_TEXT = 160;
  var CARRY_KEY = 'hubFlashCarry';
  var CARRY_WINDOW_MS = 3000;
  var COOKIE = 'hub_flash';
  var pending = [];
  var ready = false;

  function summarize(text) {
    if (text.length <= LONG_TEXT) return text;
    var re = /[.;](?=\s)/g, m;
    while ((m = re.exec(text))) {
      var end = m.index + 1;
      if (end > LONG_TEXT) break;
      if (end >= 20) return text.slice(0, end);
    }
    return text.slice(0, 140).replace(/\s+$/, '') + '…';
  }

  function stack() {
    var el = document.querySelector('[data-hub-flash-stack]');
    if (!el) {
      el = document.createElement('div');
      el.className = 'hub-flash-stack';
      el.setAttribute('data-hub-flash-stack', '');
      el.setAttribute('aria-live', 'polite');
      el.setAttribute('aria-atomic', 'false');
      document.body.appendChild(el);
    }
    if (!el.querySelector('.hub-flash-bar')) {
      var bar = document.createElement('div');
      bar.className = 'hub-flash-bar';
      bar.hidden = true;
      bar.innerHTML = '<span class="hub-flash-hidden-count"></span>' +
        '<button type="button" class="hub-flash-closeall">Chiudi tutti</button>';
      el.appendChild(bar);
    }
    return el;
  }

  function toasts(el) {
    return Array.prototype.slice.call((el || stack()).querySelectorAll('.hub-flash:not(.hub-flash-out)'));
  }

  function layout() {
    var el = stack();
    var list = toasts(el);
    var hidden = Math.max(0, list.length - MAX_VISIBLE);
    list.forEach(function (t, i) { t.classList.toggle('hub-flash-overflow', i < hidden); });
    var bar = el.querySelector('.hub-flash-bar');
    bar.hidden = list.length < 2;
    bar.querySelector('.hub-flash-hidden-count').textContent = hidden ? '+' + hidden + ' altri' : '';
    el.appendChild(bar);
  }

  function forget(toast) {
    var id = toast.getAttribute('data-carry-id');
    if (!id) return;
    try {
      var carry = JSON.parse(sessionStorage.getItem(CARRY_KEY) || '[]').filter(function (c) { return c.id !== id; });
      sessionStorage.setItem(CARRY_KEY, JSON.stringify(carry));
    } catch (e) {}
  }

  function close(toast) {
    if (!toast || toast.classList.contains('hub-flash-out')) return;
    toast.classList.add('hub-flash-out');
    forget(toast);
    setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); layout(); }, 180);
    layout();
  }

  function arm(toast) {
    if (toast._hubFlashTimer) clearTimeout(toast._hubFlashTimer);
    if (/\bhub-flash-(success|info|debug)\b/.test(toast.className)) {
      toast._hubFlashTimer = setTimeout(function () { close(toast); }, AUTO_CLOSE_MS);
    }
  }

  function setCount(toast, count) {
    toast.setAttribute('data-count', String(count));
    var badge = toast.querySelector('.hub-flash-count');
    badge.textContent = '×' + count;
    badge.hidden = count < 2;
  }

  function build(item) {
    var level = String(item.level || 'info').replace(/[^a-z]/g, '') || 'info';
    var text = String(item.text || '');
    var summary = summarize(text);
    var toast = document.createElement('div');
    toast.className = 'hub-flash hub-flash-' + level;
    toast.setAttribute('role', level === 'error' ? 'alert' : 'status');
    toast.setAttribute('data-hub-flash-key', level + '|' + text);
    var body = document.createElement('div');
    body.className = 'hub-flash-body';
    var span = document.createElement('span');
    span.className = 'hub-flash-text';
    span.textContent = summary;
    var badge = document.createElement('span');
    badge.className = 'hub-flash-count';
    body.appendChild(span);
    body.appendChild(badge);
    if (summary !== text) {
      var more = document.createElement('button');
      more.type = 'button';
      more.className = 'hub-flash-more';
      more.setAttribute('aria-expanded', 'false');
      more.textContent = 'Dettagli';
      var detail = document.createElement('div');
      detail.className = 'hub-flash-detail';
      detail.hidden = true;
      detail.textContent = text;
      body.appendChild(more);
      body.appendChild(detail);
    }
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'hub-flash-close';
    btn.setAttribute('aria-label', 'Chiudi messaggio');
    btn.innerHTML = '&times;';
    toast.appendChild(body);
    toast.appendChild(btn);
    setCount(toast, Math.max(1, Number(item.count) || 1));
    return toast;
  }

  function carry(item, toast) {
    try {
      var id = String(Date.now()) + Math.random().toString(36).slice(2, 7);
      var list = JSON.parse(sessionStorage.getItem(CARRY_KEY) || '[]');
      list.push({ id: id, at: Date.now(), level: item.level, text: item.text, count: item.count });
      sessionStorage.setItem(CARRY_KEY, JSON.stringify(list.slice(-20)));
      toast.setAttribute('data-carry-id', id);
    } catch (e) {}
  }

  function render(items, opts) {
    var el = stack();
    items.forEach(function (item) {
      if (!item || !item.text) return;
      var key = String(item.level || 'info') + '|' + String(item.text);
      var same = toasts(el).filter(function (t) { return t.getAttribute('data-hub-flash-key') === key; })[0];
      if (same) {
        setCount(same, Number(same.getAttribute('data-count') || 1) + (Number(item.count) || 1));
        el.insertBefore(same, el.querySelector('.hub-flash-bar'));
        arm(same);
        return;
      }
      var toast = build(item);
      el.insertBefore(toast, el.querySelector('.hub-flash-bar'));
      if (opts && opts.carry) carry(item, toast);
      arm(toast);
    });
    layout();
  }

  function show(items, opts) {
    if (!Array.isArray(items) || !items.length) return;
    if (!ready) { pending.push([items, opts]); return; }
    render(items, opts);
  }

  function fromHeader(value) {
    if (!value) return;
    try { show(JSON.parse(value), { carry: true }); } catch (e) {}
  }

  /* fetch */
  if (window.fetch) {
    var origFetch = window.fetch;
    window.fetch = function () {
      return origFetch.apply(this, arguments).then(function (response) {
        try { fromHeader(response.headers.get('X-Hub-Flash')); } catch (e) {}
        return response;
      });
    };
  }
  /* XHR (anche HTMX) */
  if (window.XMLHttpRequest) {
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.send = function () {
      this.addEventListener('load', function () {
        try { fromHeader(this.getResponseHeader('X-Hub-Flash')); } catch (e) {}
      });
      return origSend.apply(this, arguments);
    };
  }

  /* download: cookie lasciato dalla risposta col file */
  function readCookie() {
    var m = document.cookie.match(/(?:^|;\s*)hub_flash=([^;]+)/);
    if (!m) return;
    document.cookie = COOKIE + '=; Max-Age=0; path=/; SameSite=Lax';
    try {
      var b64 = m[1].replace(/-/g, '+').replace(/_/g, '/');
      while (b64.length % 4) b64 += '=';
      show(JSON.parse(atob(b64)));
    } catch (e) {}
  }

  function onReady() {
    ready = true;
    var el = stack();
    toasts(el).forEach(arm);
    try {
      var now = Date.now();
      var carried = JSON.parse(sessionStorage.getItem(CARRY_KEY) || '[]').filter(function (c) { return now - c.at < 60000; });
      sessionStorage.removeItem(CARRY_KEY);
      if (carried.length) render(carried);
    } catch (e) {}
    pending.splice(0).forEach(function (p) { render(p[0], p[1]); });
    layout();
    readCookie();
    setInterval(function () { if (document.visibilityState !== 'hidden') readCookie(); }, 1000);

    el.addEventListener('click', function (e) {
      var closeBtn = e.target.closest('.hub-flash-close');
      if (closeBtn) { close(closeBtn.closest('.hub-flash')); return; }
      if (e.target.closest('.hub-flash-closeall')) { toasts(el).forEach(close); return; }
      var more = e.target.closest('.hub-flash-more');
      if (more) {
        var toast = more.closest('.hub-flash');
        var detail = toast.querySelector('.hub-flash-detail');
        var open = detail.hidden;
        detail.hidden = !open;
        toast.querySelector('.hub-flash-text').hidden = open;
        more.textContent = open ? 'Meno' : 'Dettagli';
        more.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (open && toast._hubFlashTimer) clearTimeout(toast._hubFlashTimer);
      }
    });
    el.addEventListener('mouseenter', function () {
      toasts(el).forEach(function (t) { if (t._hubFlashTimer) clearTimeout(t._hubFlashTimer); });
    });
    el.addEventListener('mouseleave', function () {
      toasts(el).forEach(function (t) { if (!t.querySelector('.hub-flash-detail:not([hidden])')) arm(t); });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      var list = toasts(el);
      if (!list.length) return;
      if (document.querySelector('dialog[open], .gs-overlay.gs-open, [data-notification-shell].open')) return;
      list.forEach(close);
    });
  }

  /* Messaggi arrivati via header su una pagina che sta per essere lasciata:
     se compaiono da meno di 3 s li ripropone la pagina successiva. */
  window.addEventListener('pagehide', function () {
    try {
      var now = Date.now();
      var list = JSON.parse(sessionStorage.getItem(CARRY_KEY) || '[]').filter(function (c) { return now - c.at < CARRY_WINDOW_MS; });
      if (list.length) sessionStorage.setItem(CARRY_KEY, JSON.stringify(list));
      else sessionStorage.removeItem(CARRY_KEY);
    } catch (e) {}
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', onReady);
  else onReady();

  window.hubFlash = { show: function (items) { show(items); } };
})();
