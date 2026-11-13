/* Modulo Notizie: visualizzatore allegati, editor (anteprima, ruoli, trascina file), pannello permessi. */
(function () {
  "use strict";

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function formatSize(bytes) {
    if (!bytes && bytes !== 0) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1).replace(".", ",") + " MB";
  }

  /* ── Visualizzatore allegati nella lettura ───────────────── */
  function initViewer() {
    var viewer = qs("[data-nz-viewer]");
    if (!viewer) return;
    var frame = qs("[data-nz-viewer-frame]", viewer);
    var img = qs("[data-nz-viewer-img]", viewer);
    var name = qs("[data-nz-viewer-name]", viewer);
    var full = qs("[data-nz-viewer-full]", viewer);
    var down = qs("[data-nz-viewer-download]", viewer);
    var fallback = qs("[data-nz-viewer-fallback]", viewer);
    // Telefoni: il PDF in iframe non si vede (o parte il download); si apre a schermo intero.
    var narrow = window.matchMedia("(max-width: 720px)");

    if (frame && frame.getAttribute("data-src") && !narrow.matches) {
      frame.src = frame.getAttribute("data-src");
    }

    function show(btn) {
      var url = btn.getAttribute("data-url");
      var tipo = btn.getAttribute("data-tipo");
      name.textContent = btn.getAttribute("data-nome") || "";
      full.href = url;
      down.href = btn.getAttribute("data-download");
      viewer.classList.toggle("is-pdf", tipo === "pdf");
      if (tipo === "pdf") {
        img.hidden = true;
        img.removeAttribute("src");
        frame.hidden = false;
        if (fallback) fallback.href = url;
        frame.src = narrow.matches ? "about:blank" : url + "#view=FitH&navpanes=0";
      } else {
        frame.hidden = true;
        frame.src = "about:blank";
        img.hidden = false;
        img.src = url;
        img.alt = name.textContent;
      }
      qsa("[data-nz-file]").forEach(function (row) { row.classList.remove("is-active"); });
      var row = btn.closest("[data-nz-file]");
      if (row) row.classList.add("is-active");
      if (window.matchMedia("(max-width: 1100px)").matches) {
        viewer.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    qsa("[data-nz-preview]").forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        if (btn.getAttribute("data-tipo") === "pdf" && narrow.matches) return; // apre la nuova scheda
        ev.preventDefault();
        show(btn);
      });
    });
  }

  /* ── Editor: Scrivi / Anteprima ─────────────────────────── */
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function linebreaks(text) {
    // Stessa resa del filtro Django «linebreaks» usato nella pagina di lettura.
    var paras = text.replace(/\r\n?/g, "\n").split(/\n{2,}/);
    return paras
      .filter(function (p) { return p.trim() !== ""; })
      .map(function (p) { return "<p>" + escapeHtml(p).replace(/\n/g, "<br>") + "</p>"; })
      .join("");
  }

  function initEditor() {
    var seg = qs("[data-nz-editor-tabs]");
    if (!seg) return;
    var write = qs("[data-nz-write]");
    var preview = qs("[data-nz-preview-pane]");
    var titolo = qs("[data-nz-titolo]");
    var corpo = qs("[data-nz-corpo]");
    var counter = qs("[data-nz-count]");

    function updateCount() {
      if (counter && corpo) counter.textContent = corpo.value.length.toLocaleString("it-IT") + " caratteri";
    }
    if (corpo) corpo.addEventListener("input", updateCount);
    updateCount();

    qsa("button", seg).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var mode = btn.getAttribute("data-mode");
        qsa("button", seg).forEach(function (b) { b.classList.toggle("active", b === btn); });
        if (mode === "preview") {
          var t = (titolo && titolo.value.trim()) || "";
          var body = (corpo && corpo.value.trim()) || "";
          preview.innerHTML =
            (t ? "<h2>" + escapeHtml(t) + "</h2>" : "") +
            (body ? '<div class="nz-body">' + linebreaks(body) + "</div>"
                  : '<p class="nz-preview-empty">Nessun testo da mostrare.</p>');
          write.hidden = true;
          preview.hidden = false;
        } else {
          preview.hidden = true;
          write.hidden = false;
        }
      });
    });
  }

  /* ── Editor: destinatari ────────────────────────────────── */
  function initRoles() {
    var box = qs("[data-nz-roles]");
    if (!box) return;
    var search = qs("[data-nz-roles-search]");
    var allMsg = qs("[data-nz-roles-all]");
    var countEl = qs("[data-nz-roles-count]");
    var clear = qs("[data-nz-roles-clear]");
    var inputs = qsa("input[type=checkbox]", box);

    function refresh() {
      var n = inputs.filter(function (i) { return i.checked; }).length;
      if (allMsg) allMsg.hidden = n > 0;
      if (countEl) countEl.textContent = n ? n + (n === 1 ? " ruolo" : " ruoli") : "Tutti";
      if (clear) clear.hidden = n === 0;
    }
    inputs.forEach(function (i) { i.addEventListener("change", refresh); });
    if (clear) {
      clear.addEventListener("click", function () {
        inputs.forEach(function (i) { i.checked = false; });
        refresh();
      });
    }
    if (search) {
      search.addEventListener("input", function () {
        var q = search.value.trim().toLowerCase();
        qsa("[data-nz-role]", box).forEach(function (el) {
          el.hidden = q !== "" && el.getAttribute("data-nome").indexOf(q) === -1;
        });
      });
    }
    refresh();
  }

  /* ── Editor: trascina file ──────────────────────────────── */
  function initDrop() {
    var drop = qs("[data-nz-drop]");
    if (!drop) return;
    var input = qs("input[type=file]", drop);
    var list = qs("[data-nz-drop-list]");
    var store = [];
    var canAssign = typeof DataTransfer === "function";

    function sync() {
      if (canAssign) {
        var dt = new DataTransfer();
        store.forEach(function (f) { dt.items.add(f); });
        input.files = dt.files;
      }
      render();
    }

    function render() {
      list.innerHTML = "";
      var files = canAssign ? store : Array.prototype.slice.call(input.files || []);
      files.forEach(function (f, idx) {
        var ext = (f.name.split(".").pop() || "").toLowerCase();
        var cls = ext === "pdf" ? "is-pdf" : (/^(png|jpe?g|gif|webp|bmp)$/.test(ext) ? "is-img" : "");
        var row = document.createElement("div");
        row.className = "nz-file is-new";
        row.innerHTML =
          '<div class="nz-file-ico ' + cls + '">' + escapeHtml(ext.slice(0, 4)) + "</div>" +
          '<div style="min-width:0"><div class="nz-file-name"></div><div class="nz-file-sub">Nuovo · ' +
          formatSize(f.size) + "</div></div>" +
          '<div class="nz-file-actions"></div>';
        row.querySelector(".nz-file-name").textContent = f.name;
        if (canAssign) {
          var rm = document.createElement("button");
          rm.type = "button";
          rm.className = "nz-btn nz-btn-danger";
          rm.textContent = "Togli";
          rm.addEventListener("click", function () { store.splice(idx, 1); sync(); });
          row.querySelector(".nz-file-actions").appendChild(rm);
        }
        list.appendChild(row);
      });
    }

    function add(files) {
      Array.prototype.forEach.call(files, function (f) {
        var dup = store.some(function (s) { return s.name === f.name && s.size === f.size; });
        if (!dup) store.push(f);
      });
      sync();
    }

    input.addEventListener("change", function () {
      if (canAssign) add(input.files); else render();
    });
    ["dragenter", "dragover"].forEach(function (evt) {
      drop.addEventListener(evt, function (e) { e.preventDefault(); drop.classList.add("is-over"); });
    });
    ["dragleave", "drop"].forEach(function (evt) {
      drop.addEventListener(evt, function (e) { e.preventDefault(); drop.classList.remove("is-over"); });
    });
    drop.addEventListener("drop", function (e) {
      if (e.dataTransfer && e.dataTransfer.files && canAssign) add(e.dataTransfer.files);
    });
  }

  /* ── Editor: allegati da rimuovere ──────────────────────── */
  function initRemoveToggles() {
    qsa("[data-nz-del]").forEach(function (cb) {
      var row = cb.closest(".nz-file");
      function upd() { if (row) row.classList.toggle("is-removed", cb.checked); }
      cb.addEventListener("change", upd);
      upd();
    });
  }

  /* ── Doppio invio: un clic solo per i pulsanti di salvataggio ── */
  function initSubmitOnce() {
    var form = qs("[data-nz-form]");
    if (!form) return;
    form.addEventListener("submit", function (e) {
      var btn = e.submitter;
      if (form.dataset.sent === "1") { e.preventDefault(); return; }
      form.dataset.sent = "1";
      if (btn) {
        // Disabilitato dopo l'invio: il valore del pulsante (save_and_publish) e' gia' nei dati.
        btn.setAttribute("aria-busy", "true");
        setTimeout(function () { btn.disabled = true; }, 0);
      }
    });
  }

  /* ── Pannello laterale ──────────────────────────────────── */
  function initDrawers() {
    qsa("[data-nz-drawer-open]").forEach(function (opener) {
      var id = opener.getAttribute("data-nz-drawer-open");
      var drawer = document.getElementById(id);
      var velo = document.getElementById(id + "-velo");
      if (!drawer || !velo) return;
      function close() { drawer.hidden = true; velo.hidden = true; opener.focus(); }
      opener.addEventListener("click", function () {
        drawer.hidden = false; velo.hidden = false;
        var first = qs("input, button", drawer);
        if (first) first.focus();
      });
      velo.addEventListener("click", close);
      qsa("[data-nz-drawer-close]", drawer).forEach(function (b) { b.addEventListener("click", close); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && !drawer.hidden) close();
      });
    });
  }

  /* ── Filtri: invio automatico quando cambia una tendina ─── */
  function initAutoSubmit() {
    qsa("[data-nz-autosubmit]").forEach(function (form) {
      qsa("[data-nz-autosubmit-change]", form).forEach(function (el) {
        el.addEventListener("change", function () {
          if (typeof form.requestSubmit === "function") form.requestSubmit();
          else form.submit();
        });
      });
    });
  }

  function init() {
    initViewer();
    initEditor();
    initRoles();
    initDrop();
    initRemoveToggles();
    initSubmitOnce();
    initDrawers();
    initAutoSubmit();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
