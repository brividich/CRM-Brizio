/* NOVICROM HUB — helper riusabile per Chart.js (stile portale).
 *
 * Richiede che la pagina abbia gia' caricato Chart.js (core/vendor/chartjs).
 * Espone window.NHUB.chart / NHUB.barChart / NHUB.lineChart con default di brand
 * (palette navy/cyan/orange, responsive) e gestione del ciclo di vita: ridisegnare
 * sullo stesso <canvas> distrugge l'istanza precedente (no leak su re-render).
 */
window.NHUB = window.NHUB || {};
(function () {
  "use strict";

  var BRAND = ["#1f87cd", "#0c2545", "#ff6b00", "#2f9e6f", "#dc2626", "#d97706", "#64748b"];
  var instances = new WeakMap();

  function baseOptions(extra) {
    var o = {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
    };
    if (extra) {
      Object.keys(extra).forEach(function (k) { o[k] = extra[k]; });
    }
    return o;
  }

  // Generico: distrugge l'eventuale chart precedente sul canvas e ne crea uno nuovo.
  window.NHUB.chart = function (canvas, config) {
    if (!canvas || typeof Chart === "undefined") return null;
    var prev = instances.get(canvas);
    if (prev) { try { prev.destroy(); } catch (e) {} }
    try {
      var c = new Chart(canvas, config);
      instances.set(canvas, c);
      return c;
    } catch (e) {
      return null;
    }
  };

  window.NHUB.barChart = function (canvas, opts) {
    opts = opts || {};
    return window.NHUB.chart(canvas, {
      type: "bar",
      data: {
        labels: opts.labels || [],
        datasets: [{
          label: opts.label || "",
          data: opts.values || [],
          backgroundColor: opts.color || BRAND[0],
          borderRadius: 4,
          maxBarThickness: 48,
        }],
      },
      options: baseOptions({ plugins: { legend: { display: !!opts.label } } }),
    });
  };

  window.NHUB.lineChart = function (canvas, opts) {
    opts = opts || {};
    return window.NHUB.chart(canvas, {
      type: "line",
      data: {
        labels: opts.labels || [],
        datasets: [{
          label: opts.label || "",
          data: opts.values || [],
          borderColor: opts.color || BRAND[0],
          backgroundColor: "rgba(31,135,205,.12)",
          fill: true,
          tension: 0.3,
          pointRadius: 3,
        }],
      },
      options: baseOptions({ plugins: { legend: { display: !!opts.label } } }),
    });
  };

  window.NHUB.BRAND_COLORS = BRAND;
})();
