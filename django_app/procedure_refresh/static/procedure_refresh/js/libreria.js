/* CN-SGI · libreria: pannello laterale della scheda documento, schede interne, tasto «/».
   I link con data-cn-doc aprono la scheda nel pannello (HTMX); senza JS vanno alla pagina. */
(function () {
  "use strict";
  var drawer = document.getElementById("cn-drawer");
  var scrim = document.getElementById("cn-scrim");
  var ultimoFocus = null;

  function apri(url) {
    if (!drawer || !window.htmx) { window.location.href = url; return; }
    ultimoFocus = document.activeElement;
    drawer.innerHTML = '<p class="cn-note" style="margin:18px">Caricamento…</p>';
    drawer.hidden = false;
    scrim.hidden = false;
    document.body.style.overflow = "hidden";
    window.htmx.ajax("GET", url, { target: "#cn-drawer", swap: "innerHTML" });
  }

  function chiudi() {
    if (!drawer || drawer.hidden) return;
    drawer.hidden = true;
    scrim.hidden = true;
    drawer.innerHTML = "";
    document.body.style.overflow = "";
    if (ultimoFocus && ultimoFocus.focus) ultimoFocus.focus();
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-cn-doc]");
    if (link && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) {
      e.preventDefault();
      apri(link.getAttribute("href"));
      return;
    }
    if (e.target.closest("[data-cn-close]")) { chiudi(); return; }
    var tab = e.target.closest("[data-cn-tab]");
    if (tab) {
      var box = tab.closest("[data-cn-scheda]");
      box.querySelectorAll("[data-cn-tab]").forEach(function (b) { b.setAttribute("aria-selected", b === tab ? "true" : "false"); });
      box.querySelectorAll("[data-cn-pane]").forEach(function (p) { p.hidden = p.getAttribute("data-cn-pane") !== tab.getAttribute("data-cn-tab"); });
    }
  });

  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target === drawer) {
      var x = drawer.querySelector("[data-cn-close]");
      if (x) x.focus();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { chiudi(); return; }
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(tag) && !document.activeElement.isContentEditable) {
      var q = document.getElementById("cn-q");
      if (q) { e.preventDefault(); q.focus(); }
    }
  });

  /* Gestione «Chi vede cosa»: sezioni e documenti seguono lo scaffale scelto. */
  var selScaf = document.getElementById("cn-v-scaffale");
  if (selScaf) {
    var filtra = function () {
      var s = selScaf.value;
      ["cn-v-sezione", "cn-v-documento"].forEach(function (id) {
        var sel = document.getElementById(id);
        if (!sel) return;
        Array.prototype.forEach.call(sel.options, function (o) {
          if (!o.value) return;
          var ok = o.getAttribute("data-scaffale") === s;
          o.hidden = !ok; o.disabled = !ok;
          if (!ok && o.selected) sel.value = "";
        });
      });
    };
    selScaf.addEventListener("change", filtra);
    filtra();
    var chi = document.querySelectorAll("input[name=chi]");
    var ruoli = document.getElementById("cn-v-ruoli");
    var aggiornaChi = function () {
      var sel = document.querySelector("input[name=chi]:checked");
      if (ruoli) ruoli.hidden = sel && sel.value === "nessuno";
    };
    chi.forEach(function (r) { r.addEventListener("change", aggiornaChi); });
    aggiornaChi();
  }
})();

/* Filtri della ricerca: si applicano appena cambiano. */
document.addEventListener("change", function (e) {
  if (e.target.matches && e.target.matches("[data-cn-autosubmit]") && e.target.form) e.target.form.submit();
});
