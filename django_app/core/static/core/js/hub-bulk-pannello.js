/* Selezione multipla e pannello laterale di anteprima, per tutto il portale (nati nel SOC).
   Niente framework: attributi data-* nel markup. Caricato da core/base.html.

   Selezione multipla   form[data-bulk]: .sec-bulk-item, [data-bulk-all], [data-bulk-count] (+ [data-bulk-label] singolare/plurale),
                        [data-bulk-go] (anche più pulsanti), [data-bulk-clear],
                        campi opzionali [data-show-for="azione1 azione2"] mostrati solo per quelle azioni.
                        Le caselle possono stare fuori dal form: si collegano con form="<id del form>".
                        Liste miste [data-bulk-kinds]: righe e opzioni con data-kind, un tipo alla volta, il form
                        va a data-action-<tipo>; i campi nascosti sono anche disabilitati (non si spediscono).
   Anteprima a pannello [data-preview="/url/"] su righe o elementi: clic (fuori da link e caselle) apre il
                        pannello laterale; un bottone/link con data-preview lo apre lui stesso (Ctrl+clic su un
                        link apre invece la pagina). ← → scorrono le righe della stessa lista, Esc chiude.
                        Nel pannello i link [data-drawer-load] cambiano il contenuto senza chiuderlo; i form
                        [data-drawer-form] si inviano senza lasciare la pagina; [data-drawer-target] mette la
                        risposta in un riquadro del pannello; [data-drawer-replace] sostituisce tutto il pannello.
                        Il pannello si appende al contenitore [data-drawer-host] o .soc-module più vicino alla riga
                        (gli stili del modulo valgono anche lì dentro), altrimenti a <body>.
   API                  window.HubBulkPannello.initWithin(root) dopo aver sostituito un pezzo di pagina;
                        window.HubBulkPannello.isOpen() dice se il pannello è aperto.
   Testo inserito con textContent o HTML generato dal server stesso: mai HTML da input dell'utente. */
(function () {
  "use strict";
  if (window.HubBulkPannello) return;

  function csrf() {
    var m = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var input = document.querySelector("input[name='csrfmiddlewaretoken']");
    return input ? input.value : "";
  }

  /* ---------- Selezione multipla ---------- */
  // Elenco completo delle caselle di un form, anche quelle fuori dal form (righe che hanno già un loro
  // form dentro) collegate con form="<id del form>". Riletto a ogni uso: le righe sostituite da HTMX
  // (es. «Leggi ora») portano caselle nuove.
  function bulkItems(form) {
    var items = Array.prototype.slice.call(form.querySelectorAll(".sec-bulk-item"));
    if (form.id) {
      Array.prototype.forEach.call(document.querySelectorAll('.sec-bulk-item[form="' + form.id + '"]'), function (box) {
        if (items.indexOf(box) === -1) items.push(box);
      });
    }
    return items;
  }

  function initBulk(form) {
    if (form.__hubBulk) { form.__hubBulk.refresh(); return; }
    var all = form.querySelector("[data-bulk-all]") || (form.id ? document.querySelector('[data-bulk-all][form="' + form.id + '"]') : null);
    function items() { return bulkItems(form); }
    function checked() { return items().filter(function (box) { return box.checked; }); }
    var count = form.querySelector("[data-bulk-count]");
    // [data-bulk-label data-one="selezionata" data-many="selezionate"]: singolare o plurale accanto al numero.
    var label = form.querySelector("[data-bulk-label]");
    var gos = form.querySelectorAll("[data-bulk-go]");
    var action = form.querySelector("select[name='action']");
    var dependants = form.querySelectorAll("[data-show-for]");
    var clear = form.querySelector("[data-bulk-clear]");
    // Liste miste (alert, ticket, incidenti): si seleziona un tipo alla volta, le azioni e l'indirizzo
    // del form seguono il tipo scelto ([data-bulk-kinds], righe con data-kind, data-action-<tipo>).
    var kinds = form.hasAttribute("data-bulk-kinds");
    var kindLabel = form.querySelector("[data-bulk-kind-label]");
    var KIND_NAMES = { alert: "alert", ticket: "ticket", incident: "incidenti" };
    function kindOf() {
      var first = checked()[0];
      return first ? (first.getAttribute("data-kind") || "") : "";
    }
    function selectable(box, kind) { return !kind || (box.getAttribute("data-kind") || "") === kind; }
    function syncKind() {
      if (!kinds) return;
      var kind = kindOf();
      form.setAttribute("data-kind", kind);
      items().forEach(function (box) { box.disabled = !selectable(box, kind); });
      var url = kind ? form.getAttribute("data-action-" + kind) : "";
      if (url) form.setAttribute("action", url);
      if (kindLabel) kindLabel.textContent = kind ? (KIND_NAMES[kind] || kind) + " selezionat" + (checked().length === 1 ? "o" : "i") : "selezionati";
      if (action) {
        var visible = null;
        action.querySelectorAll("option[data-kind]").forEach(function (opt) {
          var ok = !kind || opt.getAttribute("data-kind") === kind;
          opt.hidden = !ok; opt.disabled = !ok;
          if (ok && !visible) visible = opt;
        });
        if (action.selectedOptions[0] && action.selectedOptions[0].disabled && visible) action.value = visible.value;
      }
    }
    function refresh() {
      var n = checked().length;
      if (count) count.textContent = n;
      if (label) label.textContent = n === 1 ? label.getAttribute("data-one") : label.getAttribute("data-many");
      gos.forEach(function (go) { go.disabled = n === 0; });
      form.classList.toggle("has-selection", n > 0);
      syncKind();
      if (all) {
        var pool = items().filter(function (box) { return !box.disabled; });
        all.checked = n > 0 && n === pool.length;
        all.indeterminate = n > 0 && n < pool.length;
      }
      sync();
    }
    function sync() {
      var value = action ? action.value : "";
      var kind = kinds ? form.getAttribute("data-kind") || "" : "";
      dependants.forEach(function (el) {
        var forKind = el.getAttribute("data-kind");
        var off = (" " + el.getAttribute("data-show-for") + " ").indexOf(" " + value + " ") === -1 || (forKind && kind && forKind !== kind);
        el.hidden = off;
        // Un campo nascosto non va spedito: due «status» o due «reason» nello stesso form si pesterebbero.
        if (el.matches("input, select, textarea")) el.disabled = off;
        else el.querySelectorAll("input, select, textarea").forEach(function (f) { f.disabled = off; });
      });
    }
    if (all) {
      all.addEventListener("change", function () {
        // Solo le righe visibili e selezionabili: la ricerca della tabella nasconde le altre, il tipo scelto blocca gli altri tipi.
        var kind = kinds ? kindOf() : "";
        items().forEach(function (box) { if (!all.checked) box.checked = false; else if (box.offsetParent !== null && selectable(box, kind)) box.checked = true; });
        refresh();
      });
    }
    if (clear) clear.addEventListener("click", function () { items().forEach(function (box) { box.checked = false; }); refresh(); });
    if (action) action.addEventListener("change", sync);
    // Maiusc+clic seleziona l'intervallo, come nei client di posta.
    var last = null;
    function onItemClick(box, ev) {
      var list = items();
      var index = list.indexOf(box);
      if (ev.shiftKey && last && list.indexOf(last) !== -1 && index !== -1) {
        var a = list.indexOf(last), from = Math.min(a, index), to = Math.max(a, index);
        for (var i = from; i <= to; i++) if (!list[i].disabled) list[i].checked = box.checked;
        refresh();
      }
      last = box;
    }
    form.__hubBulk = { refresh: refresh, click: onItemClick };
    sync();
    refresh();
  }

  // Caselle: ascolto unico sul documento, la casella trova il suo form da sola (anche con form="...").
  function bulkOf(box) {
    if (!box || !box.matches || !box.matches(".sec-bulk-item")) return null;
    var form = box.form || box.closest("form[data-bulk]");
    return form && form.__hubBulk ? form.__hubBulk : null;
  }
  document.addEventListener("change", function (ev) { var b = bulkOf(ev.target); if (b) b.refresh(); });
  document.addEventListener("click", function (ev) { var b = bulkOf(ev.target); if (b) b.click(ev.target, ev); });

  /* ---------- Pannello di anteprima ---------- */
  var drawer, drawerBody, drawerTitle, current = null, changed = false;

  function hostFor(el) {
    var sel = "[data-drawer-host], .soc-module";
    return (el && el.closest && el.closest(sel)) || document.querySelector(sel) || document.body;
  }

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
    drawerBody = drawer.querySelector(".soc-drawer-body");
    drawerTitle = drawer.querySelector(".soc-drawer-pos");
    drawer.addEventListener("click", function (ev) {
      if (ev.target.closest("[data-drawer-close]")) closeDrawer();
      else if (ev.target.closest("[data-drawer-prev]")) step(-1);
      else if (ev.target.closest("[data-drawer-next]")) step(1);
      else {
        var link = ev.target.closest("a[data-drawer-load]");
        if (link && !ev.ctrlKey && !ev.metaKey) { ev.preventDefault(); load(link.getAttribute("data-drawer-load") || link.href); }
      }
    });
    drawerBody.addEventListener("submit", onDrawerSubmit);
  }

  function siblings(el) {
    var scope = el.closest("[data-preview-scope]") || el.closest("tbody") || el.parentElement;
    return Array.prototype.filter.call(scope.querySelectorAll("[data-preview]"), function (row) {
      return row.offsetParent !== null;
    });
  }

  // innerHTML non esegue gli <script> del frammento: si ricreano, così una scheda
  // con il suo JS (es. attività del KICK-OFF) funziona anche dentro il pannello.
  function eseguiScript(root) {
    Array.prototype.forEach.call(root.querySelectorAll("script"), function (old) {
      var s = document.createElement("script");
      Array.prototype.forEach.call(old.attributes, function (a) { s.setAttribute(a.name, a.value); });
      s.textContent = old.textContent;
      old.parentNode.replaceChild(s, old);
    });
  }

  function mostra(html) {
    drawerBody.innerHTML = html;
    eseguiScript(drawerBody);
    drawerBody.scrollTop = 0;
  }

  function load(url) {
    drawerBody.innerHTML = '<p class="soc-drawer-loading">Caricamento…</p>';
    return fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function (html) { mostra(html); drawerBody.focus(); })
      .catch(function () { drawerBody.innerHTML = '<p class="sec-action-result sec-error">Anteprima non disponibile. Apri la scheda completa.</p>'; });
  }

  function openFor(el) {
    if (!drawer) buildDrawer();
    // Dentro il contenitore del modulo: badge, pulsanti e testi hanno gli stili scoped lì.
    var host = hostFor(el);
    if (drawer.parentNode !== host) host.appendChild(drawer);
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
    if (current) { current.classList.remove("is-previewed"); if (current.focus) current.focus(); }
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
    // getAttribute: con un campo name="action" nel form, form.action sarebbe il campo e non l'URL.
    fetch(form.getAttribute("action") || window.location.href, {
      method: "POST", body: new FormData(form), credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "HX-Request": "true", "X-Requested-With": "XMLHttpRequest" }
    })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.text(); })
      .then(function (html) {
        if (target) { target.innerHTML = html; if (button) { button.disabled = false; if (button.dataset.label) button.textContent = button.dataset.label; } return; }
        changed = true;
        // [data-drawer-replace]: la risposta è il pannello rifatto, con l'esito dell'azione dentro.
        if (form.hasAttribute("data-drawer-replace")) { mostra(html); return; }
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
    if (!row) return;
    var own = ev.target.closest("a, button, input, select, label, textarea");
    if (own && own !== row) return;
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

  function initWithin(root) {
    (root || document).querySelectorAll("form[data-bulk]").forEach(initBulk);
    (root || document).querySelectorAll("[data-preview]").forEach(function (row) {
      if (!row.hasAttribute("tabindex")) row.setAttribute("tabindex", "0");
      row.classList.add("has-preview");
    });
  }

  window.HubBulkPannello = {
    initWithin: initWithin,
    isOpen: function () { return !!(drawer && drawer.classList.contains("is-open")); },
    open: openFor,
    close: closeDrawer
  };

  // Pezzi di pagina rimessi da HTMX (righe aggiornate, frammenti): stessi comportamenti.
  document.addEventListener("htmx:load", function (ev) {
    var el = ev.target;
    if (!el || !el.querySelectorAll) return;
    initWithin(el.parentNode || el);
    var form = el.closest && el.closest("form[data-bulk]");
    if (form) initBulk(form);
    el.querySelectorAll(".sec-bulk-item[form]").forEach(function (box) { if (box.form) initBulk(box.form); });
    if (el.matches && el.matches(".sec-bulk-item[form]") && el.form) initBulk(el.form);
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { initWithin(document); });
  else initWithin(document);
})();
