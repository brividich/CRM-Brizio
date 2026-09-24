/* NOVICROM HUB — Ricerca unificata (Ctrl+K / Cmd+K, pulsanti [data-gs-open]).
 *
 * Un solo overlay (#gs-overlay in core/base.html) con tre sezioni:
 *  - «Recenti»: ultime pagine aperte dall'utente (localStorage, solo per questo browser);
 *  - «Vai a…»: pagine di navigazione, gia' ACL-filtrate lato server in `command-palette-data`;
 *  - risultati dati (dipendenti, asset, ticket, …) dall'API di ricerca globale (`data-api-url`).
 * Vanilla, nessuna dipendenza.
 */
(function () {
  "use strict";

  var overlay = document.getElementById("gs-overlay");
  var input = document.getElementById("gs-input");
  var results = document.getElementById("gs-results");
  var modal = document.getElementById("gs-modal");
  if (!overlay || !input || !results) return;

  var API_URL = overlay.getAttribute("data-api-url") || "";
  var RECENT_KEY = "nhub.recent-pages";
  var RECENT_MAX = 6;

  var PAGES = [];
  try {
    var dataEl = document.getElementById("command-palette-data");
    PAGES = dataEl ? JSON.parse(dataEl.textContent) || [] : [];
  } catch (e) { PAGES = []; }

  var ICONS = {
    page: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/></svg>',
    recent: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    dipendente: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
    asset: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
    ticket: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 8a2 2 0 0 0 0 4v5a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-5a2 2 0 0 1 0-4V5a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1z"/></svg>',
    kickoff: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/></svg>',
    task: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 12 2 2 4-4"/><rect x="3" y="3" width="18" height="18" rx="3"/></svg>',
    procedura: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h12l4 4v12H4z"/><path d="M8 12h8M8 16h5"/></svg>',
    dpi: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/></svg>'
  };
  var LABELS = {
    dipendente: "Dipendenti", asset: "Asset", ticket: "Ticket",
    kickoff: "Kickoff", task: "Attività", procedura: "Procedure", dpi: "DPI"
  };

  var timer = null, seq = 0, sel = -1, nodes = [];
  var lastPages = [], lastData = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function norm(s) {
    return String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }

  /* ── Recenti (per-browser, tollerante a storage bloccato) ───────────── */
  function readRecent() {
    try {
      var raw = window.localStorage.getItem(RECENT_KEY);
      var arr = raw ? JSON.parse(raw) : [];
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }
  function pushRecent(entry) {
    if (!entry || !entry.u || !entry.l) return;
    try {
      var arr = readRecent().filter(function (r) { return r.u !== entry.u; });
      arr.unshift({ l: entry.l, u: entry.u, g: entry.g || "" });
      window.localStorage.setItem(RECENT_KEY, JSON.stringify(arr.slice(0, RECENT_MAX + 1)));
    } catch (e) { /* storage non disponibile: nessun recente */ }
  }
  /* Registra la pagina corrente se corrisponde a una voce di navigazione nota. */
  (function recordCurrent() {
    var here = window.location.pathname;
    for (var i = 0; i < PAGES.length; i++) {
      var u = PAGES[i].u;
      if (u && (u === here || u.split("?")[0] === here)) { pushRecent(PAGES[i]); return; }
    }
  })();

  /* ── Filtri ──────────────────────────────────────────────────────────── */
  function matchPages(q) {
    q = norm(q).trim();
    if (!q) return [];
    var terms = q.split(/\s+/);
    var scored = [];
    PAGES.forEach(function (d) {
      var label = norm(d.l), hay = label + " " + norm(d.g);
      if (!terms.every(function (t) { return hay.indexOf(t) !== -1; })) return;
      var score = label.indexOf(terms[0]) === 0 ? 0 : (label.indexOf(terms[0]) !== -1 ? 1 : 2);
      scored.push({ d: d, s: score });
    });
    scored.sort(function (a, b) { return a.s - b.s || a.d.l.localeCompare(b.d.l); });
    return scored.slice(0, 6).map(function (x) { return x.d; });
  }

  /* ── Render ──────────────────────────────────────────────────────────── */
  function sectionHtml(title) {
    return '<div class="gs-group-label">' + esc(title) + "</div>";
  }
  function itemHtml(it) {
    return '<a class="gs-item gs-tipo-' + esc(it.kind) + '" href="' + esc(it.url) + '" role="option"' +
      (it.recent ? " data-gs-recent" : "") + ' data-label="' + esc(it.label) + '" data-group="' + esc(it.group || "") + '">' +
      '<span class="gs-item-icon" aria-hidden="true">' + (ICONS[it.kind] || ICONS.page) + "</span>" +
      '<span class="gs-item-body">' +
        (it.module ? '<span class="gs-item-module">' + esc(it.module) + "</span>" : "") +
        '<span class="gs-item-label">' + esc(it.label) + "</span>" +
        (it.sub ? '<span class="gs-item-sub">' + esc(it.sub) + "</span>" : "") +
        (it.preview ? '<span class="gs-item-preview">' + esc(it.preview) + "</span>" : "") +
      "</span>" +
      '<span class="gs-item-arrow" aria-hidden="true">&#8594;</span>' +
      "</a>";
  }
  function pageItem(d, recent) {
    return { kind: recent ? "recent" : "page", label: d.l, sub: d.g, url: d.u, group: d.g, recent: !!recent };
  }

  function render(q) {
    var html = "";
    var here = window.location.pathname;
    if (!q) {
      var rec = readRecent().filter(function (r) { return r.u.split("?")[0] !== here; }).slice(0, RECENT_MAX);
      if (rec.length) {
        html += sectionHtml("Recenti");
        rec.forEach(function (r) { html += itemHtml(pageItem(r, true)); });
      }
      if (!html) {
        html = '<div class="gs-empty">Digita il nome di una pagina, di un dipendente, di un asset, di un ticket…</div>';
      }
    } else {
      if (lastPages.length) {
        html += sectionHtml("Vai a…");
        lastPages.forEach(function (d) { html += itemHtml(pageItem(d, false)); });
      }
      var data = lastData;
      if (data && data.results && data.results.length) {
        var groups = {}, order = [];
        data.results.forEach(function (r) {
          if (!groups[r.tipo]) { groups[r.tipo] = []; order.push(r.tipo); }
          groups[r.tipo].push(r);
        });
        order.forEach(function (tipo) {
          html += sectionHtml(LABELS[tipo] || tipo);
          groups[tipo].forEach(function (r) {
            html += itemHtml({ kind: r.tipo, label: r.label, sub: r.sub, preview: r.preview, module: r.module, url: r.url });
          });
        });
      }
      if (!html) {
        html = q.length < 2
          ? '<div class="gs-empty">Digita almeno 2 caratteri</div>'
          : data === null
            ? '<div class="gs-empty">Ricerca in corso…</div>'
            : '<div class="gs-empty">Nessun risultato per «' + esc(q) + '»</div>';
      }
    }
    results.innerHTML = html;
    nodes = Array.prototype.slice.call(results.querySelectorAll(".gs-item"));
    setSelected(nodes.length ? 0 : -1);
  }

  function setSelected(i) {
    nodes.forEach(function (n) { n.classList.remove("gs-selected"); n.setAttribute("aria-selected", "false"); });
    sel = i;
    if (i >= 0 && i < nodes.length) {
      nodes[i].classList.add("gs-selected");
      nodes[i].setAttribute("aria-selected", "true");
      nodes[i].scrollIntoView({ block: "nearest" });
    }
  }

  /* ── Ricerca ─────────────────────────────────────────────────────────── */
  function search(q) {
    if (!API_URL || q.length < 2) { lastData = { results: [] }; render(q); return; }
    var my = ++seq;
    fetch(API_URL + "?q=" + encodeURIComponent(q), { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.ok ? r.json() : { results: [] }; })
      .then(function (data) {
        if (my !== seq || input.value.trim() !== q) return;
        lastData = data || { results: [] };
        var keep = sel >= 0 && nodes[sel] ? nodes[sel].getAttribute("href") : null;
        render(q);
        if (keep) nodes.forEach(function (n, i) { if (n.getAttribute("href") === keep) setSelected(i); });
      })
      .catch(function () { if (my === seq) { lastData = { results: [] }; render(q); } });
  }

  function remember(node) {
    if (!node) return;
    var kind = node.className.match(/gs-tipo-(\w+)/);
    if (kind && (kind[1] === "page" || kind[1] === "recent")) {
      pushRecent({ l: node.getAttribute("data-label"), u: node.getAttribute("href"), g: node.getAttribute("data-group") });
    }
  }

  /* ── Apertura / chiusura ─────────────────────────────────────────────── */
  var lastFocus = null;
  function isOpen() { return overlay.classList.contains("gs-open"); }
  function open() {
    if (isOpen()) return;
    lastFocus = document.activeElement;
    overlay.classList.add("gs-open");
    input.value = "";
    seq++; lastPages = []; lastData = null;
    render("");
    input.focus();
  }
  function close() {
    if (!isOpen()) return;
    overlay.classList.remove("gs-open");
    clearTimeout(timer);
    seq++;
    results.innerHTML = "";
    nodes = []; sel = -1;
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  input.addEventListener("input", function () {
    clearTimeout(timer);
    var q = input.value.trim();
    seq++;
    if (!q) { render(""); return; }
    lastPages = matchPages(q);
    lastData = null;
    render(q);
    timer = setTimeout(function () { search(q); }, 200);
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") { e.preventDefault(); if (nodes.length) setSelected((sel + 1) % nodes.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); if (nodes.length) setSelected((sel - 1 + nodes.length) % nodes.length); }
    else if (e.key === "Enter") {
      e.preventDefault();
      var n = nodes[sel >= 0 ? sel : 0];
      if (n) { remember(n); window.location.href = n.getAttribute("href"); }
    }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  });

  results.addEventListener("click", function (e) {
    var n = e.target.closest(".gs-item");
    if (n) { remember(n); close(); }
  });
  results.addEventListener("mousemove", function (e) {
    var n = e.target.closest(".gs-item");
    if (n) { var i = nodes.indexOf(n); if (i !== sel && i >= 0) setSelected(i); }
  });

  overlay.addEventListener("click", function (e) { if (modal && !modal.contains(e.target)) close(); });

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-gs-open]")) { e.preventDefault(); e.stopPropagation(); open(); }
  });

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (isOpen()) close(); else open();
    } else if (e.key === "Escape" && isOpen()) {
      close();
    }
  });
})();
