/* Interazioni comuni del SOC. Niente framework: attributi data-* nel markup.

   Selezione multipla e pannello di anteprima (form[data-bulk], [data-preview]) stanno nel codice comune
                        core/js/hub-bulk-pannello.js, caricato da core/base.html per tutto il portale.
   Barra di stato live  [data-live-url] si ricarica ogni [data-live-every] secondi (pagina visibile).
   Sezioni vive         [data-autorefresh="120"] con id: rilette dalla pagina stessa ogni N secondi.
   Suggerimenti         [data-tip-id]: il pulsante [data-tip-close] li nasconde per sempre (localStorage).
   Testo inserito con textContent o HTML generato dal server stesso: mai HTML da input dell'utente. */
(function () {
  "use strict";
  // Caricato anche da pagine fuori dal SOC (pannello CVE negli Asset): una volta sola.
  if (window.__socUi) return;
  window.__socUi = true;

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* storage bloccato: si vive senza */ }
    return null;
  }

  /* ---------- Barra di stato live e sezioni vive ---------- */
  function poll(el, url, seconds, swap) {
    setInterval(function () {
      if (document.hidden) return;
      if (window.HubBulkPannello && window.HubBulkPannello.isOpen()) return;
      fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(); return r.text(); })
        .then(function (html) { swap(el, html); })
        .catch(function () { el.classList.add("is-stale"); });
    }, Math.max(seconds, 30) * 1000);
  }

  function initLive() {
    document.querySelectorAll("[data-live-url]").forEach(function (el) {
      poll(el, el.getAttribute("data-live-url"), parseInt(el.getAttribute("data-live-every") || "60", 10), function (node, html) {
        node.innerHTML = html;
        node.classList.remove("is-stale");
      });
    });
    document.querySelectorAll("[data-autorefresh][id]").forEach(function (el) {
      // Mai mentre l'utente sta scrivendo o ha selezionato righe.
      poll(el, window.location.href, parseInt(el.getAttribute("data-autorefresh"), 10), function (node, html) {
        if (node.querySelector(".sec-bulk-item:checked") || node.contains(document.activeElement) && document.activeElement.matches("input, textarea, select")) return;
        var doc = new DOMParser().parseFromString(html, "text/html");
        var fresh = doc.getElementById(node.id);
        if (fresh) { node.innerHTML = fresh.innerHTML; if (window.HubBulkPannello) window.HubBulkPannello.initWithin(node); }
      });
    });
  }

  /* ---------- Suggerimenti chiudibili ---------- */
  function initTips() {
    document.querySelectorAll("[data-tip-id]").forEach(function (tip) {
      var key = "soc-tip-" + tip.getAttribute("data-tip-id");
      if (store(key) === "1") { tip.hidden = true; return; }
      var close = tip.querySelector("[data-tip-close]");
      if (close) close.addEventListener("click", function () { tip.hidden = true; store(key, "1"); });
    });
  }

  function init() {
    initLive();
    initTips();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
