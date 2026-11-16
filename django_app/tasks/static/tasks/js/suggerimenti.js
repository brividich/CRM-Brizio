/* Campi ricercabili: ogni <input data-suggest="campo"> propone i valori già
   scritti in quel campo (endpoint tasks:identity_suggest, solo il proprio ambito).
   Il campo resta testo libero: il suggerimento è un aiuto, non un vincolo.
   L'URL dell'endpoint sta in data-suggest-url sul <form> (o su un antenato). */
(function () {
  "use strict";

  function attach(input, seq) {
    var host = input.closest("[data-suggest-url]");
    if (!host) return;
    var url = host.getAttribute("data-suggest-url");
    var field = input.getAttribute("data-suggest");
    var list = document.createElement("datalist");
    list.id = "sugg-" + field + "-" + seq;
    input.after(list);
    input.setAttribute("list", list.id);
    input.setAttribute("autocomplete", "off");
    var last = null;
    var req = 0;

    function load() {
      var q = String(input.value || "").trim();
      if (q === last) return;
      last = q;
      var mine = ++req;
      fetch(url + "?field=" + encodeURIComponent(field) + "&q=" + encodeURIComponent(q), {
        headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin"
      })
        .then(function (r) { return r.ok ? r.json() : { values: [] }; })
        .then(function (data) {
          if (mine !== req) return;
          list.replaceChildren();
          (data.values || []).forEach(function (v) {
            if (v === input.value) return;
            var o = document.createElement("option");
            o.value = v;
            list.appendChild(o);
          });
        })
        .catch(function () { /* accessorio: il campo resta libero */ });
    }

    var timer = null;
    input.addEventListener("focus", load);
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(load, 150);
    });
  }

  function init(root) {
    var n = 0;
    (root || document).querySelectorAll("input[data-suggest]:not([data-suggest-ok])").forEach(function (input) {
      input.setAttribute("data-suggest-ok", "1");
      attach(input, ++n + "-" + Math.random().toString(36).slice(2, 7));
    });
  }

  window.portalSuggerimenti = init;
  document.addEventListener("DOMContentLoaded", function () { init(document); });
})();
