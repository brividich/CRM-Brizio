/*
 * sortable-table.js — NOVICROM HUB
 *
 * Aggiunge ordinamento e filtro per colonna a qualsiasi <table data-sortable>.
 * Opera solo lato client sulle righe attualmente nel DOM (es. pagina corrente
 * della paginazione lato server). Non sostituisce i filtri server-side.
 *
 * Markup richiesto:
 *   <table data-sortable> ... <thead><tr><th>Nome</th>...</tr></thead> ... </table>
 *
 * Opzioni per <th>:
 *   data-sort-type="text|number|date"  (default: text)
 *   data-no-sort                        — disabilita l'ordinamento per la colonna
 *   data-no-filter                      — disabilita il filtro per la colonna
 *
 * Per ordinare per un valore diverso dal testo visibile usa
 *   <td data-sort-value="2026-01-15">15 gen 2026</td>
 */
(function () {
  "use strict";

  const SORT_ICON = {
    none: "↕",
    asc: "▲",
    desc: "▼",
  };

  const COLLATOR = new Intl.Collator("it", {
    numeric: true,
    sensitivity: "base",
    ignorePunctuation: true,
  });

  function isBlankText(raw) {
    const t = raw.trim();
    return t === "" || t === "-" || t === "—" || t === "–";
  }

  function cellSortValue(cell, type) {
    let raw;
    if (cell == null) {
      raw = "";
    } else if (cell.dataset && cell.dataset.sortValue != null) {
      raw = cell.dataset.sortValue;
    } else {
      raw = (cell.textContent || "").replace(/\s+/g, " ").trim();
    }
    if (type === "number") {
      if (isBlankText(raw)) return { blank: true, value: 0 };
      const n = parseFloat(raw.replace(/[^\d,.\-]/g, "").replace(/\.(?=\d{3}(\D|$))/g, "").replace(",", "."));
      return { blank: false, value: Number.isFinite(n) ? n : NaN };
    }
    if (type === "date") {
      if (isBlankText(raw)) return { blank: true, value: 0 };
      const t = Date.parse(raw);
      return { blank: false, value: Number.isFinite(t) ? t : NaN };
    }
    return { blank: isBlankText(raw), value: raw };
  }

  function compareValues(a, b, type) {
    if (a.blank && b.blank) return 0;
    if (a.blank) return 1;
    if (b.blank) return -1;
    if (type === "number" || type === "date") {
      if (Number.isNaN(a.value) && Number.isNaN(b.value)) return 0;
      if (Number.isNaN(a.value)) return 1;
      if (Number.isNaN(b.value)) return -1;
      return a.value - b.value;
    }
    return COLLATOR.compare(String(a.value), String(b.value));
  }

  function compareRows(rowA, rowB, colIdx, type, dir) {
    const va = cellSortValue(rowA.cells[colIdx], type);
    const vb = cellSortValue(rowB.cells[colIdx], type);
    const cmp = compareValues(va, vb, type);
    if (cmp !== 0) return dir === "asc" ? cmp : -cmp;
    return rowA._stableIdx - rowB._stableIdx;
  }

  function applyFilters(tbody, filters) {
    const rows = Array.from(tbody.rows);
    for (const row of rows) {
      if (row.dataset.emptyRow === "1") continue;
      let visible = true;
      for (const [idx, term] of filters.entries()) {
        if (!term) continue;
        const cell = row.cells[idx];
        const text = cell ? (cell.textContent || "").trim().toLocaleLowerCase() : "";
        if (!text.includes(term.toLocaleLowerCase())) {
          visible = false;
          break;
        }
      }
      row.style.display = visible ? "" : "none";
    }
  }

  function setupTable(table) {
    const thead = table.tHead;
    const tbody = table.tBodies[0];
    if (!thead || !tbody) return;
    const headerRow = thead.rows[0];
    if (!headerRow) return;

    Array.from(tbody.rows).forEach((row, i) => { row._stableIdx = i; });

    const headers = Array.from(headerRow.cells);
    const filters = headers.map(() => "");
    let currentSort = { idx: -1, dir: null };

    headers.forEach((th, idx) => {
      const type = th.dataset.sortType || "text";
      const noSort = th.hasAttribute("data-no-sort");
      const noFilter = th.hasAttribute("data-no-filter");
      if (noSort && noFilter) return;

      th.classList.add("st-th");

      const labelHTML = th.innerHTML;
      th.innerHTML = "";

      const wrap = document.createElement("div");
      wrap.className = "st-th-wrap";

      const label = document.createElement("span");
      label.className = "st-th-label";
      label.innerHTML = labelHTML;
      wrap.appendChild(label);

      if (!noSort) {
        const sortBtn = document.createElement("button");
        sortBtn.type = "button";
        sortBtn.className = "st-sort";
        sortBtn.title = "Ordina";
        sortBtn.textContent = SORT_ICON.none;
        sortBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          let dir;
          if (currentSort.idx !== idx) dir = "asc";
          else if (currentSort.dir === "asc") dir = "desc";
          else if (currentSort.dir === "desc") dir = null;
          else dir = "asc";

          headers.forEach((other) => {
            const btn = other.querySelector(".st-sort");
            if (btn) btn.textContent = SORT_ICON.none;
          });

          sortBtn.textContent = dir ? SORT_ICON[dir] : SORT_ICON.none;
          const dataRows = Array.from(tbody.rows).filter(
            (r) => r.dataset.emptyRow !== "1"
          );
          if (dir) {
            dataRows.sort((a, b) => compareRows(a, b, idx, type, dir));
          } else {
            dataRows.sort((a, b) => a._stableIdx - b._stableIdx);
          }
          const frag = document.createDocumentFragment();
          for (const r of dataRows) frag.appendChild(r);
          tbody.appendChild(frag);
          currentSort = { idx: dir ? idx : -1, dir };
        });
        wrap.appendChild(sortBtn);
      }

      if (!noFilter) {
        const filterBtn = document.createElement("button");
        filterBtn.type = "button";
        filterBtn.className = "st-filter-toggle";
        filterBtn.title = "Filtra";
        filterBtn.setAttribute("aria-expanded", "false");
        filterBtn.textContent = "▾";
        const input = document.createElement("input");
        input.type = "text";
        input.className = "st-filter-input";
        input.placeholder = "Filtra…";
        input.style.display = "none";
        input.addEventListener("click", (e) => e.stopPropagation());
        input.addEventListener("input", () => {
          filters[idx] = input.value.trim();
          filterBtn.classList.toggle("active", filters[idx].length > 0);
          applyFilters(tbody, filters);
        });
        filterBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          const open = input.style.display !== "none";
          input.style.display = open ? "none" : "inline-block";
          filterBtn.setAttribute("aria-expanded", String(!open));
          if (!open) {
            input.focus();
            input.select();
          }
        });
        wrap.appendChild(filterBtn);
        wrap.appendChild(input);
      }

      th.appendChild(wrap);
    });
  }

  function init() {
    document.querySelectorAll("table[data-sortable]").forEach(setupTable);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
