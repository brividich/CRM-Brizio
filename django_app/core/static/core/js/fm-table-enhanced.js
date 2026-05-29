/**
 * fm-table-enhanced.js — sistema tabelle personalizzabili portale Novicrom HUB.
 *
 * Auto-bind su `<table data-table-id="…">` e sulle tabelle dati rilevate automaticamente.
 * Aggiunge per colonna:
 *   - icona sort ↕ / ▲ / ▼  (multi-sort con Shift+click)
 *   - icona filtro (imbuto stile Excel) — click apre popover con input filtro
 *
 * Sopra la tabella appare una barra controlli con:
 *   - ricerca globale
 *   - menu "Colonne ▾" (toggle visibilità + drag-reorder)
 *   - bottone Reset
 *   - status salvataggio
 *   - contatore risultati
 *
 * Stato per-utente persistito via /api/table-prefs/<table_id>/ (modello UserTablePreference).
 * Vedi docs/ai/TABELLE_PERSONALIZZABILI.md.
 *
 * Persistenza: solo "view config" (visible, order, sort) viene persistita lato
 * DB; filtri di colonna (`filters`) e ricerca globale (`q`) sono *transitori*
 * e vivono nella sessione della pagina — ricaricando o tornando sulla pagina
 * la tabella si apre sempre senza filtri attivi. Opt-in per tabella:
 *   data-fm-persist-filters="1"  → persiste anche filters (e q)
 *   data-fm-persist-search="1"   → persiste solo q
 *
 * Tabelle paginate server-side: alla prima azione utente con filtro/sort/search
 * attivo (e ad init se la preferenza salvata ha già una query attiva), il JS
 * rileva la paginazione cercando link `?page=N` vicini alla tabella e scarica
 * via fetch() tutte le altre pagine, unendo i <tr> al <tbody> corrente; lo
 * stato viene poi riapplicato sul dataset completo. La paginazione nativa
 * viene nascosta e le option dei filtri select rigenerate. Cap di sicurezza:
 * 5.000 righe totali. Opt-out per tabella: `data-fm-fullload="0"` (oppure
 * `data-fm-tbl-pagination-skip="1"`).
 *
 * Attributi `<th>` riconosciuti:
 *   data-col            chiave colonna (inferita automaticamente se assente)
 *   data-col-label      etichetta UI (default: testo header)
 *   data-col-type       text | select | number | date | bool   (default: text)
 *   data-col-options    '[["VAL","Label"], …]'  per type=select
 *   data-col-sortable   "1" per abilitare sort
 *   data-col-filterable "1" per abilitare filtro
 *   data-col-locked     "1" per impedire la nascita
 *
 * Per ordinare per un valore diverso dal testo visibile usare `<td data-sort-value="…">`.
 * Per filtrare per valore esatto (es. select) usare `<td data-value="…">`.
 *
 * Compatibile e sostituisce sortable-table.js: se entrambi sono inclusi, il primo
 * a inizializzare vince (entrambi controllano `dataset.fmTblInited`).
 */
(function () {
  "use strict";

  const API_BASE = "/api/table-prefs/";

  // SVG icona imbuto (filtro). Stile Excel-like: imbuto vuoto / pieno se attivo.
  const FUNNEL_SVG = '<svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">' +
    '<path d="M1.5 2.5h13l-5 6v5l-3-1.5v-3.5z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>' +
    '</svg>';
  const FUNNEL_SVG_ACTIVE = '<svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">' +
    '<path d="M1.5 2.5h13l-5 6v5l-3-1.5v-3.5z" fill="currentColor"/>' +
    '</svg>';

  const SORT_ICON = { none: "↕", asc: "▲", desc: "▼" };

  // ─── Helpers ──────────────────────────────────────────────────────────────

  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function csrfToken() {
    const m = document.cookie.match(/(^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[2]) : "";
  }

  function cleanText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function stripAccents(value) {
    return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  function slugText(value, fallback) {
    const slug = stripAccents(value)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 34);
    return slug || fallback || "col";
  }

  function shortHash(value) {
    let h = 0;
    const s = String(value || "");
    for (let i = 0; i < s.length; i += 1) {
      h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    }
    return Math.abs(h).toString(36).slice(0, 6);
  }

  function cellPlainText(cell) {
    if (!cell) return "";
    return cleanText((cell.dataset && (cell.dataset.value || cell.dataset.sortValue)) || cell.textContent || "");
  }

  function bodyRows(table) {
    return table.tBodies && table.tBodies[0] ? $$("tr", table.tBodies[0]) : [];
  }

  function rowCellCount(row) {
    return row && row.cells ? row.cells.length : 0;
  }

  function headerLabels(table) {
    const thead = table.tHead;
    const firstRow = thead && thead.rows[0];
    if (!firstRow) return [];
    return Array.from(firstRow.cells).map(th => cleanText(th.dataset.colLabel || th.textContent || ""));
  }

  function normalizePathForTableId() {
    const parts = String(window.location.pathname || "")
      .split("/")
      .map(p => p.trim())
      .filter(Boolean)
      .map((part) => {
        if (/^\d+$/.test(part) || /^[0-9a-f-]{24,}$/i.test(part)) return "id";
        return slugText(part, "page");
      });
    return (parts.join(".") || "home").slice(0, 46);
  }

  function tableContextName(table) {
    const scope = table.closest(
      "article, section, .hr-card, .ana-card, .dv-card, .wm-card, .mt-card, " +
      ".ms-card, .ac-card, .at-card, .abs-card, .tkt-card, .auto-card, .card"
    );
    const heading = scope && scope.querySelector(
      "h1, h2, h3, .hr-card-title, .ana-card-title, .dv-card-title, " +
      ".wm-card-title, .mt-card-title, .ms-card-title, .ac-card-title, .at-card-title, .tkt-card-title"
    );
    return heading ? slugText(heading.textContent, "") : "";
  }

  function generatedTableId(table, index) {
    const labels = headerLabels(table).filter(Boolean).slice(0, 6).join("|");
    const stableName = table.id ? slugText(table.id, "table") : (tableContextName(table) || "t" + String(index + 1));
    const id = "auto." + normalizePathForTableId() + "." + stableName + "." + shortHash(labels);
    return id.slice(0, 100);
  }

  function isOptedOut(table) {
    return !!(
      table.dataset.fmTableSkip === "1" ||
      table.dataset.tableEnhanced === "0" ||
      table.closest("[data-fm-table-skip='1'], [data-table-enhanced='0']")
    );
  }

  function hasComplexHeader(table) {
    const firstRow = table.tHead && table.tHead.rows[0];
    if (!firstRow) return true;
    return Array.from(firstRow.cells).some(th => th.colSpan > 1 || th.rowSpan > 1);
  }

  function isTechnicalTable(table) {
    const skipClasses = [
      "dp-retr-table", "dp-contr-table", "dp-ratei-table",
      "task-table-mini", "pdf-table", "rn-preview-table",
      "vrfc-matrix", "gantt-table", "summary-perm-table",
      "dash-pulsanti-table", "fm-mini-grid"
    ];
    if (skipClasses.some(cls => table.classList.contains(cls))) return true;
    return !!table.closest(
      ".dbs-page, .pdf-page, .print-only, .fm-th-filter-pop, .fm-tbl-menu, " +
      ".gantt-wrap, .gantt-board, .vrfc-matrix-wrap"
    );
  }

  function hasEnoughDataRows(table, colCount) {
    return bodyRows(table).filter(row => rowCellCount(row) >= Math.min(colCount, 2)).length >= 2;
  }

  function canAutoBind(table) {
    if (!table || table.tagName !== "TABLE") return false;
    if (isOptedOut(table) || isTechnicalTable(table)) return false;
    if (table.parentElement && table.parentElement.closest("table")) return false;
    if (!table.tHead || !table.tBodies || !table.tBodies[0]) return false;
    if (hasComplexHeader(table)) return false;

    const firstRow = table.tHead.rows[0];
    const colCount = firstRow ? firstRow.cells.length : 0;
    if (colCount < 2) return false;

    const labels = headerLabels(table).filter(Boolean);
    if (labels.length < 2) return false;
    return hasEnoughDataRows(table, colCount);
  }

  function isActionLabel(label) {
    return /^(azioni?|comandi|operazioni|opzioni|tools?|edit|modifica|elimina)$/i.test(cleanText(label));
  }

  function looksLikeActionColumn(table, idx, label) {
    if (!cleanText(label)) return true;
    if (isActionLabel(label)) return true;
    const rows = bodyRows(table).slice(0, 12);
    if (!rows.length) return false;
    let actionCells = 0;
    let filled = 0;
    rows.forEach((row) => {
      const cell = row.cells[idx];
      if (!cell) return;
      const text = cleanText(cell.textContent);
      if (!text && !cell.querySelector("a, button, input, select")) return;
      filled += 1;
      if (cell.querySelector("button, input, select, .btn") || (cell.querySelectorAll("a").length >= 1 && text.length <= 40)) {
        actionCells += 1;
      }
    });
    return filled > 0 && actionCells === filled && idx === (table.tHead.rows[0].cells.length - 1);
  }

  function valuesForColumn(table, idx) {
    const values = [];
    bodyRows(table).slice(0, 250).forEach((row) => {
      const cell = row.cells[idx];
      const value = cellPlainText(cell);
      if (value && value !== "-" && value !== "—") values.push(value);
    });
    return values;
  }

  function isDateLike(value) {
    const text = cleanText(value);
    return /^\d{4}-\d{2}-\d{2}/.test(text) || /^\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}/.test(text);
  }

  function isNumberLike(value) {
    const text = cleanText(value).replace(/\s/g, "").replace("%", "").replace("€", "").replace(",", ".");
    return /^-?\d+(\.\d+)?$/.test(text);
  }

  function isBoolLike(value) {
    return /^(si|sì|no|yes|true|false|0|1|ok|ko|✓|✔)$/i.test(cleanText(value));
  }

  function inferColumnType(label, values) {
    const sample = values.filter(Boolean).slice(0, 60);
    const labelSlug = slugText(label, "");
    if (!sample.length) return "text";
    if (/(data|scadenza|inizio|fine|aggiornato|creato|chiuso|aperto)/.test(labelSlug) && sample.some(isDateLike)) return "date";
    if (sample.length >= 2 && sample.every(isDateLike)) return "date";
    if (sample.length >= 2 && sample.every(isBoolLike)) return "bool";
    if (sample.length >= 2 && sample.every(isNumberLike)) return "number";
    if (/(nome|dipendente|ragione|descrizione|titolo|email|codice|matricola|asset|fornitore|utente|note|seriale|modello|telefono|piva|indirizzo)/.test(labelSlug)) {
      return "text";
    }

    const unique = Array.from(new Set(sample.map(cleanText))).filter(Boolean);
    const maxLen = unique.reduce((m, v) => Math.max(m, v.length), 0);
    if (unique.length > 1 && unique.length <= 12 && unique.length <= Math.max(4, Math.ceil(sample.length * 0.45)) && maxLen <= 42) {
      return "select";
    }
    return "text";
  }

  // Inferisce il tipo dalla sola etichetta, senza scansionare le celle.
  // Restituisce null se non è possibile determinarlo senza leggere i valori.
  function inferColumnTypeFromLabel(label) {
    const s = slugText(label, "");
    if (/(data|scadenza|inizio|fine|aggiornato|creato|chiuso|aperto)/.test(s)) return "date";
    if (/(nome|dipendente|ragione|descrizione|titolo|email|codice|matricola|asset|fornitore|utente|note|seriale|modello|telefono|piva|indirizzo)/.test(s)) return "text";
    return null;
  }

  function applyInferredColumns(table) {
    const firstRow = table.tHead && table.tHead.rows[0];
    if (!firstRow) return false;

    const usedKeys = {};
    Array.from(firstRow.cells).forEach((th, idx) => {
      const label = cleanText(th.dataset.colLabel || th.textContent || "");
      const actionColumn = looksLikeActionColumn(table, idx, label);

      if (!th.dataset.col && !label && actionColumn) {
        th.dataset.colLocked = "1";
        return;
      }

      let key = cleanText(th.dataset.col);
      if (!key) {
        const baseKey = slugText(label, "col_" + String(idx + 1));
        const seen = usedKeys[baseKey] || 0;
        usedKeys[baseKey] = seen + 1;
        key = seen ? baseKey + "_" + String(seen + 1) : baseKey;
        th.dataset.col = key;
      } else {
        usedKeys[key] = (usedKeys[key] || 0) + 1;
      }

      if (!th.dataset.colLabel) th.dataset.colLabel = label || key;
      if (actionColumn) {
        if (th.dataset.colSortable === undefined) th.dataset.colSortable = "0";
        if (th.dataset.colFilterable === undefined) th.dataset.colFilterable = "0";
        if (th.dataset.colLocked === undefined) th.dataset.colLocked = "1";
        return;
      }

      if (!th.dataset.colType) {
        // Fast path: se il label è sufficiente non scansionare le celle.
        const fastType = inferColumnTypeFromLabel(label);
        if (fastType) {
          th.dataset.colType = fastType;
        } else {
          const values = valuesForColumn(table, idx);
          th.dataset.colType = inferColumnType(label, values);
          if (th.dataset.colType === "select" && !th.dataset.colOptions) {
            const opts = Array.from(new Set(values.map(cleanText).filter(Boolean))).slice(0, 30)
              .sort((a, b) => a.localeCompare(b, "it", { sensitivity: "base", numeric: true }))
              .map(v => [v, v]);
            th.dataset.colOptions = JSON.stringify(opts);
          }
        }
      } else if (th.dataset.colType === "select" && !th.dataset.colOptions) {
        const values = valuesForColumn(table, idx);
        const opts = Array.from(new Set(values.map(cleanText).filter(Boolean))).slice(0, 30)
          .sort((a, b) => a.localeCompare(b, "it", { sensitivity: "base", numeric: true }))
          .map(v => [v, v]);
        th.dataset.colOptions = JSON.stringify(opts);
      }
      if (th.dataset.colSortable === undefined) th.dataset.colSortable = "1";
      if (th.dataset.colFilterable === undefined) th.dataset.colFilterable = "1";
    });
    return Array.from(firstRow.cells).some(th => !!th.dataset.col);
  }

  function prepareTable(table, index) {
    if (isOptedOut(table)) return false;
    const explicit = !!table.dataset.tableId;
    if (!explicit && !canAutoBind(table)) return false;
    if (!applyInferredColumns(table)) return false;
    if (!explicit) {
      table.dataset.tableId = generatedTableId(table, index || 0);
      table.dataset.fmTblAuto = "1";
      table.classList.add("fm-table-auto");
    }
    return true;
  }

  async function fetchPrefs(tableId) {
    try {
      const r = await fetch(API_BASE + encodeURIComponent(tableId) + "/", {
        credentials: "same-origin", headers: { "Accept": "application/json" },
      });
      if (!r.ok) return {};
      const data = await r.json();
      return (data && data.state) ? data.state : {};
    } catch (e) { return {}; }
  }

  // Per default le preferenze persistite sono solo "view config": colonne
  // visibili, ordine, sort. Filtri di colonna e ricerca globale sono invece
  // *transitori* (vivono nella sessione di pagina): ricaricando o tornando
  // sulla pagina la tabella non risulta più filtrata. Opt-in per tabella:
  //   <table data-fm-persist-filters="1">  → persiste anche filters
  //   <table data-fm-persist-search="1">   → persiste anche q (search)
  function buildPersistOpts(table) {
    return {
      persistFilters: table.dataset.fmPersistFilters === "1",
      persistSearch: table.dataset.fmPersistSearch === "1" || table.dataset.fmPersistFilters === "1",
    };
  }

  const _savePending = {};
  function schedulePrefsSave(tableId, state, statusEl, persistOpts) {
    persistOpts = persistOpts || {};
    if (_savePending[tableId]) clearTimeout(_savePending[tableId]);
    _savePending[tableId] = setTimeout(async () => {
      if (statusEl) { statusEl.textContent = "Salvataggio…"; statusEl.classList.add("fm-tbl-status-saving"); }
      const payload = {
        visible: state.visible,
        order:   state.order,
        sort:    state.sort,
        filters: persistOpts.persistFilters ? state.filters : {},
        q:       persistOpts.persistSearch  ? state.q       : "",
      };
      try {
        const r = await fetch(API_BASE + encodeURIComponent(tableId) + "/", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
          body: JSON.stringify({ state: payload }),
        });
        if (statusEl) {
          statusEl.classList.remove("fm-tbl-status-saving");
          statusEl.textContent = r.ok ? "✓ Preferenze salvate" : "⚠ Errore salvataggio";
          if (r.ok) setTimeout(() => { statusEl.textContent = ""; }, 1800);
        }
      } catch (e) {
        if (statusEl) statusEl.textContent = "⚠ Offline";
      }
    }, 600);
  }

  async function deletePrefs(tableId) {
    try {
      await fetch(API_BASE + encodeURIComponent(tableId) + "/", {
        method: "DELETE", credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken() },
      });
    } catch (e) { /* no-op */ }
  }

  // ─── Parsing colonne ──────────────────────────────────────────────────────

  function parseColumns(table) {
    const thead = table.tHead;
    if (!thead) return [];
    const firstRow = thead.rows[0];
    const cols = [];
    Array.from(firstRow.cells).forEach((th, idx) => {
      const key = th.dataset.col;
      if (!key) { cols.push({ idx, key: null, th, locked: true }); return; }
      let options = null;
      if (th.dataset.colOptions) {
        try { options = JSON.parse(th.dataset.colOptions); } catch (e) { options = null; }
      }
      cols.push({
        idx, key, th,
        label:      th.dataset.colLabel || th.textContent.trim(),
        type:       th.dataset.colType || "text",
        options:    options,
        sortable:   th.dataset.colSortable === "1",
        filterable: th.dataset.colFilterable === "1",
        locked:     th.dataset.colLocked === "1",
      });
    });
    return cols;
  }

  function defaultState(cols) {
    const named = cols.filter(c => c.key);
    return {
      visible: named.map(c => c.key),
      order:   named.map(c => c.key),
      sort:    [],          // [[key,"asc"|"desc"], …]
      filters: {},
      q:       "",
    };
  }

  function mergeState(defaults, saved) {
    if (!saved || typeof saved !== "object") return defaults;
    const out = JSON.parse(JSON.stringify(defaults));
    if (Array.isArray(saved.visible)) out.visible = saved.visible.filter(k => defaults.order.includes(k));
    if (Array.isArray(saved.order)) {
      const known = new Set(defaults.order);
      const merged = saved.order.filter(k => known.has(k));
      defaults.order.forEach(k => { if (!merged.includes(k)) merged.push(k); });
      out.order = merged;
    }
    if (Array.isArray(saved.sort)) out.sort = saved.sort.filter(s => Array.isArray(s) && s.length === 2);
    if (saved.filters && typeof saved.filters === "object") out.filters = saved.filters;
    if (typeof saved.q === "string") out.q = saved.q;
    return out;
  }

  // ─── Barra controlli sopra la tabella ────────────────────────────────────

  function buildControlsBar(table, cols, state, onChange, statusEl) {
    const bar = document.createElement("div");
    bar.className = "fm-tbl-controls";

    // Search globale
    const searchWrap = document.createElement("div");
    searchWrap.className = "fm-tbl-search";
    searchWrap.innerHTML = '<span class="fm-tbl-search-ico">🔍</span>';
    const search = document.createElement("input");
    search.type = "search";
    search.placeholder = "Cerca…";
    search.value = state.q || "";
    search.addEventListener("input", () => { state.q = search.value; onChange(); });
    searchWrap.appendChild(search);
    bar.appendChild(searchWrap);

    // Pulsante Colonne ▾
    const colsBtn = document.createElement("button");
    colsBtn.type = "button";
    colsBtn.className = "fm-tbl-btn";
    colsBtn.innerHTML = "Colonne ▾";
    const colsMenu = buildColumnsMenu(cols, state, onChange);
    colsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      colsMenu.classList.toggle("fm-tbl-menu-open");
    });
    document.addEventListener("click", (e) => {
      if (!colsMenu.contains(e.target) && e.target !== colsBtn) {
        colsMenu.classList.remove("fm-tbl-menu-open");
      }
    });
    const colsWrap = document.createElement("div");
    colsWrap.className = "fm-tbl-menu-wrap";
    colsWrap.appendChild(colsBtn);
    colsWrap.appendChild(colsMenu);
    bar.appendChild(colsWrap);

    // Reset
    const resetBtn = document.createElement("button");
    resetBtn.type = "button";
    resetBtn.className = "fm-tbl-btn fm-tbl-btn-ghost";
    resetBtn.textContent = "Reset";
    resetBtn.addEventListener("click", async () => {
      if (!confirm("Ripristinare le preferenze di default per questa tabella?")) return;
      const tableId = table.dataset.tableId;
      await deletePrefs(tableId);
      location.reload();
    });
    bar.appendChild(resetBtn);

    if (statusEl) bar.appendChild(statusEl);
    return bar;
  }

  function buildColumnsMenu(cols, state, onChange) {
    const menu = document.createElement("div");
    menu.className = "fm-tbl-menu";

    const named = cols.filter(c => c.key);
    const ordered = state.order.map(k => named.find(c => c.key === k)).filter(Boolean);

    const ul = document.createElement("ul");
    ul.className = "fm-tbl-col-list";

    ordered.forEach((col) => {
      const li = document.createElement("li");
      li.draggable = true;
      li.dataset.colKey = col.key;
      li.className = "fm-tbl-col-item";

      const handle = document.createElement("span");
      handle.className = "fm-tbl-col-handle";
      handle.textContent = "⋮⋮";
      li.appendChild(handle);

      const lbl = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = state.visible.includes(col.key);
      cb.disabled = !!col.locked;
      cb.addEventListener("change", () => {
        if (cb.checked) {
          if (!state.visible.includes(col.key)) state.visible.push(col.key);
        } else {
          state.visible = state.visible.filter(k => k !== col.key);
        }
        onChange();
      });
      lbl.appendChild(cb);
      const span = document.createElement("span");
      span.textContent = " " + col.label;
      lbl.appendChild(span);
      li.appendChild(lbl);
      ul.appendChild(li);
    });

    // Drag-reorder
    let dragKey = null;
    ul.addEventListener("dragstart", (e) => {
      const li = e.target.closest(".fm-tbl-col-item");
      if (!li) return;
      dragKey = li.dataset.colKey;
      li.classList.add("fm-tbl-col-dragging");
    });
    ul.addEventListener("dragend", () => {
      ul.querySelectorAll(".fm-tbl-col-dragging").forEach(el => el.classList.remove("fm-tbl-col-dragging"));
    });
    ul.addEventListener("dragover", (e) => {
      e.preventDefault();
      const li = e.target.closest(".fm-tbl-col-item");
      if (!li || li.dataset.colKey === dragKey) return;
      const rect = li.getBoundingClientRect();
      const after = (e.clientY - rect.top) > rect.height / 2;
      const draggingEl = ul.querySelector(".fm-tbl-col-dragging");
      if (!draggingEl) return;
      if (after) li.parentNode.insertBefore(draggingEl, li.nextSibling);
      else li.parentNode.insertBefore(draggingEl, li);
    });
    ul.addEventListener("drop", (e) => {
      e.preventDefault();
      state.order = Array.from(ul.children).map(li => li.dataset.colKey);
      dragKey = null;
      onChange();
    });

    menu.appendChild(ul);
    return menu;
  }

  // ─── Decorazione header con sort + filter icone ──────────────────────────

  function decorateHeader(col, state, onChange) {
    if (!col.key) return;
    const th = col.th;
    th.classList.add("fm-th");

    // Salva il label originale e ricostruisci con wrapper
    const labelHTML = th.innerHTML.trim();
    th.innerHTML = "";

    const wrap = document.createElement("div");
    wrap.className = "fm-th-wrap";

    const lbl = document.createElement("span");
    lbl.className = "fm-th-label";
    lbl.innerHTML = labelHTML;
    wrap.appendChild(lbl);

    // Sort icon
    if (col.sortable) {
      const sortBtn = document.createElement("button");
      sortBtn.type = "button";
      sortBtn.className = "fm-th-sort";
      sortBtn.title = "Ordina (Shift+click per multi-sort)";
      const entry = state.sort.find(s => s[0] === col.key);
      sortBtn.textContent = entry ? SORT_ICON[entry[1]] : SORT_ICON.none;
      if (entry) sortBtn.classList.add("active");
      sortBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const idx = state.sort.findIndex(s => s[0] === col.key);
        const cur = idx >= 0 ? state.sort[idx][1] : null;
        const next = cur === "asc" ? "desc" : (cur === "desc" ? null : "asc");
        if (!e.shiftKey) state.sort = state.sort.filter(s => s[0] === col.key);
        if (idx >= 0) state.sort = state.sort.filter(s => s[0] !== col.key);
        if (next) state.sort.push([col.key, next]);
        onChange();
      });
      wrap.appendChild(sortBtn);
    }

    // Filter funnel icon + popover
    if (col.filterable) {
      const isActive = !!state.filters[col.key];
      const filterBtn = document.createElement("button");
      filterBtn.type = "button";
      filterBtn.className = "fm-th-filter";
      filterBtn.title = "Filtra";
      filterBtn.innerHTML = isActive ? FUNNEL_SVG_ACTIVE : FUNNEL_SVG;
      if (isActive) filterBtn.classList.add("active");

      const pop = document.createElement("div");
      pop.className = "fm-th-filter-pop";

      const popInner = document.createElement("div");
      popInner.className = "fm-th-filter-pop-inner";

      // Header con etichetta colonna + chiudi
      const popTitle = document.createElement("div");
      popTitle.className = "fm-th-filter-pop-title";
      const titleLabel = document.createElement("span");
      titleLabel.textContent = "Filtra: " + (col.label || col.key);
      const popCloseBtn = document.createElement("button");
      popCloseBtn.type = "button";
      popCloseBtn.className = "fm-th-filter-pop-close";
      popCloseBtn.innerHTML = "✕";
      popCloseBtn.title = "Chiudi";
      popCloseBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        pop.classList.remove("fm-th-filter-pop-open");
      });
      popTitle.appendChild(titleLabel);
      popTitle.appendChild(popCloseBtn);
      popInner.appendChild(popTitle);

      let input;
      let datalist = null;
      if (col.type === "select") {
        input = document.createElement("select");
        const optEmpty = document.createElement("option");
        optEmpty.value = ""; optEmpty.textContent = "— tutti —";
        input.appendChild(optEmpty);
        (col.options || []).forEach(opt => {
          const o = document.createElement("option");
          o.value = opt[0]; o.textContent = opt[1] || opt[0];
          input.appendChild(o);
        });
        input.value = state.filters[col.key] || "";
      } else if (col.type === "bool") {
        input = document.createElement("select");
        [["", "— tutti —"], ["1", "Sì"], ["0", "No"]].forEach(opt => {
          const o = document.createElement("option");
          o.value = opt[0]; o.textContent = opt[1];
          input.appendChild(o);
        });
        input.value = state.filters[col.key] || "";
      } else {
        input = document.createElement("input");
        input.type = col.type === "number" ? "number" : (col.type === "date" ? "date" : "search");
        input.placeholder = col.type === "number" ? "≥ valore" : (col.type === "date" ? "gg/mm/aaaa" : "contiene…");
        input.value = state.filters[col.key] || "";
        input.setAttribute("autocomplete", "off");
        // Datalist con suggerimenti unici della colonna (autocomplete nativo browser).
        // Popolato in modo lazy al primo click sul filtro per non scansionare
        // le celle al caricamento della pagina.
        if (col.type === "text") {
          const tableIdSlug = slugText(col.th.closest("table").dataset.tableId || "tbl", "tbl");
          const dlId = "fm-dl-" + tableIdSlug + "-" + slugText(col.key, "c") + "-" + shortHash(tableIdSlug + col.key);
          datalist = document.createElement("datalist");
          datalist.id = dlId;
          input.setAttribute("list", dlId);
        }
      }
      input.className = "fm-th-filter-input";

      function commitInput() {
        if (input.value) state.filters[col.key] = input.value;
        else delete state.filters[col.key];
        // Aggiorna icona
        const nowActive = !!state.filters[col.key];
        filterBtn.classList.toggle("active", nowActive);
        filterBtn.innerHTML = nowActive ? FUNNEL_SVG_ACTIVE : FUNNEL_SVG;
        onChange();
      }
      input.addEventListener("input", commitInput);
      input.addEventListener("change", commitInput);
      input.addEventListener("click", (e) => e.stopPropagation());

      popInner.appendChild(input);
      if (datalist) popInner.appendChild(datalist);

      // Riga azioni (Pulisci)
      const actionsRow = document.createElement("div");
      actionsRow.className = "fm-th-filter-actions";
      const clearBtn = document.createElement("button");
      clearBtn.type = "button";
      clearBtn.className = "fm-th-filter-clear";
      clearBtn.textContent = "Pulisci";
      clearBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        input.value = "";
        commitInput();
        pop.classList.remove("fm-th-filter-pop-open");
      });
      actionsRow.appendChild(clearBtn);
      popInner.appendChild(actionsRow);

      pop.appendChild(popInner);

      // Riferimenti utili per refresh dopo full-load (il pop migra in body)
      col._fmPop = pop;
      col._fmInput = input;
      col._fmDatalist = datalist;
      col._fmFilterBtn = filterBtn;

      let _dlPopulated = false;
      filterBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        // Chiudi tutti gli altri popover
        document.querySelectorAll(".fm-th-filter-pop-open").forEach(el => {
          if (el !== pop) el.classList.remove("fm-th-filter-pop-open");
        });
        const willOpen = !pop.classList.contains("fm-th-filter-pop-open");
        pop.classList.toggle("fm-th-filter-pop-open");
        if (willOpen) {
          // Popola il datalist testo in modo lazy al primo click (evita scan DOM al load)
          if (datalist && !_dlPopulated) {
            rebuildDatalistOptions(datalist, valuesForColumn(col.th.closest("table"), col.idx));
            _dlPopulated = true;
          }
          positionFilterPopover(pop, filterBtn);
          setTimeout(() => { try { input.focus(); if (input.select) input.select(); } catch (_) {} }, 0);
        }
      });
      document.addEventListener("click", (e) => {
        if (!pop.contains(e.target) && e.target !== filterBtn && !filterBtn.contains(e.target)) {
          pop.classList.remove("fm-th-filter-pop-open");
        }
      });

      wrap.appendChild(filterBtn);
      // pop resta inizialmente nel th; alla prima apertura migra in body per
      // sfuggire ai contenitori con overflow:hidden / overflow-x:auto
      wrap.appendChild(pop);
    }

    th.appendChild(wrap);
  }

  // Riempie un <datalist> con i valori distinti di una colonna (max 60).
  function rebuildDatalistOptions(datalist, values) {
    const unique = Array.from(new Set(values.map(cleanText).filter(Boolean)))
      .sort((a, b) => a.localeCompare(b, "it", { sensitivity: "base", numeric: true }))
      .slice(0, 60);
    while (datalist.firstChild) datalist.removeChild(datalist.firstChild);
    unique.forEach((v) => {
      const o = document.createElement("option");
      o.value = v;
      datalist.appendChild(o);
    });
  }

  // Sposta il popover in <body> e lo posiziona via position:fixed rispetto al
  // funnel, in modo da non essere clippato da overflow:hidden / overflow-x:auto
  // dei contenitori della tabella (es. .table-responsive, hr-card, ecc.).
  function positionFilterPopover(pop, anchor) {
    if (pop.parentNode !== document.body) {
      document.body.appendChild(pop);
    }
    pop.style.position = "fixed";
    pop.style.right = "auto";
    pop.style.left = "0px";
    pop.style.top = "0px";
    pop.style.zIndex = "9999";
    // Forza layout per leggere la larghezza reale
    const popWidth = pop.offsetWidth || 240;
    const popHeight = pop.offsetHeight || 80;
    const rect = anchor.getBoundingClientRect();
    let top = rect.bottom + 4;
    if (top + popHeight > window.innerHeight - 8) {
      top = Math.max(8, rect.top - popHeight - 4);
    }
    let left = rect.right - popWidth;
    if (left < 8) left = 8;
    const maxLeft = window.innerWidth - popWidth - 8;
    if (left > maxLeft) left = maxLeft;
    pop.style.top = top + "px";
    pop.style.left = left + "px";
  }

  // Chiudi tutti i popover su resize/scroll della pagina (le coordinate fixed
  // si disallineano dall'anchor). Listener installato una sola volta.
  if (!window._fmTblPopGlobalCloseInstalled) {
    window._fmTblPopGlobalCloseInstalled = true;
    const closeAllPops = () => {
      document.querySelectorAll(".fm-th-filter-pop-open").forEach((p) => p.classList.remove("fm-th-filter-pop-open"));
    };
    window.addEventListener("resize", closeAllPops, { passive: true });
    window.addEventListener("scroll", closeAllPops, { passive: true, capture: true });
  }

  function updateSortIndicators(cols, state) {
    cols.forEach((col) => {
      if (!col.key || !col.sortable) return;
      const sortBtn = col.th.querySelector(".fm-th-sort");
      if (!sortBtn) return;
      const entry = state.sort.find(s => s[0] === col.key);
      sortBtn.textContent = entry ? SORT_ICON[entry[1]] : SORT_ICON.none;
      sortBtn.classList.toggle("active", !!entry);
    });
  }

  // ─── Applicazione stato (visibility / filter / sort) ─────────────────────

  function getCellText(row, idx) {
    return cellPlainText(row.cells[idx]);
  }

  function parseDateComparable(value) {
    const text = cleanText(value);
    if (!text) return 0;
    const iso = text.match(/(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?/);
    if (iso) {
      return new Date(
        Number(iso[1]),
        Number(iso[2]) - 1,
        Number(iso[3]),
        Number(iso[4] || 0),
        Number(iso[5] || 0)
      ).getTime();
    }
    const dmy = text.match(/(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/);
    if (dmy) {
      const year = Number(dmy[3].length === 2 ? "20" + dmy[3] : dmy[3]);
      return new Date(
        year,
        Number(dmy[2]) - 1,
        Number(dmy[1]),
        Number(dmy[4] || 0),
        Number(dmy[5] || 0)
      ).getTime();
    }
    const parsed = Date.parse(text);
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  function rowMatchesFilters(row, cols, state) {
    if (state.q && state.q.trim()) {
      const ql = state.q.toLowerCase();
      if (!row.textContent.toLowerCase().includes(ql)) return false;
    }
    for (const key in state.filters) {
      const val = state.filters[key];
      if (val === "" || val == null) continue;
      const col = cols.find(c => c.key === key);
      if (!col) continue;
      const cellTxt = getCellText(row, col.idx);
      const cell = row.cells[col.idx];
      if (col.type === "select") {
        const cv = (cell && cell.dataset.value) || cellTxt;
        if (cv !== val && cellTxt !== val) return false;
      } else if (col.type === "bool") {
        const truthy = ["sì","si","yes","1","true","✓","✔"].includes(cellTxt.toLowerCase());
        if (String(val) === "1" && !truthy) return false;
        if (String(val) === "0" && truthy) return false;
      } else if (col.type === "number") {
        const n = parseFloat(cellTxt.replace(",", "."));
        const target = parseFloat(String(val).replace(",", "."));
        if (isNaN(n) || isNaN(target)) return false;
        if (n < target) return false;
      } else if (col.type === "date") {
        // match parziale: confronta sia gg/mm/aaaa sia aaaa-mm-gg
        const isoVal = val;                  // yyyy-mm-dd
        const dmyVal = val.split("-").reverse().join("/");  // dd/mm/yyyy
        if (cellTxt.indexOf(dmyVal) === -1 && cellTxt.indexOf(isoVal) === -1) return false;
      } else {
        if (cellTxt.toLowerCase().indexOf(String(val).toLowerCase()) === -1) return false;
      }
    }
    return true;
  }

  function compareRows(rowA, rowB, cols, state) {
    for (const [key, dir] of state.sort) {
      const col = cols.find(c => c.key === key);
      if (!col) continue;
      let a = getCellText(rowA, col.idx);
      let b = getCellText(rowB, col.idx);
      const cellA = rowA.cells[col.idx];
      const cellB = rowB.cells[col.idx];
      if (cellA && cellA.dataset.sortValue !== undefined) a = cellA.dataset.sortValue;
      if (cellB && cellB.dataset.sortValue !== undefined) b = cellB.dataset.sortValue;
      let cmp;
      if (col.type === "number") {
        cmp = (parseFloat(a.replace(",", ".")) || 0) - (parseFloat(b.replace(",", ".")) || 0);
      } else if (col.type === "date") {
        cmp = parseDateComparable(a) - parseDateComparable(b);
      } else {
        cmp = a.localeCompare(b, "it", { sensitivity: "base", numeric: true });
      }
      if (cmp !== 0) return dir === "desc" ? -cmp : cmp;
    }
    return 0;
  }

  function applyState(table, cols, state) {
    // Visibilità colonne
    const visible = new Set(state.visible);
    cols.forEach((col) => {
      if (!col.key) return;
      const hide = !visible.has(col.key) && !col.locked;
      col.th.style.display = hide ? "none" : "";
      $$("tr", table.tBodies[0]).forEach(tr => {
        const cell = tr.cells[col.idx];
        if (cell) cell.style.display = hide ? "none" : "";
      });
    });

    // Filtra
    const rows = $$("tr", table.tBodies[0]);
    rows.forEach(tr => {
      tr.style.display = rowMatchesFilters(tr, cols, state) ? "" : "none";
    });

    // Sort
    if (state.sort.length) {
      const visibleRows = rows.filter(r => r.style.display !== "none");
      visibleRows.sort((a, b) => compareRows(a, b, cols, state));
      const tbody = table.tBodies[0];
      const frag = document.createDocumentFragment();
      visibleRows.forEach(r => frag.appendChild(r));
      tbody.appendChild(frag);
    }

    updateSortIndicators(cols, state);

    // Conta
    const countEl = table._fmTblCountEl || (table.parentNode.parentNode && table.parentNode.parentNode.querySelector(".fm-tbl-count"));
    if (countEl) {
      const tot = rows.length;
      const shown = rows.filter(r => r.style.display !== "none").length;
      countEl.textContent = shown < tot ? `${shown} / ${tot}` : `${tot}`;
    }
  }

  // ─── Caricamento completo dataset (server pagination) ────────────────────
  //
  // I filtri/sort/search del componente sono client-side: di default lavorano
  // solo sulle righe presenti nel <tbody> della pagina visibile. Quando la
  // view usa Paginator (Django), questo limita il filtro al subset corrente.
  //
  // Per garantire che il filtro agisca su tutto il dataset:
  //   - rileviamo automaticamente la paginazione cercando link `?page=N`
  //     vicini alla tabella;
  //   - alla prima azione utente con filtro/sort/search attivo, in background
  //     scarichiamo via fetch() tutte le altre pagine, estraiamo i <tr> della
  //     tabella corrispondente e li uniamo al <tbody> corrente;
  //   - durante il caricamento il filtro corrente continua ad applicarsi sui
  //     dati già presenti (UX reattiva), e al termine viene riapplicato sul
  //     dataset completo;
  //   - la paginazione nativa viene nascosta perché non più significativa;
  //   - cap di sicurezza FM_MAX_MERGED_ROWS per evitare di saturare il
  //     browser su dataset enormi. Opt-out per tabella: data-fm-fullload="0".
  //
  // Limiti accettati:
  //   - le righe clonate dalle pagine remote non avranno event listener
  //     attaccati via JS al di fuori del componente (gli handler inline
  //     `onclick`/`href` e quelli delegati continuano a funzionare).
  //   - le option dei filtri select vengono rigenerate dopo il merge per
  //     riflettere i nuovi valori distinti del dataset completo.

  const FM_MAX_MERGED_ROWS = 5000;
  const _fmLoadAllInflight = new WeakMap();
  const _fmLoadAllDone = new WeakSet();

  function tablePageScope(table) {
    return table.closest(
      "article, section, .hr-card, .ana-card, .dv-card, .wm-card, .mt-card, " +
      ".ms-card, .ac-card, .at-card, .abs-card, .tkt-card, .auto-card, .card, main"
    ) || document.body;
  }

  function detectPagination(table) {
    const scope = tablePageScope(table);
    const urls = new Map();
    let lastPage = 1;
    $$('a[href*="page="]', scope).forEach((a) => {
      try {
        const u = new URL(a.href, window.location.href);
        const p = parseInt(u.searchParams.get("page"), 10);
        if (Number.isFinite(p) && p >= 1) {
          urls.set(p, u.toString());
          if (p > lastPage) lastPage = p;
        }
      } catch (e) { /* ignore malformed href */ }
    });
    let currentPage = 1;
    try {
      const cur = parseInt(new URL(window.location.href).searchParams.get("page") || "1", 10);
      if (Number.isFinite(cur) && cur >= 1) currentPage = cur;
    } catch (e) { /* ignore */ }
    // Fallback: parse "Pagina N / M" o "Pagina N di M" presente nei template
    const m = (scope.textContent || "").match(/Pagina\s+(\d+)\s*(?:\/|di)\s*(\d+)/i);
    if (m) {
      const n = parseInt(m[1], 10);
      const tot = parseInt(m[2], 10);
      if (Number.isFinite(n)) currentPage = n;
      if (Number.isFinite(tot) && tot > lastPage) lastPage = tot;
    }
    if (lastPage <= 1) return null;
    return { currentPage, lastPage, urls };
  }

  function tableSignature(table) {
    if (table.id) return "id:" + table.id;
    // Considera data-table-id solo se proveniente dal template (non auto-generato lato JS)
    if (table.dataset.tableId && table.dataset.fmTblAuto !== "1") return "tid:" + table.dataset.tableId;
    const labels = headerLabels(table).join("|");
    const cls = Array.from(table.classList).sort().join(".");
    return "hdr:" + cls + ":" + labels;
  }

  function tableSignatureForFetched(t) {
    if (t.id) return "id:" + t.id;
    if (t.hasAttribute("data-table-id")) return "tid:" + t.getAttribute("data-table-id");
    const head = t.tHead && t.tHead.rows[0];
    const labels = head
      ? Array.from(head.cells).map((c) => cleanText(c.dataset.colLabel || c.textContent || "")).join("|")
      : "";
    const cls = Array.from(t.classList).sort().join(".");
    return "hdr:" + cls + ":" + labels;
  }

  function findMatchingTableInDoc(doc, sig, fallbackIndex) {
    const tables = Array.from(doc.querySelectorAll("table"));
    for (const t of tables) {
      if (tableSignatureForFetched(t) === sig) return t;
    }
    if (typeof fallbackIndex === "number" && tables[fallbackIndex]) return tables[fallbackIndex];
    return null;
  }

  function refreshSelectFilterOptions(table, cols) {
    cols.forEach((col) => {
      if (!col.key || col.type !== "select") return;
      const values = valuesForColumn(table, col.idx);
      const opts = Array.from(new Set(values.map(cleanText).filter(Boolean))).slice(0, 60)
        .sort((a, b) => a.localeCompare(b, "it", { sensitivity: "base", numeric: true }))
        .map((v) => [v, v]);
      col.options = opts;
      col.th.dataset.colOptions = JSON.stringify(opts);
      // Il select del filtro è memorizzato su col._fmInput (il popover può
      // essere stato migrato in body, quindi querySelector sul th non basta).
      const sel = col._fmInput || col.th.querySelector("select.fm-th-filter-input");
      if (!sel || sel.tagName !== "SELECT") return;
      const current = sel.value;
      while (sel.firstChild) sel.removeChild(sel.firstChild);
      const optEmpty = document.createElement("option");
      optEmpty.value = ""; optEmpty.textContent = "— tutti —";
      sel.appendChild(optEmpty);
      opts.forEach((opt) => {
        const o = document.createElement("option");
        o.value = opt[0]; o.textContent = opt[1] || opt[0];
        sel.appendChild(o);
      });
      sel.value = current;
    });
  }

  // Rigenera i suggerimenti <datalist> dei filtri text usando il dataset
  // corrente (post merge full-load).
  function refreshTextFilterDatalists(table, cols) {
    cols.forEach((col) => {
      if (!col.key || col.type !== "text") return;
      const dl = col._fmDatalist;
      if (!dl) return;
      rebuildDatalistOptions(dl, valuesForColumn(table, col.idx));
    });
  }

  function hideServerPaginationBlock(table) {
    $$(".hr-pag, .ana-pag, .pagination, .paginator, .pag, .pagin", tablePageScope(table)).forEach((el) => {
      if (el.getAttribute("data-fm-hidden") === "1") return;
      el.style.display = "none";
      el.setAttribute("data-fm-hidden", "1");
    });
  }

  function hasActiveQuery(state) {
    if (state.q && String(state.q).trim()) return true;
    if (state.sort && state.sort.length > 0) return true;
    if (state.filters) {
      for (const k in state.filters) {
        const v = state.filters[k];
        if (v != null && v !== "") return true;
      }
    }
    return false;
  }

  async function ensureFullDataset(table, statusEl, cols, onLoaded) {
    if (table.dataset.fmFullload === "0" || table.dataset.fmTblPaginationSkip === "1") return;
    if (_fmLoadAllDone.has(table)) return;
    if (_fmLoadAllInflight.has(table)) return _fmLoadAllInflight.get(table);

    const pag = detectPagination(table);
    if (!pag) { _fmLoadAllDone.add(table); return; }

    const promise = (async () => {
      const sig = tableSignature(table);
      const allTables = Array.from(document.querySelectorAll("table"));
      const tableIndex = allTables.indexOf(table);
      const tbody = table.tBodies[0];

      const toFetch = [];
      for (let p = 1; p <= pag.lastPage; p += 1) {
        if (p === pag.currentPage) continue;
        const u = pag.urls.get(p) || (function () {
          const url = new URL(window.location.href);
          url.searchParams.set("page", String(p));
          return url.toString();
        })();
        toFetch.push({ page: p, url: u });
      }
      toFetch.sort((a, b) => a.page - b.page);

      let totalRows = bodyRows(table).length;
      const totalPages = toFetch.length;
      let processedPages = 0;

      if (statusEl) {
        statusEl.classList.add("fm-tbl-status-saving");
        statusEl.textContent = "Carico dataset completo… 0/" + totalPages;
      }

      for (const item of toFetch) {
        if (totalRows >= FM_MAX_MERGED_ROWS) {
          if (statusEl) statusEl.textContent = "⚠ Limite " + FM_MAX_MERGED_ROWS + " righe raggiunto";
          break;
        }
        try {
          const r = await fetch(item.url, {
            credentials: "same-origin",
            headers: { "Accept": "text/html, */*" },
          });
          if (r.ok) {
            const html = await r.text();
            const doc = new DOMParser().parseFromString(html, "text/html");
            const matched = findMatchingTableInDoc(doc, sig, tableIndex);
            if (matched && matched.tBodies[0]) {
              const remoteRows = Array.from(matched.tBodies[0].querySelectorAll(":scope > tr"));
              const frag = document.createDocumentFragment();
              for (const row of remoteRows) {
                if (totalRows >= FM_MAX_MERGED_ROWS) break;
                const cloned = document.importNode(row, true);
                cloned.dataset.fmExtra = "1";
                frag.appendChild(cloned);
                totalRows += 1;
              }
              tbody.appendChild(frag);
            }
          }
        } catch (e) { /* skip page on network/parse error */ }
        processedPages += 1;
        if (statusEl) statusEl.textContent = "Carico dataset completo… " + processedPages + "/" + totalPages;
      }

      _fmLoadAllDone.add(table);
      hideServerPaginationBlock(table);
      refreshSelectFilterOptions(table, cols);
      refreshTextFilterDatalists(table, cols);

      if (statusEl) {
        statusEl.classList.remove("fm-tbl-status-saving");
        statusEl.textContent = "✓ Dataset completo (" + totalRows + " righe)";
        setTimeout(() => {
          if (statusEl.textContent && statusEl.textContent.indexOf("Dataset completo") >= 0) {
            statusEl.textContent = "";
          }
        }, 2200);
      }
      if (typeof onLoaded === "function") onLoaded();
    })();

    _fmLoadAllInflight.set(table, promise);
    try { await promise; }
    finally { _fmLoadAllInflight.delete(table); }
  }

  // ─── Init di una tabella ─────────────────────────────────────────────────

  function tableControlAnchor(table) {
    return table.closest(
      ".fm-table-wrap, .hr-table-wrap, .ana-table-wrap, .dv-table-wrap, .wm-table-wrap, " +
      ".mt-table-wrap, .ms-table-wrap, .ac-table-wrap, .at-table-wrap, .abs-table-wrap, " +
      ".tkt-table-wrap, .auto-table-wrap, .tp-table-wrap, .table-responsive, .table-wrap"
    ) || table.parentNode;
  }

  async function initTable(table, opts) {
    opts = opts || {};
    if (table.dataset.fmTblInited === "1") return;
    if (!prepareTable(table, opts.index || 0)) return;
    const tableId = table.dataset.tableId;
    if (!tableId) return;

    const cols = parseColumns(table);
    if (!cols.some(c => c.key)) return;
    table.dataset.fmTblInited = "1";

    const defaults = defaultState(cols);
    const saved = await fetchPrefs(tableId);
    const persistOpts = buildPersistOpts(table);
    // I filtri/ricerca sono per default transitori: scartiamo dallo stato
    // salvato qualsiasi residuo (anche entry storiche da quando la persistenza
    // era totale) così la tabella si apre sempre pulita.
    if (!persistOpts.persistFilters) saved.filters = {};
    if (!persistOpts.persistSearch)  saved.q = "";
    const state = mergeState(defaults, saved);

    const statusEl = document.createElement("span");
    statusEl.className = "fm-tbl-status";

    // Trigger non-bloccante: applica subito il filtro sui dati visibili e, se
    // c'è una query attiva e la tabella è paginata server-side, in background
    // scarica le altre pagine; al termine riapplica lo stato sul dataset
    // completo. ensureFullDataset() è idempotente per tabella.
    const maybeLoadAll = () => {
      if (!hasActiveQuery(state)) return;
      if (_fmLoadAllDone.has(table)) return;
      ensureFullDataset(table, statusEl, cols, () => applyState(table, cols, state));
    };

    const onChange = () => {
      applyState(table, cols, state);
      schedulePrefsSave(tableId, state, statusEl, persistOpts);
      maybeLoadAll();
    };

    // Decorazione header (sort + filter icone per ogni th[data-col])
    cols.forEach(col => decorateHeader(col, state, onChange));

    // Barra controlli sopra il wrap
    const wrap = tableControlAnchor(table);
    const bar = buildControlsBar(table, cols, state, onChange, statusEl);
    wrap.parentNode.insertBefore(bar, wrap);

    // Contatore
    const countSpan = document.createElement("span");
    countSpan.className = "fm-tbl-count";
    countSpan.textContent = String($$("tr", table.tBodies[0]).length);
    table._fmTblCountEl = countSpan;
    bar.appendChild(countSpan);

    // Applica stato iniziale e, se le preferenze salvate hanno già una query
    // attiva (filtro/sort/search), carica subito tutto il dataset così che il
    // primo render rifletta la filtro su tutti i record e non solo sulla pagina.
    applyState(table, cols, state);
    maybeLoadAll();
  }

  // ─── Auto-bind ────────────────────────────────────────────────────────────

  function initAll() {
    $$("table").forEach((table, index) => initTable(table, { index: index }));
  }

  function watchDynamicTables() {
    if (!window.MutationObserver || !document.body) return;
    let timer = null;
    const observer = new MutationObserver((mutations) => {
      const hasTable = mutations.some((mutation) => {
        return Array.from(mutation.addedNodes || []).some((node) => {
          if (!node || node.nodeType !== 1) return false;
          return (node.matches && node.matches("table")) || (node.querySelector && node.querySelector("table"));
        });
      });
      if (!hasTable) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(initAll, 120);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      initAll();
      watchDynamicTables();
    });
  } else {
    initAll();
    watchDynamicTables();
  }
  window.fmTableEnhanced = { init: initTable, initAll: initAll };
})();
