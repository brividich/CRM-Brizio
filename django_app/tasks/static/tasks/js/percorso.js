/* Percorso guidato — rail + evidenziazione tappa corrente + completamento.
   Progressive enhancement: senza JS resta una pagina a sezioni verticali.
   Attiva su ogni contenitore con [data-kp-root]. */
(function () {
  "use strict";

  function textFilled(el) {
    if (el.type === "checkbox" || el.type === "radio") return el.checked;
    if (el.type === "hidden") return false;
    return String(el.value || "").trim() !== "";
  }

  function stationComplete(station) {
    var required = station.querySelectorAll(
      "input[required],select[required],textarea[required],[data-kp-required]"
    );
    if (required.length) {
      return Array.prototype.every.call(required, textFilled);
    }
    // Nessun campo obbligatorio esplicito: "compilata" se almeno un campo ha valore.
    var any = station.querySelectorAll("input,select,textarea");
    return Array.prototype.some.call(any, textFilled);
  }

  function initPercorso(root) {
    var stations = Array.prototype.slice.call(root.querySelectorAll(".kp-station"));
    if (!stations.length) return;

    var nodesWrap = root.querySelector(".kp-rail-nodes");
    var progress = root.querySelector(".kp-progress-count");
    var nodes = [];

    stations.forEach(function (st, i) {
      st.setAttribute("data-kp-index", i);
      if (!st.id) st.id = "kp-st-" + i;
      if (nodesWrap) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "kp-node";
        var title = st.getAttribute("data-title") || "Tappa " + (i + 1);
        btn.innerHTML =
          '<span class="kp-dot">' + (i + 1) + '</span><span class="kp-label"></span>';
        btn.querySelector(".kp-label").textContent = title;
        btn.addEventListener("click", function () {
          document.getElementById(st.id).scrollIntoView({ behavior: "smooth", block: "start" });
        });
        nodesWrap.appendChild(btn);
        nodes.push(btn);
      }
    });

    function refresh() {
      var done = 0;
      stations.forEach(function (st, i) {
        var ok = stationComplete(st);
        st.classList.toggle("is-done", ok);
        if (nodes[i]) nodes[i].classList.toggle("is-done", ok);
        if (ok) done++;
      });
      if (progress) progress.textContent = done + "/" + stations.length;
    }

    root.addEventListener("input", refresh);
    root.addEventListener("change", refresh);

    if ("IntersectionObserver" in window && nodes.length) {
      var io = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (e) {
            if (!e.isIntersecting) return;
            var idx = +e.target.getAttribute("data-kp-index");
            stations.forEach(function (s) { s.classList.remove("is-current"); });
            e.target.classList.add("is-current");
            nodes.forEach(function (n, i) { n.classList.toggle("is-active", i === idx); });
          });
        },
        { rootMargin: "-45% 0px -50% 0px", threshold: 0 }
      );
      stations.forEach(function (st) { io.observe(st); });
    }

    refresh();
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.slice
      .call(document.querySelectorAll("[data-kp-root]"))
      .forEach(initPercorso);
  });
})();
