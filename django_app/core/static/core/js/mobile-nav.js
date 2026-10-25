/* Menu di modulo su smartphone (≤720px).
   Le barre di navigazione dei moduli (subnav del portale, Anagrafica, Assenze,
   Assets, SOC, Contatori, o qualsiasi [data-mnav]) sul telefono non scorrono più
   di lato: diventano un pulsante con la sezione corrente che apre un pannello dal
   basso con TUTTE le voci, raggruppate e filtrabili. La barra originale resta nel
   DOM (nascosta): le voci del pannello sono copie dei suoi link, i permessi li ha
   già decisi il server quando l'ha resa. Sopra i 720px non cambia niente. */
(function () {
  "use strict";

  var NAV_SEL = "[data-mnav], .subnav, .hrnav, .abs-subnav, .as-side, .soc-subnav, .cnav";
  /* Contenitori che raggruppano voci (tendine, gruppi della sidebar). */
  var GROUP_SEL = "[data-mnav-group], .hrnav-dd, .as-nav-group, [role='group'][aria-label], nav[aria-label]";
  var GROUP_LABEL_SEL = ".hrnav-pill, .hrnav-dd-btn, .as-nav-parent .as-link";
  /* Intestazioni: di sezione (fuori dai gruppi) o di colonna (dentro un gruppo). */
  var HEAD_SEL = "[data-mnav-head], .as-nav-head, .hrnav-dd-head";
  var BADGE_SEL = "[class*='badge'], .hrnav-sub-n, .nav-soon, .dot";
  var SKIP_SEL = "[data-mnav-skip], .as-brand-link";
  /* Nome del modulo nel pannello, per le barre che non hanno data-mnav. */
  var TITLES = { "hrnav": "Anagrafica", "abs-subnav": "Assenze", "as-side": "Assets", "soc-subnav": "SOC", "cnav": "Contatori" };
  var MIN_LINKS = 4;

  var mq = window.matchMedia("(max-width:720px)");
  var bars = [];
  var sheet = null;

  function clean(text) {
    return String(text || "").replace(/[▾▸›»]/g, "").replace(/\s+/g, " ").trim();
  }

  function labelOf(el) {
    var c = el.cloneNode(true);
    c.querySelectorAll("svg, " + BADGE_SEL).forEach(function (n) { n.remove(); });
    return clean(c.textContent) || clean(el.getAttribute("aria-label")) || clean(el.getAttribute("title"));
  }

  function badgeOf(el) {
    var b = el.querySelector(BADGE_SEL);
    var t = b ? clean(b.textContent) : "";
    return t && t.length <= 6 ? t : "";
  }

  function groupLabel(g) {
    if (g.hasAttribute("data-mnav-group")) return clean(g.getAttribute("data-mnav-group"));
    var t = g.querySelector(GROUP_LABEL_SEL);
    if (t) return labelOf(t);
    return clean(g.getAttribute("aria-label"));
  }

  function isActive(a) {
    return a.classList.contains("active") || a.hasAttribute("aria-current");
  }

  /* Legge la barra in ordine di documento: voci + intestazioni. */
  function collect(root) {
    var rows = [];
    var seen = {};
    var section = "";
    var lastHead = null;
    var nodes = root.querySelectorAll("a[href], " + HEAD_SEL);
    nodes.forEach(function (el) {
      if (el.matches(HEAD_SEL)) {
        var inGroup = el.parentElement && el.parentElement.closest(GROUP_SEL);
        if (!inGroup || !root.contains(inGroup) || inGroup === root) section = labelOf(el);
        return;
      }
      var href = el.getAttribute("href") || "";
      if (!href || href === "#" || href.indexOf("javascript:") === 0 || el.matches(SKIP_SEL)) return;
      if (el.closest("[hidden]") && !el.closest(".hrnav-dd-menu, .as-nav-children")) return;
      if (seen[href]) return;
      seen[href] = true;

      var g = el.parentElement ? el.parentElement.closest(GROUP_SEL) : null;
      if (g && (g === root || !root.contains(g))) g = null;
      var head = g ? groupLabel(g) : section;
      var col = el.closest(".hrnav-dd-col");
      var sub = col && col.querySelector(".hrnav-dd-head") ? labelOf(col.querySelector(".hrnav-dd-head")) : "";
      var key = head + "|" + sub;
      if (key !== lastHead) {
        if (head && (!lastHead || lastHead.split("|")[0] !== head)) rows.push({ head: head, level: 1 });
        if (sub) rows.push({ head: sub, level: 2 });
        lastHead = key;
      }
      var label = labelOf(el);
      /* La voce che apre la panoramica del gruppo ha lo stesso nome del gruppo. */
      if (g && label === head) label = "Panoramica";
      rows.push({ link: el, label: label, badge: badgeOf(el), active: isActive(el), group: head });
    });
    return rows;
  }

  function currentOf(rows) {
    var links = rows.filter(function (r) { return r.link; });
    var page = links.filter(function (r) { return r.link.getAttribute("aria-current") === "page"; });
    if (page.length) return page[page.length - 1];
    var act = links.filter(function (r) { return r.active; });
    return act.length ? act[act.length - 1] : null;
  }

  function moduleTitle(root) {
    var t = clean(root.getAttribute("data-mnav"));
    if (t) return t;
    for (var cls in TITLES) { if (root.classList.contains(cls)) return TITLES[cls]; }
    /* Subnav generica: il nome è la voce accesa della barra in alto. */
    var top = document.querySelector(".topnav .nav-a.active .nav-label, .sidebar .sb-item.active .sb-label");
    return (top && clean(top.textContent)) || clean(root.getAttribute("aria-label")) || "Sezioni";
  }

  /* ── Pannello dal basso (uno solo, riusato) ───────────────────────── */
  function ensureSheet() {
    if (sheet) return sheet;
    var wrap = document.createElement("div");
    wrap.className = "mnav-sheet";
    wrap.hidden = true;
    wrap.innerHTML =
      '<div class="mnav-backdrop" data-mnav-close></div>' +
      '<div class="mnav-panel" role="dialog" aria-modal="true" aria-labelledby="mnav-title">' +
        '<div class="mnav-grip" aria-hidden="true"></div>' +
        '<div class="mnav-head">' +
          '<h2 class="mnav-title" id="mnav-title"></h2>' +
          '<button type="button" class="mnav-x" data-mnav-close aria-label="Chiudi">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>' +
          '</button>' +
        '</div>' +
        '<div class="mnav-filter" hidden>' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
          '<input type="search" placeholder="Filtra le voci" autocomplete="off" aria-label="Filtra le voci">' +
        '</div>' +
        '<div class="mnav-list"></div>' +
        '<p class="mnav-empty" hidden>Nessuna voce corrisponde.</p>' +
      '</div>';
    document.body.appendChild(wrap);
    var input = wrap.querySelector(".mnav-filter input");
    input.addEventListener("input", function () { applyFilter(wrap, input.value); });
    wrap.addEventListener("click", function (e) {
      if (e.target.closest("[data-mnav-close]")) closeSheet();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !wrap.hidden) closeSheet();
    });
    /* Trascinando giù la maniglia/intestazione il pannello si chiude. */
    var panel = wrap.querySelector(".mnav-panel");
    var startY = null;
    panel.addEventListener("touchstart", function (e) {
      if (!e.target.closest(".mnav-grip, .mnav-head")) return;
      startY = e.touches[0].clientY;
    }, { passive: true });
    panel.addEventListener("touchmove", function (e) {
      if (startY === null) return;
      var dy = Math.max(0, e.touches[0].clientY - startY);
      panel.style.transform = "translateY(" + dy + "px)";
    }, { passive: true });
    panel.addEventListener("touchend", function (e) {
      if (startY === null) return;
      var dy = e.changedTouches[0].clientY - startY;
      startY = null;
      panel.style.transform = "";
      if (dy > 90) closeSheet();
    });
    sheet = wrap;
    return wrap;
  }

  function applyFilter(wrap, q) {
    q = clean(q).toLowerCase();
    var any = false;
    var items = wrap.querySelectorAll(".mnav-item");
    items.forEach(function (it) {
      var hit = !q || it.getAttribute("data-text").indexOf(q) !== -1;
      it.hidden = !hit;
      if (hit) any = true;
    });
    /* Un'intestazione resta solo se sotto ha almeno una voce visibile. */
    wrap.querySelectorAll(".mnav-h").forEach(function (h) {
      var n = h.nextElementSibling, vis = false;
      while (n && !n.classList.contains("mnav-h1") && !(h.classList.contains("mnav-h2") && n.classList.contains("mnav-h2"))) {
        if (n.classList.contains("mnav-item") && !n.hidden) { vis = true; break; }
        n = n.nextElementSibling;
      }
      h.hidden = !vis;
    });
    wrap.querySelector(".mnav-empty").hidden = any;
  }

  var lastTrigger = null;

  function openSheet(bar) {
    var wrap = ensureSheet();
    var rows = collect(bar.root);
    wrap.querySelector(".mnav-title").textContent = bar.title;
    var list = wrap.querySelector(".mnav-list");
    list.innerHTML = "";
    var nLinks = 0;
    rows.forEach(function (r) {
      if (r.head) {
        var h = document.createElement("div");
        h.className = "mnav-h mnav-h" + r.level;
        h.textContent = r.head;
        list.appendChild(h);
        return;
      }
      nLinks++;
      var a = document.createElement("a");
      a.className = "mnav-item" + (r.active ? " is-active" : "");
      a.href = r.link.getAttribute("href");
      if (r.link.getAttribute("target")) { a.target = r.link.getAttribute("target"); a.rel = "noopener"; }
      if (r.active) a.setAttribute("aria-current", "page");
      a.setAttribute("data-text", (r.label + " " + (r.group || "")).toLowerCase());
      var span = document.createElement("span");
      span.className = "mnav-item-label";
      span.textContent = r.label;
      a.appendChild(span);
      if (r.badge) {
        var b = document.createElement("span");
        b.className = "mnav-badge";
        b.textContent = r.badge;
        a.appendChild(b);
      }
      list.appendChild(a);
    });
    var filter = wrap.querySelector(".mnav-filter");
    var input = filter.querySelector("input");
    filter.hidden = nLinks <= 8;
    input.value = "";
    applyFilter(wrap, "");
    lastTrigger = bar.trigger;
    wrap.hidden = false;
    document.documentElement.classList.add("mnav-lock");
    bar.trigger.setAttribute("aria-expanded", "true");
    requestAnimationFrame(function () {
      wrap.classList.add("is-open");
      var cur = list.querySelector(".is-active");
      if (cur) cur.scrollIntoView({ block: "center" });
      (cur || wrap.querySelector(".mnav-x")).focus({ preventScroll: true });
    });
  }

  function closeSheet() {
    if (!sheet || sheet.hidden) return;
    sheet.classList.remove("is-open");
    document.documentElement.classList.remove("mnav-lock");
    if (lastTrigger) {
      lastTrigger.setAttribute("aria-expanded", "false");
      lastTrigger.focus({ preventScroll: true });
    }
    setTimeout(function () { if (!sheet.classList.contains("is-open")) sheet.hidden = true; }, 200);
  }

  /* ── Pulsante che sostituisce la barra ───────────────────────────── */
  function buildTrigger(bar) {
    var rows = collect(bar.root);
    var cur = currentOf(rows);
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mnav-trigger";
    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-expanded", "false");
    var kicker = cur && cur.group && cur.group !== cur.label ? cur.group : bar.title;
    btn.innerHTML =
      '<svg class="mnav-trigger-ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/></svg>' +
      '<span class="mnav-trigger-text"><span class="mnav-trigger-kicker"></span><span class="mnav-trigger-label"></span></span>' +
      '<svg class="mnav-trigger-caret" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    btn.querySelector(".mnav-trigger-kicker").textContent = kicker;
    btn.querySelector(".mnav-trigger-label").textContent = cur ? cur.label : "Scegli una sezione";
    btn.setAttribute("aria-label", "Menu " + bar.title + (cur ? ": sei in " + cur.label : ""));
    btn.addEventListener("click", function () { openSheet(bar); });
    var host = document.createElement("div");
    host.className = "mnav-bar";
    host.appendChild(btn);
    return host;
  }

  function linkCount(root) {
    return collect(root).filter(function (r) { return r.link; }).length;
  }

  function setup() {
    document.querySelectorAll(NAV_SEL).forEach(function (root) {
      if (root.hasAttribute("data-mnav-off") || root.__mnav) return;
      /* Barre annidate (es. .subnav dentro .hrnav): vale la più esterna. */
      var outer = root.parentElement && root.parentElement.closest(NAV_SEL);
      if (outer && !outer.hasAttribute("data-mnav-off")) return;
      if (linkCount(root) < MIN_LINKS) return;
      var bar = { root: root, title: moduleTitle(root) };
      var host = buildTrigger(bar);
      bar.trigger = host.querySelector(".mnav-trigger");
      bar.host = host;
      /* La sidebar di Assets sta dentro la griglia: il pulsante va sopra la griglia. */
      var anchor = root.classList.contains("as-side") ? root.closest(".as-shell") || root : root;
      anchor.parentNode.insertBefore(host, anchor);
      /* Barra dentro al contenuto (non a tutta larghezza): niente fascia bianca. */
      if (!anchor.parentNode.classList.contains("main-wrap") && !root.classList.contains("hrnav")) host.classList.add("mnav-bar--inline");
      root.__mnav = bar;
      bars.push(bar);
    });
    sync();
  }

  function sync() {
    var on = mq.matches;
    document.documentElement.classList.toggle("mnav-on", on);
    bars.forEach(function (bar) {
      bar.root.classList.toggle("mnav-collapsed", on);
      bar.host.hidden = !on;
    });
    if (!on) closeSheet();
  }

  if (mq.addEventListener) mq.addEventListener("change", sync);
  else if (mq.addListener) mq.addListener(sync);

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup);
  else setup();
})();
