/**
 * fm-table-enhanced.js — sistema tabelle personalizzabili portale Novicrom HUB.
 *
 * Auto-bind su `<table data-table-id="…">` e sulle tabelle dati rilevate automaticamente.
 * Aggiunge per colonna:
 *   - icona sort ↕ / ▲ / ▼  (multi-sort con Shift+click)
 *   - icona filtro (imbuto stile Excel) — click apre popover con input filtro
 *
 * Sopra la tabella appare una barra controlli con:
 *   - ricerca globale (opt-out per tabella con data-fm-hide-search="1", utile
 *     quando la pagina ha già una ricerca rapida dedicata sopra la tabella)
 *   - menu "Colonne ▾" (toggle visibilità + drag-reorder)
 *   - bottone Reset
 *   - status salvataggio
 *   - contatore risultati
 *
 * L'intera barra controlli può essere nascosta (mantenendo le icone di
 * ordina/filtro per colonna negli header) con data-fm-hide-controls="1" sul
 * <table> o su un suo antenato (es. <body data-fm-hide-controls="1"> per
 * applicarlo a tutte le tabelle di un modulo).
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
 * Colonne ridimensionabili: maniglia sul bordo destro di ogni intestazione
 * (trascina; doppio clic = adatta al contenuto; frecce ←/→ da tastiera). Le
 * larghezze finiscono nelle preferenze utente (`widths`) come colonne e sort.
 *
 * Area tabella: la tabella sta in un contenitore `.fm-tbl-viewport` con
 * intestazione fissa; quando è più alta dello schermo il contenitore scorre
 * da sé (altezza = schermo). Pulsante «Schermo intero» nella barra controlli.
 * Opt-out per tabella: `data-fm-viewport="0"`.
 *
 * Caricamento passo passo: oltre ~150 righe se ne disegnano 100 alla volta,
 * le successive arrivano scorrendo (o con «Mostra altre»); le tabelle
 * paginate dal server caricano la pagina successiva allo stesso modo. Con un
 * filtro/ricerca/ordinamento attivo si carica comunque tutto il dataset.
 * Blocco iniziale personalizzabile con `data-fm-row-cap="N"`; opt-out con
 * `data-fm-progressive="0"`.
 *
 * Intestazioni su più righe (gruppi con colspan/rowspan): ordinamento e
 * filtro stanno sulla riga più bassa; i gruppi si stringono quando si
 * nascondono le loro colonne.
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
 *
 * API programmatica (window.fmTableEnhanced):
 *   setColumnFilter(tableOrId, colKey, value)  filtro di colonna dall'esterno
 *   setSearch(tableOrId, q)                    ricerca globale dall'esterno —
 *     usata dalle pagine che hanno già la loro casella di ricerca sopra
 *     l'elenco e la vogliono live (modulo Anagrafica). Ritorna false se la
 *     tabella non è gestita dal componente. L'init è async: chi pilota la
 *     tabella dall'esterno ascolti l'evento `fm-table:ready` sul <table>.
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

  const ICON_ATTRS = 'viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" ' +
    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="fm-tbl-ico"';
  const ICON_COLUMNS = '<svg ' + ICON_ATTRS + '><rect x="1.75" y="2.25" width="12.5" height="11.5" rx="2"/>' +
    '<path d="M6 2.5v11M10 2.5v11"/></svg>';
  const ICON_EXPAND = '<svg ' + ICON_ATTRS + '><path d="M2 6V2.5h3.5M14 6V2.5h-3.5M2 10v3.5h3.5M14 10v3.5h-3.5"/></svg>';
  const ICON_COLLAPSE = '<svg ' + ICON_ATTRS + '><path d="M5.5 2v3.5H2M10.5 2v3.5H14M5.5 14v-3.5H2M10.5 14v-3.5H14"/></svg>';

  // Larghezze colonna ammesse (px) e blocco del caricamento passo passo.
  const COL_MIN_W = 44;
  const COL_MAX_W = 900;
  const FM_CHUNK = 100;
  function clampWidth(w) { return Math.max(COL_MIN_W, Math.min(COL_MAX_W, Math.round(w))); }

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

  // Una "detail row" è una riga figlia di espansione (es. dettaglio collassabile
  // di una riga dati) che NON deve partecipare a filtro/sort/visibilità del
  // componente: la sua visibilità è controllata da JS esterno (toggle). Si
  // marca con class="fm-detail-row" oppure data-fm-detail-row="1".
  function isDetailRow(row) {
    return !!(row && row.nodeType === 1 && (
      row.classList.contains("fm-detail-row") ||
      (row.dataset && row.dataset.fmDetailRow === "1")
    ));
  }

  function bodyRows(table) {
    return table.tBodies && table.tBodies[0]
      // Solo le righe dirette del tbody: una tabella annidata dentro una
      // riga di dettaglio non deve finire nel conteggio né nei filtri.
      ? Array.from(table.tBodies[0].rows).filter(tr => !isDetailRow(tr))
      : [];
  }

  function rowCellCount(row) {
    return row && row.cells ? row.cells.length : 0;
  }

  // Griglia dell'intestazione, anche su più righe. Per ogni colonna del corpo
  // restituisce la cella «foglia» (quella dell'ultima riga del thead che la
  // copre, eventualmente con rowspan dall'alto) e l'elenco delle celle di
  // gruppo con le colonne che coprono. null se il thead non si riconduce a una
  // cella per colonna (foglia con colspan > 1).
  function headerGrid(table) {
    const thead = table.tHead;
    if (!thead || !thead.rows.length) return null;
    const rows = Array.from(thead.rows);
    const last = rows.length - 1;
    const grid = rows.map(() => []);
    rows.forEach((tr, r) => {
      let c = 0;
      Array.from(tr.cells).forEach((cell) => {
        while (grid[r][c]) c += 1;
        const rs = Math.max(1, cell.rowSpan || 1);
        const cs = Math.max(1, cell.colSpan || 1);
        for (let dr = 0; dr < rs && r + dr <= last; dr += 1) {
          for (let dc = 0; dc < cs; dc += 1) grid[r + dr][c + dc] = cell;
        }
        c += cs;
      });
    });
    const leaves = [];
    for (let c = 0; c < grid[last].length; c += 1) {
      const th = grid[last][c];
      if (!th || (th.colSpan || 1) > 1) return null;
      leaves.push(th);
    }
    const leafSet = new Set(leaves);
    const groupMap = new Map();
    for (let r = 0; r < last; r += 1) {
      grid[r].forEach((cell, c) => {
        if (!cell || leafSet.has(cell)) return;
        if (!groupMap.has(cell)) groupMap.set(cell, []);
        const list = groupMap.get(cell);
        if (!list.includes(c)) list.push(c);
      });
    }
    const groups = Array.from(groupMap, ([th, cols]) => ({ th, cols }));
    return { leaves, groups };
  }

  function headerLabels(table) {
    const grid = headerGrid(table);
    if (!grid) return [];
    return grid.leaves.map(th => cleanText(th.dataset.colLabel || th.textContent || ""));
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

  // Nasconde solo la barra controlli sopra la tabella (ricerca globale, menu
  // Colonne, Reset, contatore), lasciando attive le icone di ordina/filtro per
  // colonna negli header. Opt-out per tabella o per antenato (es. su <body>
  // per coprire tutte le tabelle di un modulo).
  function controlsHidden(table) {
    return !!(
      table.dataset.fmHideControls === "1" ||
      table.closest("[data-fm-hide-controls='1']")
    );
  }

  function hasUnsupportedHeader(table) {
    return headerGrid(table) === null;
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
    if (hasUnsupportedHeader(table)) return false;

    const colCount = headerGrid(table).leaves.length;
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
    const grid = headerGrid(table);
    return filled > 0 && actionCells === filled && !!grid && idx === grid.leaves.length - 1;
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
    const grid = headerGrid(table);
    if (!grid) return false;

    const usedKeys = {};
    grid.leaves.forEach((th, idx) => {
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
    return grid.leaves.some(th => !!th.dataset.col);
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
        widths:  state.widths || {},
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

  // ─── Viste salvate ────────────────────────────────────────────────────────
  // Una vista = colonne, ordine, ordinamento, filtri e ricerca con un nome.
  // Stesso endpoint e stesso modello delle preferenze, record a parte
  // `<table_id>::viste` (così il salvataggio automatico non le cancella).
  // Applicare una vista ricarica la pagina: lo stato passa in sessionStorage e
  // initTable lo usa al posto delle preferenze, filtri e ricerca compresi.
  const VIEWS_MAX = 12;
  const VIEWS_PENDING = "fm-tbl-vista:";

  function viewsId(tableId) {
    const base = tableId.length > 93 ? tableId.slice(0, 84) + "~" + shortHash(tableId) : tableId;
    return base + "::viste";
  }

  async function fetchViews(tableId) {
    const st = await fetchPrefs(viewsId(tableId));
    return Array.isArray(st.viste) ? st.viste.filter(v => v && typeof v.nome === "string" && v.stato) : [];
  }

  async function saveViews(tableId, viste) {
    try {
      const r = await fetch(API_BASE + encodeURIComponent(viewsId(tableId)) + "/", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
        body: JSON.stringify({ state: { viste: viste } }),
      });
      return r.ok;
    } catch (e) { return false; }
  }

  function takePendingView(tableId) {
    try {
      const raw = sessionStorage.getItem(VIEWS_PENDING + tableId);
      if (!raw) return null;
      sessionStorage.removeItem(VIEWS_PENDING + tableId);
      const v = JSON.parse(raw);
      return v && v.stato ? v : null;
    } catch (e) { return null; }
  }

  function buildViewsMenu(table, state, statusEl) {
    const tableId = table.dataset.tableId;
    const menu = document.createElement("div");
    menu.className = "fm-tbl-menu fm-tbl-views";
    let viste = null;

    function snapshot() {
      return {
        visible: state.visible.slice(),
        order: state.order.slice(),
        sort: state.sort.map(s => s.slice()),
        filters: Object.assign({}, state.filters),
        q: state.q || "",
      };
    }

    function render() {
      menu.innerHTML = "";
      const title = document.createElement("div");
      title.className = "fm-tbl-views-title";
      title.textContent = "Viste salvate";
      menu.appendChild(title);
      if (viste === null) {
        const p = document.createElement("div");
        p.className = "fm-tbl-views-empty";
        p.textContent = "Caricamento…";
        menu.appendChild(p);
        return;
      }
      if (!viste.length) {
        const p = document.createElement("div");
        p.className = "fm-tbl-views-empty";
        p.textContent = "Nessuna vista salvata. Imposta colonne, filtri e ordinamento, poi salvala qui sotto.";
        menu.appendChild(p);
      }
      const ul = document.createElement("ul");
      ul.className = "fm-tbl-col-list";
      viste.forEach((v, i) => {
        const li = document.createElement("li");
        li.className = "fm-tbl-views-item";
        const apply = document.createElement("button");
        apply.type = "button";
        apply.className = "fm-tbl-views-apply";
        apply.textContent = v.nome;
        apply.title = "Applica la vista «" + v.nome + "»";
        apply.addEventListener("click", () => {
          try { sessionStorage.setItem(VIEWS_PENDING + tableId, JSON.stringify(v)); } catch (e) { return; }
          location.reload();
        });
        const del = document.createElement("button");
        del.type = "button";
        del.className = "fm-tbl-views-del";
        del.textContent = "×";
        del.title = "Elimina la vista «" + v.nome + "»";
        del.setAttribute("aria-label", del.title);
        del.addEventListener("click", async (e) => {
          e.stopPropagation();
          if (!(await hubConfirm("Eliminare la vista «" + v.nome + "»?"))) return;
          const next = viste.filter((_, j) => j !== i);
          if (await saveViews(tableId, next)) { viste = next; render(); }
          else if (statusEl) statusEl.textContent = "⚠ Errore salvataggio";
        });
        li.appendChild(apply);
        li.appendChild(del);
        ul.appendChild(li);
      });
      menu.appendChild(ul);

      const add = document.createElement("button");
      add.type = "button";
      add.className = "fm-tbl-views-add";
      add.textContent = "＋ Salva la vista attuale…";
      add.addEventListener("click", async (e) => {
        e.stopPropagation();
        const nome = cleanText(prompt("Nome della vista (colonne, filtri, ricerca e ordinamento di adesso):") || "").slice(0, 60);
        if (!nome) return;
        const idx = viste.findIndex(v => v.nome.toLowerCase() === nome.toLowerCase());
        if (idx >= 0 && !(await hubConfirm("Esiste già una vista «" + viste[idx].nome + "»: sostituirla?"))) return;
        if (idx < 0 && viste.length >= VIEWS_MAX) {
          alert("Puoi salvare al massimo " + VIEWS_MAX + " viste per tabella: eliminane una.");
          return;
        }
        const next = viste.slice();
        const item = { nome: nome, stato: snapshot() };
        if (idx >= 0) next[idx] = item; else next.push(item);
        if (await saveViews(tableId, next)) {
          viste = next;
          render();
          if (statusEl) {
            statusEl.textContent = "✓ Vista «" + nome + "» salvata";
            setTimeout(() => { statusEl.textContent = ""; }, 2200);
          }
        } else {
          alert("Vista non salvata: troppi filtri o connessione assente.");
        }
      });
      menu.appendChild(add);
    }

    menu._fmOpen = async function () {
      if (viste === null) {
        render();
        viste = await fetchViews(tableId);
      }
      render();
    };
    return menu;
  }

  // ─── Parsing colonne ──────────────────────────────────────────────────────

  function parseColumns(table) {
    const grid = headerGrid(table);
    if (!grid) return [];
    const cols = [];
    grid.leaves.forEach((th, idx) => {
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
        hidden:     th.dataset.colHidden === "1",
      });
    });
    return cols;
  }

  function defaultState(cols) {
    const named = cols.filter(c => c.key);
    return {
      // `data-col-hidden="1"` → colonna presente ma NON visibile di default
      // (resta riattivabile dal menu "Colonne ▾"). Additivo: default = visibile.
      visible: named.filter(c => !c.hidden).map(c => c.key),
      order:   named.map(c => c.key),
      sort:    [],          // [[key,"asc"|"desc"], …]
      filters: {},
      q:       "",
      widths:  {},          // { key: px } solo per le colonne allargate/strette a mano
    };
  }

  function mergeState(defaults, saved) {
    if (!saved || typeof saved !== "object") return defaults;
    const out = JSON.parse(JSON.stringify(defaults));
    if (Array.isArray(saved.visible)) {
      // Tieni solo le chiavi note dello stato salvato, ma AGGIUNGI come visibili
      // le colonne nuove (presenti nei default ma non ancora nella preferenza
      // salvata), altrimenti una colonna introdotta dopo resterebbe nascosta
      // per gli utenti che hanno già una preferenza memorizzata.
      const savedVisible = saved.visible.filter(k => defaults.order.includes(k));
      const savedKnown = new Set(saved.visible);
      const newlyAdded = defaults.visible.filter(k => !savedKnown.has(k));
      out.visible = savedVisible.concat(newlyAdded);
    }
    if (Array.isArray(saved.order)) {
      const known = new Set(defaults.order);
      const merged = saved.order.filter(k => known.has(k));
      defaults.order.forEach(k => { if (!merged.includes(k)) merged.push(k); });
      out.order = merged;
    }
    if (Array.isArray(saved.sort)) out.sort = saved.sort.filter(s => Array.isArray(s) && s.length === 2);
    if (saved.filters && typeof saved.filters === "object") out.filters = saved.filters;
    if (typeof saved.q === "string") out.q = saved.q;
    if (saved.widths && typeof saved.widths === "object") {
      const known = new Set(defaults.order);
      Object.keys(saved.widths).forEach((k) => {
        const w = Number(saved.widths[k]);
        if (known.has(k) && Number.isFinite(w)) out.widths[k] = clampWidth(w);
      });
    }
    return out;
  }

  // ─── Barra controlli sopra la tabella ────────────────────────────────────

  function buildControlsBar(table, cols, state, onChange, statusEl) {
    const bar = document.createElement("div");
    bar.className = "fm-tbl-controls";

    // Search globale — opt-out per tabella con data-fm-hide-search="1"
    // (utile quando la pagina ha già una ricerca rapida dedicata sopra la tabella).
    if (table.dataset.fmHideSearch !== "1" && !table.closest("[data-fm-hide-search='1']")) {
      const searchWrap = document.createElement("div");
      searchWrap.className = "fm-tbl-search";
      searchWrap.innerHTML = '<span class="fm-tbl-search-ico">🔍</span>';
      const search = document.createElement("input");
      search.type = "search";
      search.placeholder = "Cerca…";
      search.value = state.q || "";
      search.addEventListener("input", () => { state.q = search.value; onChange(); });
      // Riferimento per `_fmSetSearch`: una ricerca impostata dall'esterno
      // (es. la casella di ricerca della pagina) deve restare in sincronia con
      // questa casella, altrimenti i due campi mostrano query diverse.
      table._fmSearchInput = search;
      searchWrap.appendChild(search);
      bar.appendChild(searchWrap);
    }

    // Pulsante Colonne ▾
    const colsBtn = document.createElement("button");
    colsBtn.type = "button";
    colsBtn.className = "fm-tbl-btn";
    colsBtn.innerHTML = ICON_COLUMNS + "Colonne ▾";
    colsBtn.title = "Mostra, nascondi e riordina le colonne";
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

    // Viste ▾ (salvate per utente, con nome)
    const viewsBtn = document.createElement("button");
    viewsBtn.type = "button";
    viewsBtn.className = "fm-tbl-btn";
    viewsBtn.textContent = table._fmViewName ? "Vista: " + table._fmViewName + " ▾" : "Viste ▾";
    viewsBtn.title = "Viste salvate: richiama colonne, filtri e ordinamento con un clic";
    const viewsMenu = buildViewsMenu(table, state, statusEl);
    viewsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      colsMenu.classList.remove("fm-tbl-menu-open");
      const open = viewsMenu.classList.toggle("fm-tbl-menu-open");
      if (open) viewsMenu._fmOpen();
    });
    document.addEventListener("click", (e) => {
      if (!viewsMenu.contains(e.target) && e.target !== viewsBtn) {
        viewsMenu.classList.remove("fm-tbl-menu-open");
      }
    });
    const viewsWrap = document.createElement("div");
    viewsWrap.className = "fm-tbl-menu-wrap";
    viewsWrap.appendChild(viewsBtn);
    viewsWrap.appendChild(viewsMenu);
    bar.appendChild(viewsWrap);

    // Reset
    const resetBtn = document.createElement("button");
    resetBtn.type = "button";
    resetBtn.className = "fm-tbl-btn fm-tbl-btn-ghost";
    resetBtn.textContent = "Reset";
    resetBtn.addEventListener("click", async () => {
      if (!(await hubConfirm("Ripristinare le preferenze di default per questa tabella?"))) return;
      const tableId = table.dataset.tableId;
      await deletePrefs(tableId);
      location.reload();
    });
    bar.appendChild(resetBtn);

    // Schermo intero: cablato in initTable, che conosce il contenitore da
    // portare a tutto schermo. Nascosto se il browser non lo supporta.
    if (document.fullscreenEnabled) {
      const fsBtn = document.createElement("button");
      fsBtn.type = "button";
      fsBtn.className = "fm-tbl-btn fm-tbl-btn-fs";
      fsBtn.innerHTML = ICON_EXPAND + "<span>Schermo intero</span>";
      fsBtn.title = "Apri la tabella a tutto schermo (Esc per uscire)";
      table._fmFsBtn = fsBtn;
      bar.appendChild(fsBtn);
    }

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
    // A schermo intero si vede solo il sottoalbero dell'elemento a tutto
    // schermo: il popover deve stare lì dentro, non in <body>.
    const host = document.fullscreenElement || document.body;
    if (pop.parentNode !== host) {
      host.appendChild(pop);
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
    // Righe dati reali (escluse le detail-row di espansione, controllate da JS esterno)
    const dataRows = bodyRows(table);

    // Visibilità colonne
    const visible = new Set(state.visible);
    cols.forEach((col) => {
      if (!col.key) return;
      const hide = !visible.has(col.key) && !col.locked;
      col.th.style.display = hide ? "none" : "";
      dataRows.forEach(tr => {
        const cell = tr.cells[col.idx];
        if (cell) cell.style.display = hide ? "none" : "";
      });
    });

    // Gruppi d'intestazione: il colspan segue le colonne visibili sotto.
    if (table._fmGroups) {
      const hiddenIdx = new Set(cols.filter(c => c.key && c.th.style.display === "none").map(c => c.idx));
      table._fmGroups.forEach((g) => {
        const n = g.cols.filter(i => !hiddenIdx.has(i)).length;
        g.th.colSpan = Math.max(1, n);
        g.th.style.display = n ? "" : "none";
      });
    }

    // Filtra (solo righe dati), poi ordina le righe che passano il filtro.
    const matched = [];
    dataRows.forEach((tr) => { if (rowMatchesFilters(tr, cols, state)) matched.push(tr); });

    // Sort: riordina le righe dati portando con sé le eventuali detail-row figlie.
    if (state.sort.length) {
      matched.sort((a, b) => compareRows(a, b, cols, state));
      const tbody = table.tBodies[0];
      const frag = document.createDocumentFragment();
      matched.forEach(r => {
        const details = [];
        let sib = r.nextElementSibling;
        while (sib && isDetailRow(sib)) { details.push(sib); sib = sib.nextElementSibling; }
        frag.appendChild(r);
        details.forEach(d => frag.appendChild(d));
      });
      tbody.appendChild(frag);
    }

    // Caricamento passo passo: delle righe che passano il filtro se ne
    // disegnano solo le prime `_fmWindow`; le altre arrivano scorrendo.
    // Le detail-row seguono il padre: nascoste se il padre lo è, altrimenti
    // restano come le ha lasciate il loro toggle.
    const limit = progressiveLimit(table, dataRows.length);
    const shownSet = new Set(matched.slice(0, limit));
    dataRows.forEach((tr) => {
      const show = shownSet.has(tr);
      tr.style.display = show ? "" : "none";
      let sib = tr.nextElementSibling;
      while (sib && isDetailRow(sib)) {
        if (!show) {
          // Si ricorda com'era: ritornato visibile il padre, il dettaglio
          // torna aperto o chiuso come l'aveva lasciato il suo toggle.
          if (sib.dataset.fmHidByParent !== "1") {
            sib.dataset.fmPrevDisplay = sib.style.display || "";
            sib.dataset.fmHidByParent = "1";
          }
          sib.style.display = "none";
        } else if (sib.dataset.fmHidByParent === "1") {
          sib.style.display = sib.dataset.fmPrevDisplay || "";
          delete sib.dataset.fmHidByParent;
          delete sib.dataset.fmPrevDisplay;
        }
        sib = sib.nextElementSibling;
      }
    });

    updateSortIndicators(cols, state);

    // Conta (solo righe dati): quelle che passano il filtro, non solo quelle
    // già disegnate.
    table._fmMatched = matched.length;
    const countEl = table._fmTblCountEl || (table.parentNode.parentNode && table.parentNode.parentNode.querySelector(".fm-tbl-count"));
    if (countEl) {
      const tot = dataRows.length;
      countEl.textContent = matched.length < tot
        ? `${formatInt(matched.length)} / ${formatInt(tot)}`
        : formatInt(tot);
    }
    updateMoreFooter(table, cols, matched.length, Math.min(limit, matched.length));
    syncColgroup(table, cols, state);
    refreshViewportMode(table);
  }

  function formatInt(n) {
    return Number(n || 0).toLocaleString("it-IT");
  }

  // ─── Caricamento passo passo ─────────────────────────────────────────────
  //
  // Sotto la soglia (1,5 blocchi) la tabella si disegna intera come sempre.
  // Sopra, se ne mostrano `_fmWindow` righe; il piede della tabella dice
  // quante ne restano e ne aggiunge un blocco quando lo si raggiunge
  // scorrendo, oppure su richiesta. Le tabelle paginate dal server caricano
  // la pagina successiva quando le righe già scaricate sono finite.

  function chunkSize(table) {
    const cap = parseInt(table.dataset.fmRowCap || "0", 10);
    return cap > 0 ? cap : FM_CHUNK;
  }

  function progressiveAllowed(table) {
    if (table.dataset.fmProgressive === "0") return false;
    // Con una casella «seleziona tutti» nell'intestazione le righe non ancora
    // disegnate finirebbero selezionate senza che l'utente le veda: queste
    // tabelle (azioni di massa) si disegnano sempre intere e tengono il loro
    // pager.
    if (table._fmBulkHeader === undefined) {
      table._fmBulkHeader = !!(table.tHead && table.tHead.querySelector("input[type='checkbox']"));
    }
    return !table._fmBulkHeader;
  }

  function progressiveEnabled(table, totalRows) {
    if (!progressiveAllowed(table)) return false;
    if (serverPagesLeft(table) > 0) return true;
    const chunk = chunkSize(table);
    return parseInt(table.dataset.fmRowCap || "0", 10) > 0 || totalRows > chunk * 1.5;
  }

  function progressiveLimit(table, totalRows) {
    if (!progressiveEnabled(table, totalRows)) return Infinity;
    if (!table._fmWindow) table._fmWindow = chunkSize(table);
    return table._fmWindow;
  }

  function serverPagesLeft(table) {
    const pag = table._fmPag;
    if (!pag || _fmLoadAllDone.has(table)) return 0;
    let left = 0;
    for (let p = 1; p <= pag.lastPage; p += 1) if (!pag.loaded.has(p)) left += 1;
    return left;
  }

  function buildMoreFooter(table) {
    const tfoot = document.createElement("tfoot");
    tfoot.className = "fm-tbl-more-foot";
    const tr = document.createElement("tr");
    tr.className = "fm-tbl-more-row";
    const td = document.createElement("td");
    td.className = "fm-tbl-more-cell";
    const inner = document.createElement("div");
    inner.className = "fm-tbl-more";
    inner.innerHTML =
      '<div class="fm-tbl-more-bar" aria-hidden="true"><span></span></div>' +
      '<span class="fm-tbl-more-text" aria-live="polite"></span>' +
      '<span class="fm-tbl-more-actions">' +
      '<button type="button" class="fm-tbl-more-btn" data-act="more"></button>' +
      '<button type="button" class="fm-tbl-more-btn fm-tbl-more-btn-ghost" data-act="all">Mostra tutte</button>' +
      '</span>';
    td.appendChild(inner);
    tr.appendChild(td);
    tfoot.appendChild(tr);
    // Un <table> ha un solo <tfoot>: se la pagina ne ha già uno (totali) la
    // nostra riga si accoda lì.
    if (table.tFoot) table.tFoot.appendChild(tr);
    else table.appendChild(tfoot);
    table._fmMore = { tr, td, inner };
    return table._fmMore;
  }

  function updateMoreFooter(table, cols, matchedCount, shownCount) {
    const enabled = progressiveEnabled(table, bodyRows(table).length);
    const left = serverPagesLeft(table);
    const needsMore = enabled && (shownCount < matchedCount || left > 0);
    if (!needsMore) {
      if (table._fmMore) table._fmMore.tr.hidden = true;
      return;
    }
    const more = table._fmMore || buildMoreFooter(table);
    more.tr.hidden = false;
    more.td.colSpan = Math.max(1, cols.filter(c => c.th.style.display !== "none").length);
    const chunk = chunkSize(table);
    const loading = !!table._fmPageLoading;
    const pag = table._fmPag;
    let text = "Visualizzate <b>" + formatInt(shownCount) + "</b> di <b>" + formatInt(matchedCount) + "</b> righe";
    if (left > 0 && pag) {
      const done = pag.lastPage - left;
      text += done === 1
        ? " · pagina 1 di " + formatInt(pag.lastPage)
        : " · pagine 1–" + formatInt(done) + " di " + formatInt(pag.lastPage);
    }
    more.inner.querySelector(".fm-tbl-more-text").innerHTML = loading ? "Carico altre righe…" : text;
    const pct = left > 0 && pag
      ? Math.round(((pag.lastPage - left) / pag.lastPage) * 100)
      : Math.round((shownCount / Math.max(1, matchedCount)) * 100);
    more.inner.querySelector(".fm-tbl-more-bar > span").style.width = Math.min(100, pct) + "%";
    more.inner.classList.toggle("is-loading", loading);
    const btnMore = more.inner.querySelector('[data-act="more"]');
    const rest = matchedCount - shownCount;
    btnMore.textContent = rest > 0
      ? "Mostra altre " + formatInt(Math.min(chunk, rest))
      : "Carica altre righe";
    btnMore.disabled = loading;
    more.inner.querySelector('[data-act="all"]').disabled = loading;
  }

  // Aggiunge un blocco di righe; se quelle già scaricate sono finite, scarica
  // la pagina successiva dal server. Ritorna true se qualcosa è cambiato.
  async function showMoreRows(table, cols, state) {
    const matched = table._fmMatched || 0;
    const chunk = chunkSize(table);
    if ((table._fmWindow || chunk) < matched) {
      table._fmWindow = (table._fmWindow || chunk) + chunk;
      applyState(table, cols, state);
      return true;
    }
    if (serverPagesLeft(table) > 0) {
      const loaded = await loadNextServerPage(table, cols);
      table._fmWindow = (table._fmWindow || chunk) + chunk;
      applyState(table, cols, state);
      return loaded;
    }
    return false;
  }

  async function showAllRows(table, cols, state, statusEl) {
    if (serverPagesLeft(table) > 0) {
      table._fmPageLoading = true;
      applyState(table, cols, state);
      await ensureFullDataset(table, statusEl, cols, null);
      table._fmPageLoading = false;
    }
    table._fmWindow = Infinity;
    applyState(table, cols, state);
  }

  function wireMoreFooter(table, cols, state, statusEl) {
    const getMore = () => table._fmMore || buildMoreFooter(table);
    const more = getMore();
    more.tr.hidden = true;
    more.inner.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-act]");
      if (!btn || btn.disabled) return;
      if (btn.dataset.act === "all") showAllRows(table, cols, state, statusEl);
      else showMoreRows(table, cols, state);
    });
    // Arrivati in fondo scorrendo, il blocco successivo si carica da solo.
    // Solo dopo che l'utente ha davvero fatto scorrere la tabella, altrimenti
    // un piede già visibile al caricamento farebbe arrivare tutto a cascata.
    if (!("IntersectionObserver" in window)) return;
    const vp = table._fmViewport;
    let userScrolled = false;
    const markScrolled = () => { userScrolled = true; };
    (vp || window).addEventListener("scroll", markScrolled, { passive: true });
    if (vp) window.addEventListener("scroll", markScrolled, { passive: true });
    let busy = false;
    const io = new IntersectionObserver((entries) => {
      if (!entries.some(en => en.isIntersecting)) return;
      if (!userScrolled || busy || more.tr.hidden || table._fmPageLoading) return;
      busy = true;
      // Un blocco per gesto: il successivo solo dopo un nuovo scorrimento.
      userScrolled = false;
      showMoreRows(table, cols, state).finally(() => { busy = false; });
    }, { root: null, rootMargin: "0px 0px 240px 0px" });
    io.observe(more.inner);
  }

  // ─── Area tabella: contenitore, intestazione fissa, schermo intero ───────
  //
  // Ogni tabella gestita sta in un `.fm-tbl-viewport`: si riusa il wrapper a
  // scorrimento orizzontale che la pagina ha già (se contiene solo la
  // tabella), altrimenti se ne crea uno. Il contenitore diventa scorrevole
  // (`fm-vp-scroll`) solo quando serve: tabella più alta dello schermo o più
  // larga della pagina. Così le tabelle piccole non cambiano affatto (nessun
  // menu a tendina nelle celle viene tagliato) e quelle grandi tengono
  // l'intestazione sempre in vista.

  function ensureViewport(table) {
    if (table._fmViewport) return table._fmViewport;
    if (table.dataset.fmViewport === "0" || table.closest("[data-fm-viewport='0']")) return null;
    const parent = table.parentElement;
    if (!parent) return null;
    let vp = null;
    if (parent.children.length === 1 && parent.tagName === "DIV") {
      const cs = window.getComputedStyle(parent);
      if (/(auto|scroll)/.test(cs.overflowX) || /(auto|scroll)/.test(cs.overflowY)) vp = parent;
    }
    if (!vp) {
      vp = document.createElement("div");
      parent.insertBefore(vp, table);
      vp.appendChild(table);
      vp.dataset.fmVpOwn = "1";
    }
    vp.classList.add("fm-tbl-viewport");
    table._fmViewport = vp;
    vp.addEventListener("scroll", () => {
      vp.classList.toggle("is-scrolled-y", vp.scrollTop > 2);
      vp.classList.toggle("is-scrolled-x", vp.scrollLeft > 2);
    }, { passive: true });
    return vp;
  }

  function refreshViewportMode(table) {
    const vp = table._fmViewport;
    if (!vp) return;
    // Una tabella che scorre in un riquadro proprio non deve «saltare» quando
    // compare una riga in più: una volta scorrevole, resta tale.
    if (vp.classList.contains("fm-vp-scroll")) return;
    const tall = table.offsetHeight > window.innerHeight * 0.72;
    const wide = table.offsetWidth > vp.clientWidth + 2;
    if (tall || wide) vp.classList.add("fm-vp-scroll");
    if (tall) vp.classList.add("fm-vp-tall");
  }

  // Colonne strette: le icone ordina/filtro passano nell'angolo (CSS
  // `fm-th-narrow`) e l'etichetta intera finisce nel tooltip.
  function markNarrowHeaders(cols) {
    cols.forEach((col) => {
      if (!col.key || col.th.style.display === "none") return;
      const narrow = col.th.getBoundingClientRect().width < 92;
      col.th.classList.toggle("fm-th-narrow", narrow);
      if (narrow && !col.th.title) col.th.title = col.label || col.key;
    });
  }

  function fullscreenTitle(table) {
    const scope = table.closest("section, article, .card, .rg-card, .hr-card, .ana-card") || null;
    const h = scope && scope.querySelector("h1, h2, h3, .card-title, .fmd-block-title");
    const pageH1 = document.querySelector(".content h1");
    const text = (h && h.textContent) || (pageH1 && pageH1.textContent) || document.title.split("|")[0];
    return cleanText(text);
  }

  function wireFullscreen(table, shell) {
    const btn = table._fmFsBtn;
    if (!btn || !shell || !shell.requestFullscreen) { if (btn) btn.hidden = true; return; }
    const title = document.createElement("span");
    title.className = "fm-tbl-fs-title";
    title.textContent = fullscreenTitle(table);
    const bar = shell.querySelector(":scope > .fm-tbl-controls");
    if (bar) bar.insertBefore(title, bar.firstChild);
    btn.addEventListener("click", () => {
      if (document.fullscreenElement === shell) document.exitFullscreen();
      else shell.requestFullscreen().catch(() => { /* negato dal browser */ });
    });
    document.addEventListener("fullscreenchange", () => {
      const on = document.fullscreenElement === shell;
      shell.classList.toggle("is-fullscreen", on);
      btn.innerHTML = on ? ICON_COLLAPSE + "<span>Esci (Esc)</span>" : ICON_EXPAND + "<span>Schermo intero</span>";
      btn.classList.toggle("active", on);
      // I popover dei filtri migrano dentro/fuori l'elemento a tutto schermo.
      document.querySelectorAll(".fm-th-filter-pop-open").forEach(p => p.classList.remove("fm-th-filter-pop-open"));
      if (on && table._fmViewport) table._fmViewport.classList.add("fm-vp-scroll");
    });
  }

  // ─── Larghezza colonne ───────────────────────────────────────────────────
  //
  // Finché nessuno tocca le larghezze la tabella resta a layout automatico,
  // come l'ha disegnata la pagina. Al primo ridimensionamento (o se l'utente
  // ha larghezze salvate) si fotografano le larghezze correnti, si passa a
  // `table-layout: fixed` con un <colgroup> nostro e da lì ogni colonna ha la
  // larghezza scelta; le celle troppo strette vanno a capo invece di
  // sbordare.

  function enterSizedMode(table, cols) {
    if (table._fmSized) return;
    const natural = {};
    cols.forEach((col) => {
      if (col.th.style.display === "none") return;
      natural[col.idx] = Math.round(col.th.getBoundingClientRect().width) || 120;
    });
    table._fmNatural = natural;
    // Un <colgroup> della pagina si sovrapporrebbe al nostro: le larghezze
    // che imponeva sono già nelle misure appena prese.
    $$(":scope > colgroup", table).forEach(cg => { if (!cg.classList.contains("fm-colgroup")) cg.remove(); });
    table._fmSized = true;
    table.classList.add("fm-tbl-sized");
  }

  function syncColgroup(table, cols, state) {
    if (!table._fmSized) return;
    let cg = table._fmColgroup;
    if (!cg) {
      cg = document.createElement("colgroup");
      cg.className = "fm-colgroup";
      table._fmColgroup = cg;
    }
    if (cg.parentNode !== table) {
      const caption = table.caption;
      table.insertBefore(cg, caption ? caption.nextSibling : table.firstChild);
    }
    const widths = state.widths || {};
    const parts = [];
    let total = 0;
    cols.forEach((col) => {
      if (col.th.style.display === "none") return;
      const w = (col.key && widths[col.key]) || (table._fmNatural && table._fmNatural[col.idx]) || 140;
      parts.push(w);
      total += w;
    });
    // Ricostruisce solo se cambia qualcosa: durante il trascinamento conta.
    const sig = parts.join(",");
    if (cg.dataset.sig !== sig) {
      while (cg.firstChild) cg.removeChild(cg.firstChild);
      parts.forEach((w) => {
        const c = document.createElement("col");
        c.style.width = w + "px";
        cg.appendChild(c);
      });
      cg.dataset.sig = sig;
    }
    table.style.tableLayout = "fixed";
    table.style.width = total + "px";
    table.style.minWidth = "0";
    table.style.maxWidth = "none";
  }

  function autoFitWidth(table, col) {
    // Per un istante la tabella torna a layout automatico, senza vincoli e
    // senza andare a capo: la larghezza dell'intestazione è allora quella
    // naturale della colonna.
    const cg = table._fmColgroup;
    const prev = { layout: table.style.tableLayout, width: table.style.width };
    if (cg && cg.parentNode) cg.parentNode.removeChild(cg);
    table.classList.add("fm-tbl-measuring");
    table.style.tableLayout = "auto";
    table.style.width = "max-content";
    const w = col.th.getBoundingClientRect().width;
    table.classList.remove("fm-tbl-measuring");
    table.style.tableLayout = prev.layout;
    table.style.width = prev.width;
    return clampWidth(w + 6);
  }

  function attachResizer(table, cols, col, state, onResized) {
    if (!col.key || table.dataset.fmResize === "0") return;
    const th = col.th;
    if (th.querySelector(":scope > .fm-th-resize")) return;
    const h = document.createElement("span");
    h.className = "fm-th-resize";
    h.tabIndex = 0;
    h.setAttribute("role", "separator");
    h.setAttribute("aria-orientation", "vertical");
    h.setAttribute("aria-label", "Larghezza colonna " + (col.label || col.key));
    h.title = "Trascina per allargare o stringere · doppio clic: adatta al contenuto";

    let frame = 0;
    const setWidth = (w) => {
      state.widths[col.key] = clampWidth(w);
      if (frame) return;
      frame = requestAnimationFrame(() => { frame = 0; syncColgroup(table, cols, state); });
    };

    h.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      enterSizedMode(table, cols);
      syncColgroup(table, cols, state);
      const startX = e.clientX;
      const startW = th.getBoundingClientRect().width;
      try { h.setPointerCapture(e.pointerId); } catch (_) { /* no-op */ }
      document.documentElement.classList.add("fm-col-resizing");
      h.classList.add("is-active");
      const move = (ev) => setWidth(startW + (ev.clientX - startX));
      const up = () => {
        h.removeEventListener("pointermove", move);
        h.removeEventListener("pointerup", up);
        h.removeEventListener("pointercancel", up);
        document.documentElement.classList.remove("fm-col-resizing");
        h.classList.remove("is-active");
        onResized();
      };
      h.addEventListener("pointermove", move);
      h.addEventListener("pointerup", up);
      h.addEventListener("pointercancel", up);
    });
    h.addEventListener("dblclick", (e) => {
      e.preventDefault();
      e.stopPropagation();
      enterSizedMode(table, cols);
      state.widths[col.key] = autoFitWidth(table, col);
      syncColgroup(table, cols, state);
      onResized();
    });
    h.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      enterSizedMode(table, cols);
      const cur = th.getBoundingClientRect().width;
      setWidth(cur + (e.key === "ArrowRight" ? 16 : -16));
      onResized();
    });
    // Il clic sulla maniglia non deve arrivare all'intestazione (alcune
    // pagine ordinano al clic sul <th>).
    h.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); });
    th.appendChild(h);
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

  // Nome del parametro di pagina: `page` di default; una pagina con più
  // elenchi paginati ne dà uno per tabella con `data-fm-page-param="log_page"`.
  function pageParam(table) {
    return table.dataset.fmPageParam || "page";
  }

  function pagerLinks(table, scope) {
    const param = pageParam(table);
    return $$('a[href*="' + param + '="]', scope).filter((a) => {
      try { return new URL(a.href, window.location.href).searchParams.has(param); }
      catch (e) { return false; }
    });
  }

  function detectPagination(table) {
    const scope = tablePageScope(table);
    const param = pageParam(table);
    const urls = new Map();
    let lastPage = 1;
    pagerLinks(table, scope).forEach((a) => {
      try {
        const u = new URL(a.href, window.location.href);
        const p = parseInt(u.searchParams.get(param), 10);
        if (Number.isFinite(p) && p >= 1) {
          urls.set(p, u.toString());
          if (p > lastPage) lastPage = p;
        }
      } catch (e) { /* ignore malformed href */ }
    });
    let currentPage = 1;
    try {
      const cur = parseInt(new URL(window.location.href).searchParams.get(param) || "1", 10);
      if (Number.isFinite(cur) && cur >= 1) currentPage = cur;
    } catch (e) { /* ignore */ }
    // Numero di pagine dichiarato dal template (i pager mostrano spesso solo
    // le pagine vicine): <div data-fm-last-page="{{ page_obj.paginator.num_pages }}">.
    const declared = param === "page"
      ? scope.querySelector("[data-fm-last-page]:not([data-fm-page-param]), [data-fm-last-page][data-fm-page-param='page']")
      : scope.querySelector("[data-fm-last-page][data-fm-page-param='" + param + "']");
    if (declared) {
      const tot = parseInt(declared.getAttribute("data-fm-last-page"), 10);
      if (Number.isFinite(tot) && tot > lastPage) lastPage = tot;
    }
    // Fallback: parse "Pagina N / M" o "Pagina N di M" presente nei template
    const m = param === "page" ? (scope.textContent || "").match(/Pagina\s+(\d+)\s*(?:\/|di)\s*(\d+)/i) : null;
    if (m) {
      const n = parseInt(m[1], 10);
      const tot = parseInt(m[2], 10);
      if (Number.isFinite(n)) currentPage = n;
      if (Number.isFinite(tot) && tot > lastPage) lastPage = tot;
    }
    if (lastPage <= 1) return null;
    return { currentPage, lastPage, urls, param, loaded: new Set([currentPage]) };
  }

  function tableSignature(table) {
    if (table.id) return "id:" + table.id;
    // Considera data-table-id solo se proveniente dal template (non auto-generato lato JS)
    if (table.dataset.tableId && table.dataset.fmTblAuto !== "1") return "tid:" + table.dataset.tableId;
    const labels = headerLabels(table).join("|");
    return "hdr:" + pageClasses(table) + ":" + labels;
  }

  // Classi messe dalla pagina, senza quelle aggiunte da questo componente
  // (`fm-…`): altrimenti la tabella locale non si riconosce più nell'HTML
  // delle altre pagine scaricate.
  function pageClasses(t) {
    return Array.from(t.classList).filter(c => !/^fm-/.test(c)).sort().join(".");
  }

  function tableSignatureForFetched(t) {
    if (t.id) return "id:" + t.id;
    if (t.hasAttribute("data-table-id")) return "tid:" + t.getAttribute("data-table-id");
    const labels = headerLabels(t).join("|");
    return "hdr:" + pageClasses(t) + ":" + labels;
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
    const scope = tablePageScope(table);
    // Le classi generiche valgono solo per il parametro di default: con più
    // elenchi paginati nella pagina si nasconde solo il pager di questa tabella.
    const blocks = new Set(pageParam(table) === "page"
      ? $$(".hr-pag, .ana-pag, .pagination, .paginator, .pag, .pagin", scope)
      : []);
    // Anche i contenitori dei link `?page=` con nomi di classe propri
    // (es. `.rg-pager`): si risale al primo antenato «da paginazione».
    pagerLinks(table, scope).forEach((a) => {
      const box = a.parentElement && a.parentElement.closest("nav, [class*='pag']");
      if (box && box !== scope && !box.contains(table)) blocks.add(box);
    });
    blocks.forEach((el) => {
      if (el.getAttribute("data-fm-hidden") === "1") return;
      el.style.display = "none";
      el.setAttribute("data-fm-hidden", "1");
    });
  }

  function pageUrl(pag, p) {
    return pag.urls.get(p) || (function () {
      const url = new URL(window.location.href);
      url.searchParams.set(pag.param || "page", String(p));
      return url.toString();
    })();
  }

  // Scarica una pagina del server e accoda le sue righe al <tbody>.
  // Ritorna il numero di righe aggiunte.
  async function fetchAndMergePage(table, pag, p) {
    const sig = tableSignature(table);
    const allTables = Array.from(document.querySelectorAll("table"));
    const tableIndex = allTables.indexOf(table);
    const tbody = table.tBodies[0];
    let added = 0;
    try {
      const r = await fetch(pageUrl(pag, p), {
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
          let total = bodyRows(table).length;
          for (const row of remoteRows) {
            if (total >= FM_MAX_MERGED_ROWS) break;
            const cloned = document.importNode(row, true);
            cloned.dataset.fmExtra = "1";
            frag.appendChild(cloned);
            total += 1;
            added += 1;
          }
          tbody.appendChild(frag);
        }
      }
    } catch (e) { /* skip page on network/parse error */ }
    pag.loaded.add(p);
    return added;
  }

  // Caricamento passo passo delle tabelle paginate: la pagina successiva a
  // quelle già scaricate. Le pagine precedenti a quella aperta (se l'utente è
  // arrivato da un link `?page=N`) le scarica solo «Mostra tutte».
  async function loadNextServerPage(table, cols) {
    const pag = table._fmPag;
    if (!pag || table._fmPageLoading) return false;
    if (bodyRows(table).length >= FM_MAX_MERGED_ROWS) { _fmLoadAllDone.add(table); return false; }
    let next = null;
    for (let p = pag.currentPage + 1; p <= pag.lastPage; p += 1) {
      if (!pag.loaded.has(p)) { next = p; break; }
    }
    if (next === null) return false;
    table._fmPageLoading = true;
    if (table._fmMore) table._fmMore.inner.classList.add("is-loading");
    try {
      await fetchAndMergePage(table, pag, next);
    } finally {
      table._fmPageLoading = false;
    }
    if (serverPagesLeft(table) === 0) _fmLoadAllDone.add(table);
    refreshSelectFilterOptions(table, cols);
    refreshTextFilterDatalists(table, cols);
    return true;
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

    const pag = table._fmPag || detectPagination(table);
    if (!pag) { _fmLoadAllDone.add(table); return; }
    table._fmPag = pag;

    const promise = (async () => {
      // Aspetta un eventuale caricamento passo passo in corso.
      while (table._fmPageLoading) await new Promise(res => setTimeout(res, 80));

      const toFetch = [];
      for (let p = 1; p <= pag.lastPage; p += 1) {
        if (!pag.loaded.has(p)) toFetch.push({ page: p });
      }

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
        totalRows += await fetchAndMergePage(table, pag, item.page);
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
    let saved = await fetchPrefs(tableId);
    const persistOpts = buildPersistOpts(table);
    // I filtri/ricerca sono per default transitori: scartiamo dallo stato
    // salvato qualsiasi residuo (anche entry storiche da quando la persistenza
    // era totale) così la tabella si apre sempre pulita.
    if (!persistOpts.persistFilters) saved.filters = {};
    if (!persistOpts.persistSearch)  saved.q = "";
    // Vista scelta dal menu «Viste ▾» prima del ricaricamento: vale tutta,
    // filtri e ricerca compresi.
    const pendingView = takePendingView(tableId);
    if (pendingView) {
      // La vista non porta le larghezze: restano quelle dell'utente.
      saved = Object.assign({}, pendingView.stato, { widths: saved.widths });
      table._fmViewName = pendingView.nome;
    }
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

    const querySig = () => JSON.stringify([state.q || "", state.filters || {}, state.sort || []]);
    table._fmQuerySig = querySig();
    const onChange = () => {
      // Nuova ricerca/filtro/ordinamento: si riparte dal primo blocco.
      const sig = querySig();
      if (sig !== table._fmQuerySig) { table._fmQuerySig = sig; table._fmWindow = 0; }
      applyState(table, cols, state);
      schedulePrefsSave(tableId, state, statusEl, persistOpts);
      maybeLoadAll();
    };
    const onResized = () => {
      markNarrowHeaders(cols);
      schedulePrefsSave(tableId, state, statusEl, persistOpts);
    };

    // Gruppi d'intestazione (thead su più righe): servono per stringerli
    // quando si nascondono le loro colonne.
    const grid = headerGrid(table);
    table._fmGroups = grid && grid.groups.length ? grid.groups : null;
    if (table._fmGroups) table.classList.add("fm-tbl-grouped");

    // Paginazione del server: rilevata subito, prima che la si nasconda.
    // Aperta la prima pagina, le successive arrivano passo passo scorrendo.
    if (table.dataset.fmFullload !== "0" && table.dataset.fmTblPaginationSkip !== "1" &&
        progressiveAllowed(table)) {
      const pag = detectPagination(table);
      if (pag && pag.currentPage === 1) {
        table._fmPag = pag;
        hideServerPaginationBlock(table);
      }
    }

    // Decorazione header (sort + filter icone per ogni th[data-col]) e
    // maniglie di larghezza.
    cols.forEach(col => decorateHeader(col, state, onChange));
    cols.forEach(col => attachResizer(table, cols, col, state, onResized));

    const vp = ensureViewport(table);

    // Barra controlli sopra il wrap — saltata con data-fm-hide-controls (le
    // icone di ordina/filtro per colonna restano comunque attive).
    if (!controlsHidden(table)) {
      const wrap = tableControlAnchor(table);
      const bar = buildControlsBar(table, cols, state, onChange, statusEl);
      // Barra + tabella in un unico guscio: è lui che va a schermo intero.
      const shell = document.createElement("div");
      shell.className = "fm-tbl-shell";
      wrap.parentNode.insertBefore(shell, wrap);
      shell.appendChild(bar);
      shell.appendChild(wrap);
      wireFullscreen(table, shell);

      // Contatore
      const countSpan = document.createElement("span");
      countSpan.className = "fm-tbl-count";
      countSpan.title = "Righe che passano ricerca e filtri / righe totali";
      countSpan.textContent = String(bodyRows(table).length);
      table._fmTblCountEl = countSpan;
      bar.appendChild(countSpan);
    }

    wireMoreFooter(table, cols, state, statusEl);
    if (vp) window.addEventListener("resize", () => refreshViewportMode(table), { passive: true });

    // API programmatica per impostare/azzerare un filtro di colonna dall'esterno
    // (es. click su un KPI che filtra la tabella per anno). Aggiorna lo stato,
    // l'icona del funnel e l'input del popover, poi riapplica.
    table._fmSetColumnFilter = function (colKey, value) {
      const col = cols.find(c => c.key === colKey);
      if (!col) return false;
      if (value === "" || value == null) delete state.filters[colKey];
      else state.filters[colKey] = String(value);
      const active = !!state.filters[colKey];
      if (col._fmInput) col._fmInput.value = state.filters[colKey] || "";
      if (col._fmFilterBtn) {
        col._fmFilterBtn.classList.toggle("active", active);
        col._fmFilterBtn.innerHTML = active ? FUNNEL_SVG_ACTIVE : FUNNEL_SVG;
      }
      onChange();
      return true;
    };

    // Ricerca globale impostabile dall'esterno: serve alle pagine che hanno già
    // la loro casella di ricerca sopra l'elenco (modulo Anagrafica) e la vogliono
    // LIVE — delegando qui si riusa anche il caricamento delle altre pagine di
    // una tabella paginata server-side, che un filtro locale non saprebbe fare.
    table._fmSetSearch = function (value) {
      state.q = value == null ? "" : String(value);
      if (table._fmSearchInput && table._fmSearchInput.value !== state.q) {
        table._fmSearchInput.value = state.q;
      }
      onChange();
      return true;
    };

    // Applica stato iniziale e, se le preferenze salvate hanno già una query
    // attiva (filtro/sort/search), carica subito tutto il dataset così che il
    // primo render rifletta la filtro su tutti i record e non solo sulla pagina.
    applyState(table, cols, state);
    // Larghezze salvate: si fotografano quelle naturali e si applicano le sue.
    if (Object.keys(state.widths).length) {
      enterSizedMode(table, cols);
      syncColgroup(table, cols, state);
    }
    markNarrowHeaders(cols);
    maybeLoadAll();
    // Colonne e ordinamento della vista diventano le preferenze correnti.
    if (pendingView) schedulePrefsSave(tableId, state, statusEl, persistOpts);

    // initTable è async (fetchPrefs): chi vuole pilotare la tabella dall'esterno
    // non può sapere quando è pronta se non glielo diciamo.
    table.dispatchEvent(new CustomEvent("fm-table:ready", { bubbles: true }));
  }

  function resolveTable(tableOrId) {
    return typeof tableOrId === "string"
      ? document.querySelector('table[data-table-id="' + tableOrId + '"], #' + tableOrId)
      : tableOrId;
  }

  // Imposta (o azzera con value vuoto) un filtro di colonna su una tabella già
  // inizializzata. Ritorna true se applicato. Usato dai KPI cliccabili.
  function setColumnFilter(tableOrId, colKey, value) {
    const table = resolveTable(tableOrId);
    if (!table || typeof table._fmSetColumnFilter !== "function") return false;
    return table._fmSetColumnFilter(colKey, value);
  }

  // Imposta (o azzera) la ricerca globale su una tabella già inizializzata.
  // Ritorna false se la tabella non è (ancora) gestita dal componente: il
  // chiamante può allora applicare un filtro locale di ripiego.
  function setSearch(tableOrId, value) {
    const table = resolveTable(tableOrId);
    if (!table || typeof table._fmSetSearch !== "function") return false;
    return table._fmSetSearch(value);
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
  window.fmTableEnhanced = { init: initTable, initAll: initAll, setColumnFilter: setColumnFilter, setSearch: setSearch };
})();
