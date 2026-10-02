/* Grafici SOC interattivi: tooltip al passaggio (o al focus da tastiera) e clic per selezionare.
   Markup: un contenitore .soc-chart con elementi [data-tip-title] e [data-tip] ("riga|riga|...").
   [data-href] rende l'elemento selezionabile (clic o Invio). Testo inserito con textContent: niente HTML. */
(function () {
  function tooltipFor(chart) {
    var tip = chart.querySelector(".soc-tip");
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "soc-tip";
      tip.setAttribute("role", "tooltip");
      tip.hidden = true;
      chart.appendChild(tip);
    }
    return tip;
  }

  function fill(tip, el) {
    tip.textContent = "";
    var title = el.getAttribute("data-tip-title");
    if (title) {
      var strong = document.createElement("strong");
      strong.textContent = title;
      tip.appendChild(strong);
    }
    (el.getAttribute("data-tip") || "").split("|").forEach(function (line) {
      if (!line) { return; }
      var row = document.createElement("span");
      var parts = line.split("::");
      if (parts.length === 2) {
        var dot = document.createElement("i");
        dot.style.background = parts[0];
        row.appendChild(dot);
        line = parts[1];
      }
      row.appendChild(document.createTextNode(line));
      tip.appendChild(row);
    });
    if (el.hasAttribute("data-href")) {
      var hint = document.createElement("em");
      hint.textContent = el.getAttribute("data-href-label") || "Clic per selezionare";
      tip.appendChild(hint);
    }
  }

  function place(chart, tip, x, y) {
    var box = chart.getBoundingClientRect();
    var left = x - box.left + 14;
    var top = y - box.top + 14;
    tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    if (left + w > box.width) { left = Math.max(4, x - box.left - w - 14); }
    if (top + h > box.height + 40) { top = Math.max(4, y - box.top - h - 10); }
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }

  function show(el, x, y) {
    var chart = el.closest(".soc-chart");
    if (!chart) { return; }
    var tip = tooltipFor(chart);
    fill(tip, el);
    chart.querySelectorAll(".is-hover").forEach(function (other) { other.classList.remove("is-hover"); });
    el.classList.add("is-hover");
    if (x === undefined) {
      var r = el.getBoundingClientRect();
      x = r.left + r.width / 2;
      y = r.top;
    }
    place(chart, tip, x, y);
  }

  function hide(el) {
    var chart = el.closest(".soc-chart");
    if (!chart) { return; }
    el.classList.remove("is-hover");
    var tip = chart.querySelector(".soc-tip");
    if (tip) { tip.hidden = true; }
  }

  function target(event) {
    return event.target && event.target.closest ? event.target.closest(".soc-chart [data-tip], .soc-chart [data-tip-title]") : null;
  }

  document.addEventListener("mousemove", function (event) {
    var el = target(event);
    if (el) { show(el, event.clientX, event.clientY); }
  });
  document.addEventListener("mouseout", function (event) {
    var el = target(event);
    if (el && !el.contains(event.relatedTarget)) { hide(el); }
  });
  document.addEventListener("focusin", function (event) {
    var el = target(event);
    if (el) { show(el); }
  });
  document.addEventListener("focusout", function (event) {
    var el = target(event);
    if (el) { hide(el); }
  });
  function go(el) {
    var href = el && el.getAttribute("data-href");
    if (href) { window.location.href = href; }
  }
  document.addEventListener("click", function (event) {
    var el = target(event);
    if (el && el.hasAttribute("data-href")) { event.preventDefault(); go(el); }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") { return; }
    var el = target(event);
    if (el && el.hasAttribute("data-href")) { event.preventDefault(); go(el); }
  });
})();
