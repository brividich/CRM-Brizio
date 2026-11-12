/* Flusso in stile Power Automate: pannello laterale ([data-amp-open] con hx-get in #amp-drawer-body),
   campi della Ricorrenza per frequenza, contenuto dinamico «{oggetto}» nell'oggetto. */
(function () {
  function drawer() { return document.getElementById("amp-drawer"); }
  function open() { var d = drawer(); if (d) d.hidden = false; }
  function close() {
    var d = drawer();
    if (!d) return;
    d.hidden = true;
    var body = document.getElementById("amp-drawer-body");
    if (body) body.innerHTML = '<p class="amp-hint">Caricamento…</p>';
  }
  function syncFreq(root) {
    (root || document).querySelectorAll("[data-pa-freq]").forEach(function (select) {
      var card = select.closest(".pa-card-body");
      if (!card) return;
      card.querySelectorAll("[data-pa-show]").forEach(function (el) {
        var on = el.getAttribute("data-pa-show").split(" ").indexOf(select.value) !== -1;
        el.hidden = !on;
        el.querySelectorAll("input,select,textarea").forEach(function (f) { f.disabled = !on; });
      });
    });
  }
  document.addEventListener("click", function (ev) {
    var token = ev.target.closest("[data-pa-token]");
    if (token) {
      var field = token.closest(".pa-field").querySelector("[data-pa-subject]");
      if (field) {
        var t = token.getAttribute("data-pa-token");
        var s = field.selectionStart == null ? field.value.length : field.selectionStart;
        var e = field.selectionEnd == null ? s : field.selectionEnd;
        field.value = field.value.slice(0, s) + t + field.value.slice(e);
        field.focus();
        field.setSelectionRange(s + t.length, s + t.length);
      }
      return;
    }
    if (ev.target.closest("[data-amp-open]")) { open(); return; }
    if (ev.target.closest("[data-amp-close]") || ev.target === drawer()) close();
  });
  document.addEventListener("change", function (ev) {
    if (ev.target.matches("[data-pa-freq]")) syncFreq(ev.target.closest(".pa"));
  });
  document.addEventListener("keydown", function (ev) {
    var d = drawer();
    if (ev.key === "Escape" && d && !d.hidden) { ev.stopPropagation(); close(); }
  }, true);
  document.addEventListener("htmx:afterSwap", function (ev) {
    if (ev.detail && ev.detail.target && ev.detail.target.id === "amp-drawer-body") syncFreq(ev.detail.target);
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { syncFreq(); });
  else syncFreq();
})();
