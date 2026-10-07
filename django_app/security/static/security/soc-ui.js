/* Interazioni comuni del SOC. Niente framework: attributi data-* nel markup.

   Selezione multipla   form[data-bulk]: .sec-bulk-item, [data-bulk-all], [data-bulk-count], [data-bulk-go],
                        campi opzionali [data-show-for="azione1 azione2"] mostrati solo per quelle azioni.
   Anteprima a pannello [data-preview="/url/"] su righe o elementi: clic (fuori da link e caselle) apre il
                        pannello laterale; ← → scorrono le righe della stessa lista, Esc chiude. Nel pannello i
                        form [data-drawer-form] si inviano senza lasciare la pagina; [data-drawer-target] mette
                        la risposta in un riquadro del pannello (es. risposta dell'AI).
   Barra di stato live  [data-live-url] si ricarica ogni [data-live-every] secondi (pagina visibile).
   Sezioni vive         [data-autorefresh="120"] con id: rilette dalla pagina stessa ogni N secondi.
   Suggerimenti         [data-tip-id]: il pulsante [data-tip-close] li nasconde per sempre (localStorage).
   Testo inserito con textContent o HTML generato dal server stesso: mai HTML da input dell'utente. */
(function () {
  "use strict";

  function csrf() {
    var m = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = document.querySelector("input[name='csrfmiddlewaretoken']");
    return input ? input.value : "";
  }

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* storage bloccato: si vive senza */ }
    return null;
  }

  /* ---------- Selezione multipla ---------- */
  function initBulk(form) {
    var items = form.querySelectorAll(".sec-bulk-item");
    var all = form.querySelector("[data-bulk-all]");
    var count = form.querySelector("[data-bulk-count]");
    var go = form.querySelector("[data-bulk-go]");
    var action = form.querySelector("select[name='action']");
    var dependants = form.querySelectorAll("[data-show-for]");
    function refresh() {
      var n = form.querySelectorAll(".sec-bulk-item:checked").length;
      if (count) count.textContent = n;
      if (go) go.disabled = n === 0;
      form.classList.toggle("has-selection", n > 0);
      if (all) {
        all.checked = n > 0 && n === items.length;
        all.indeterminate = n > 0 && n < items.length;
      }
    }
    function sync() {
      var value = action ? action.value : "";
      dependants.forEach(function (el) {
        el.hidden = (" " + el.getAttribute("data-show-for") + " ").indexOf(" " + value + " ") === -1;
      });
    }
    if (all) {
      all.addEventListener("change", function () {
        // Solo le righe visibili: la ricerca della tabella nasconde le altre.
        items.forEach(function (box) { if (box.offsetParent !== null || !all.checked) box.checked = all.checked; });
        refresh();
      });
    }
    items.forEach(function (box) { box.addEventListener("change", refresh); });
    if (action) action.addEventListener("change", sync);
    // Maiusc+clic seleziona l'intervallo, come nei client di posta.
    var last = null;
    items.forEach(function (box, index) {
      box.addEventListener("click", function (ev) {
        if (ev.shiftKey && last !== null) {
          var from = Math.min(last, index), to = Math.max(last, index);
          for (var i = from; i <= to; i++) items[i].checked = box.checked;
          refresh();
        }
        last = index;
      });
    });
    sync();
    refresh();
  }

  /* ---------- Pannello di anteprima ---------- */
  var drawer, drawerBody, drawerTitle, current = null, changed = false;

  function buildDrawer() {
    drawer = document.createElement("aside");
    drawer.className = "soc-drawer";
    drawer.setAttribute("aria-hidden", "true");
    drawer.setAttribute("role", "dialog");
    drawer.setAttribute("aria-label", "Anteprima");
    drawer.innerHTML =
      '<div class="soc-drawer-backdrop" data-drawer-close></div>' +
      '<div class="soc-drawer-panel">' +
      '  <div class="soc-drawer-bar">' +
      '    <button type="button" class="soc-drawer-nav" data-drawer-prev aria-label="Precedente (freccia sinistra)">&#8592;</button>' +
      '    <button type="button" class="soc-drawer-nav" data-drawer-next aria-label="Successivo (freccia destra)">&#8594;</button>' +
      '    <span class="soc-drawer-pos"></span>' +
      '    <button type="button" class="soc-drawer-close" data-drawer-close aria-label="Chiudi (Esc)">&#215;</button>' +
      '  </div>' +
      '  <div class="soc-drawer-body" tabindex="-1"></div>' +
      '</div>';
    // Dentro .soc-module: badge, pulsanti e testi del SOC hanno gli stili scoped lì.
    (document.querySelector(".soc-module") || document.body).appendChild(drawer);
    drawerBody = drawer.querySelector(".soc-drawer-body");
    drawerTitle = drawer.querySelector(".soc-drawer-pos");
    drawer.addEventListener("click", function (ev) {
      if (ev.target.closest("[data-drawer-close]")) closeDrawer();
      else if (ev.target.closest("[data-drawer-prev]")) step(-1);
      else if (ev.target.closest("[data-drawer-next]")) step(1);
    });
    drawerBody.addEventListener("submit", onDrawerSubmit);
  }

  function siblings(el) {
    var scope = el.closest("[data-preview-scope]") || el.closest("tbody") || el.parentElement;
    return Array.prototype.filter.call(scope.querySelectorAll("[data-preview]"), function (row) {
      return row.offsetParent !== null;
    });
  }

  function load(url) {
    drawerBody.innerHTML = '<p class="soc-drawer-loading">Caricamento…</p>';
    return fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function (html) { drawerBody.innerHTML = html; drawerBody.focus(); })
      .catch(function () { drawerBody.innerHTML = '<p class="sec-action-result sec-error">Anteprima non disponibile. Apri la scheda completa.</p>'; });
  }

  function openFor(el) {
    if (!drawer) buildDrawer();
    if (current) current.classList.remove("is-previewed");
    current = el;
    el.classList.add("is-previewed");
    var list = siblings(el);
    var index = list.indexOf(el);
    drawerTitle.textContent = list.length > 1 ? (index + 1) + " di " + list.length : "";
    drawer.querySelector("[data-drawer-prev]").disabled = index <= 0;
    drawer.querySelector("[data-drawer-next]").disabled = index < 0 || index >= list.length - 1;
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    document.documentElement.classList.add("soc-drawer-open");
    load(el.getAttribute("data-preview"));
  }

  function step(delta) {
    if (!current) return;
    var list = siblings(current);
    var next = list[list.indexOf(current) + delta];
    if (next) { openFor(next); next.scrollIntoView({ block: "nearest" }); }
  }

  function closeDrawer() {
    if (!drawer) return;
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    document.documentElement.classList.remove("soc-drawer-open");
    if (current) { current.classList.remove("is-previewed"); current.focus && current.focus(); }
    current = null;
    // Un'azione fatta nel pannello cambia la lista: la si rilegge.
    if (changed) window.location.reload();
  }

  function onDrawerSubmit(ev) {
    var form = ev.target.closest("form[data-drawer-form]");
    if (!form) return;
    ev.preventDefault();
    ev.stopPropagation();
    var targetSel = form.getAttribute("data-drawer-target");
    var target = targetSel ? drawerBody.querySelector(targetSel) : null;
    var button = form.querySelector("button[type='submit']");
    if (button) { button.disabled = true; if (button.dataset.busyLabel) { button.dataset.label = button.textContent; button.textContent = button.dataset.busyLabel; } }
    fetch(form.action, {
      method: "POST", body: new FormData(form), credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "HX-Request": "true", "X-Requested-With": "XMLHttpRequest" }
    })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function (html) {
        if (target) { target.innerHTML = html; if (button) { button.disabled = false; if (button.dataset.label) button.textContent = button.dataset.label; } return; }
        changed = true;
        return load(current ? current.getAttribute("data-preview") : form.getAttribute("data-reload"));
      })
      .catch(function () {
        var box = target || drawerBody;
        box.insertAdjacentHTML("afterbegin", '<p class="sec-action-result sec-error">Operazione non riuscita. Riprova dalla scheda completa.</p>');
        if (button) button.disabled = false;
      });
  }

  document.addEventListener("click", function (ev) {
    var row = ev.target.closest("[data-preview]");
    if (!row || ev.target.closest("a, button, input, select, label, textarea")) return;
    if (ev.ctrlKey || ev.metaKey) return;
    ev.preventDefault();
    openFor(row);
  });
  document.addEventListener("keydown", function (ev) {
    if (drawer && drawer.classList.contains("is-open")) {
      if (ev.target.closest && ev.target.closest("input, textarea, select")) return;
      if (ev.key === "Escape") closeDrawer();
      else if (ev.key === "ArrowLeft") step(-1);
      else if (ev.key === "ArrowRight") step(1);
      return;
    }
    // Invio su una riga con il focus apre l'anteprima.
    if (ev.key === "Enter" && ev.target.matches && ev.target.matches("[data-preview]")) openFor(ev.target);
  });

  /* ---------- Barra di stato live e sezioni vive ---------- */
  function poll(el, url, seconds, swap) {
    setInterval(function () {
      if (document.hidden) return;
      if (drawer && drawer.classList.contains("is-open")) return;
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
        if (fresh) { node.innerHTML = fresh.innerHTML; initWithin(node); }
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

  function initWithin(root) {
    root.querySelectorAll("form[data-bulk]").forEach(initBulk);
    root.querySelectorAll("[data-preview]").forEach(function (row) {
      if (!row.hasAttribute("tabindex")) row.setAttribute("tabindex", "0");
      row.classList.add("has-preview");
    });
  }

  function init() {
    initWithin(document);
    initLive();
    initTips();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
