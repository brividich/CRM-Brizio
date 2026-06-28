/* NOVICROM HUB — tour guidati (driver.js, lazy).
 *
 * Riusabile e dichiarativo: una pagina definisce i passi mettendo su elementi
 * `data-tour-step="N"` con `data-tour-title` / `data-tour-text`, e un pulsante
 * `data-tour-start` (opz. `data-tour-key="..."` per ricordare "già visto", e
 * `data-tour-auto` per partire una volta sola alla prima visita).
 *
 * driver.js viene caricato in modo LAZY solo quando un tour parte: zero costo sulle
 * pagine senza tour. URL degli asset in window.NHUB_TOUR (impostata in base.html).
 */
(function () {
  "use strict";

  function ensureDriver(cb) {
    if (window.driver && window.driver.js && window.driver.js.driver) return cb();
    var cfg = window.NHUB_TOUR || {};
    if (!cfg.js) return;
    if (cfg.css && !document.getElementById("nhub-driver-css")) {
      var l = document.createElement("link");
      l.id = "nhub-driver-css";
      l.rel = "stylesheet";
      l.href = cfg.css;
      document.head.appendChild(l);
    }
    if (document.getElementById("nhub-driver-js")) {
      // gia' in caricamento: riprova a breve
      setTimeout(function () { ensureDriver(cb); }, 150);
      return;
    }
    var s = document.createElement("script");
    s.id = "nhub-driver-js";
    s.src = cfg.js;
    s.onload = cb;
    s.onerror = function () {};
    document.body.appendChild(s);
  }

  function collectSteps() {
    var els = Array.prototype.slice.call(document.querySelectorAll("[data-tour-step]"));
    els.sort(function (a, b) {
      return (parseInt(a.dataset.tourStep, 10) || 0) - (parseInt(b.dataset.tourStep, 10) || 0);
    });
    return els
      .filter(function (el) { return el.offsetParent !== null; }) // solo elementi visibili
      .map(function (el) {
        return {
          element: el,
          popover: {
            title: el.dataset.tourTitle || "",
            description: el.dataset.tourText || "",
          },
        };
      });
  }

  function startTour(trigger) {
    ensureDriver(function () {
      var factory = window.driver && window.driver.js && window.driver.js.driver;
      if (!factory) return;
      var steps = collectSteps();
      if (!steps.length) return;
      var d = factory({
        showProgress: true,
        allowClose: true,
        nextBtnText: "Avanti",
        prevBtnText: "Indietro",
        doneBtnText: "Fine",
        progressText: "{{current}} / {{total}}",
        steps: steps,
        onDestroyed: function () {
          if (trigger && trigger.dataset.tourKey) {
            try { localStorage.setItem("nhub_tour_" + trigger.dataset.tourKey, "1"); } catch (e) {}
          }
        },
      });
      d.drive();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var triggers = document.querySelectorAll("[data-tour-start]");
    if (!triggers.length) return;
    Array.prototype.forEach.call(triggers, function (t) {
      t.addEventListener("click", function (e) { e.preventDefault(); startTour(t); });
      if (t.hasAttribute("data-tour-auto") && t.dataset.tourKey) {
        var seen = false;
        try { seen = !!localStorage.getItem("nhub_tour_" + t.dataset.tourKey); } catch (e) {}
        if (!seen) setTimeout(function () { startTour(t); }, 600);
      }
    });
  });
})();
