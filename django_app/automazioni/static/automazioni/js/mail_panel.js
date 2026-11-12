/* Pannello laterale «Mail, destinatari e orario»: i pulsanti [data-amp-open] caricano il pannello con hx-get in #amp-drawer-body. */
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
  document.addEventListener("click", function (ev) {
    if (ev.target.closest("[data-amp-open]")) { open(); return; }
    if (ev.target.closest("[data-amp-close]") || ev.target === drawer()) close();
  });
  document.addEventListener("keydown", function (ev) {
    var d = drawer();
    if (ev.key === "Escape" && d && !d.hidden) { ev.stopPropagation(); close(); }
  }, true);
  document.addEventListener("htmx:afterSwap", function (ev) {
    if (ev.detail && ev.detail.target && ev.detail.target.id === "amp-drawer-body") {
      var first = ev.detail.target.querySelector("input:not([type=hidden]), textarea");
      if (first) first.focus();
    }
  });
})();
