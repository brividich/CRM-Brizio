/* NOVICROM HUB — Command palette (Ctrl+K / Cmd+K).
 *
 * Salto rapido a qualsiasi pagina di navigazione (gia' ACL-filtrata lato server in
 * `command-palette-data`). Vanilla, nessuna dipendenza. Si costruisce lazy alla
 * prima apertura; se non c'e' nulla da indicizzare (es. utente anonimo) non fa nulla.
 */
(function () {
  "use strict";

  var DATA = [];
  try {
    var el = document.getElementById("command-palette-data");
    DATA = el ? JSON.parse(el.textContent) || [] : [];
  } catch (e) { DATA = []; }
  if (!DATA.length) return;

  var overlay, input, list, items = [], active = -1;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function norm(s) { return String(s || "").toLowerCase(); }

  function build() {
    overlay = document.createElement("div");
    overlay.className = "nhub-cmdk";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "Vai a una pagina");
    overlay.innerHTML =
      '<div class="nhub-cmdk-box">' +
      '<input type="text" class="nhub-cmdk-input" placeholder="Vai a&hellip; (digita un modulo o una pagina)" aria-label="Cerca pagina">' +
      '<div class="nhub-cmdk-list" role="listbox"></div>' +
      '<div class="nhub-cmdk-hint">&uarr;&darr; per muoverti &middot; Invio per aprire &middot; Esc per chiudere</div>' +
      "</div>";
    document.body.appendChild(overlay);
    input = overlay.querySelector(".nhub-cmdk-input");
    list = overlay.querySelector(".nhub-cmdk-list");
    overlay.addEventListener("click", function (e) { if (e.target === overlay) close(); });
    input.addEventListener("input", render);
    input.addEventListener("keydown", onKey);
  }

  function filtered(q) {
    q = norm(q).trim();
    if (!q) return DATA.slice(0, 50);
    var terms = q.split(/\s+/);
    return DATA.filter(function (d) {
      var hay = norm(d.l) + " " + norm(d.g);
      return terms.every(function (t) { return hay.indexOf(t) !== -1; });
    }).slice(0, 50);
  }

  function render() {
    items = filtered(input.value);
    active = items.length ? 0 : -1;
    if (!items.length) {
      list.innerHTML = '<div class="nhub-cmdk-empty">Nessun risultato</div>';
      return;
    }
    list.innerHTML = items.map(function (d, i) {
      return '<div class="nhub-cmdk-item' + (i === 0 ? " active" : "") + '" data-i="' + i + '">' +
        '<span class="nhub-cmdk-item-label">' + esc(d.l) + "</span>" +
        (d.g ? '<span class="nhub-cmdk-item-group">' + esc(d.g) + "</span>" : "") +
        "</div>";
    }).join("");
    Array.prototype.forEach.call(list.querySelectorAll(".nhub-cmdk-item"), function (elx) {
      elx.addEventListener("click", function () { go(parseInt(elx.dataset.i, 10)); });
    });
  }

  function setActive(i) {
    var els = list.querySelectorAll(".nhub-cmdk-item");
    if (!els.length) return;
    active = (i + els.length) % els.length;
    Array.prototype.forEach.call(els, function (elx, j) { elx.classList.toggle("active", j === active); });
    els[active].scrollIntoView({ block: "nearest" });
  }

  function go(i) { if (items[i] && items[i].u) window.location.href = items[i].u; }

  function onKey(e) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter") { e.preventDefault(); if (active >= 0) go(active); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  }

  function open() { if (!overlay) build(); overlay.classList.add("open"); input.value = ""; render(); input.focus(); }
  function close() { if (overlay) overlay.classList.remove("open"); }

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (overlay && overlay.classList.contains("open")) close(); else open();
    }
  });
})();
