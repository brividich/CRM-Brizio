/* Pannelli laterali della Reception: [data-apri="#id"] apre, [data-chiudi] o Esc chiude. */
(function () {
  "use strict";
  var velo = null;
  function chiudi() {
    document.querySelectorAll(".rc-pannello.on").forEach(function (p) { p.classList.remove("on"); p.setAttribute("aria-hidden", "true"); });
    if (velo) { velo.classList.remove("on"); }
    document.body.classList.remove("rc-bloccato");
  }
  function apri(sel) {
    var p = document.querySelector(sel);
    if (!p) { return; }
    chiudi();
    if (!velo) {
      velo = document.createElement("div");
      velo.className = "rc-velo";
      velo.addEventListener("click", chiudi);
      document.body.appendChild(velo);
    }
    velo.classList.add("on");
    p.classList.add("on");
    p.setAttribute("aria-hidden", "false");
    document.body.classList.add("rc-bloccato");
    var primo = p.querySelector("input:not([type=hidden]), select, textarea");
    if (primo) { setTimeout(function () { primo.focus(); }, 60); }
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest("[data-apri]");
    if (a) { e.preventDefault(); apri(a.getAttribute("data-apri")); return; }
    if (e.target.closest("[data-chiudi]")) { e.preventDefault(); chiudi(); }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { chiudi(); } });
  var aperto = document.querySelector(".rc-pannello[data-aperto]");
  if (aperto) { apri("#" + aperto.id); }
})();
