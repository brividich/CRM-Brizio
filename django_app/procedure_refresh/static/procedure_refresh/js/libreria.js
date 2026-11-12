/* CN-SGI · libreria: pannello della scheda, schede interne, anteprima, ricerca live, ricerche recenti.
   I link con data-cn-doc aprono la scheda nel pannello (HTMX); senza JS vanno alla pagina. */
(function () {
  "use strict";
  var drawer = document.getElementById("cn-drawer");
  var scrim = document.getElementById("cn-scrim");
  var ultimoFocus = null;
  var CHIAVE_RECENTI = "cnsgi-ricerche";

  /* ── Pannello laterale ─────────────────────────────────────────────── */
  function apri(url) {
    if (!drawer || !window.htmx) { window.location.href = url; return; }
    ultimoFocus = document.activeElement;
    drawer.innerHTML = '<p class="cn-note" style="margin:18px">Caricamento…</p>';
    drawer.hidden = false;
    scrim.hidden = false;
    document.body.style.overflow = "hidden";
    chiudiTendina();
    window.htmx.ajax("GET", url, { target: "#cn-drawer", swap: "innerHTML" });
  }

  function chiudi() {
    if (!drawer || drawer.hidden) return;
    drawer.hidden = true;
    scrim.hidden = true;
    drawer.innerHTML = "";
    document.body.style.overflow = "";
    if (ultimoFocus && ultimoFocus.focus) ultimoFocus.focus();
  }

  /* ── Schede della scheda documento ─────────────────────────────────── */
  function vaiScheda(box, nome) {
    var trovata = false;
    box.querySelectorAll("[data-cn-tab]").forEach(function (b) {
      var on = b.getAttribute("data-cn-tab") === nome;
      b.setAttribute("aria-selected", on ? "true" : "false");
      if (on) trovata = true;
    });
    if (!trovata) return;
    box.querySelectorAll("[data-cn-pane]").forEach(function (p) { p.hidden = p.getAttribute("data-cn-pane") !== nome; });
    if (nome === "anteprima") anteprima(box, null);
  }

  function anteprima(box, pagina) {
    var frame = box.querySelector("iframe.cn-anteprima");
    if (!frame) return;
    var base = box.getAttribute("data-pdf") || frame.getAttribute("data-src");
    if (pagina) frame.src = base + "#page=" + pagina;
    else if (!frame.getAttribute("src")) frame.src = base + "#page=1";
  }

  /* ── Ricerche recenti (solo in questo browser) ─────────────────────── */
  function leggiRecenti() {
    try { return JSON.parse(localStorage.getItem(CHIAVE_RECENTI) || "[]").slice(0, 6); } catch (e) { return []; }
  }
  function ricorda(q) {
    q = (q || "").trim();
    if (q.length < 2) return;
    try {
      var r = leggiRecenti().filter(function (x) { return x.toLowerCase() !== q.toLowerCase(); });
      r.unshift(q);
      localStorage.setItem(CHIAVE_RECENTI, JSON.stringify(r.slice(0, 6)));
    } catch (e) { /* senza archivio del browser niente recenti */ }
  }

  var tendina = document.getElementById("cn-sugg");
  function chiudiTendina() { if (tendina) tendina.innerHTML = ""; }
  function mostraRecenti(input) {
    if (!tendina || input.value.trim()) return;
    var r = leggiRecenti();
    if (!r.length) { chiudiTendina(); return; }
    var url = input.form ? input.form.getAttribute("action") : "";
    var html = '<div class="cn-sugg-box" role="listbox" aria-label="Ricerche recenti"><div class="cn-sugg-h">Ricerche recenti</div>';
    r.forEach(function (q) {
      var a = document.createElement("a");
      a.className = "cn-sugg-i";
      a.href = url + "?q=" + encodeURIComponent(q);
      a.textContent = "↺ " + q;
      html += a.outerHTML;
    });
    tendina.innerHTML = html + "</div>";
  }

  /* ── Eventi ────────────────────────────────────────────────────────── */
  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-cn-doc]");
    if (link && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) {
      e.preventDefault();
      apri(link.getAttribute("href"));
      return;
    }
    if (e.target.closest("[data-cn-close]")) { chiudi(); return; }
    var box = e.target.closest("[data-cn-scheda]");
    var tab = e.target.closest("[data-cn-tab]");
    if (tab && box) { vaiScheda(box, tab.getAttribute("data-cn-tab")); return; }
    var prev = e.target.closest("[data-cn-anteprima]");
    if (prev && box && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      vaiScheda(box, "anteprima");
      anteprima(box, prev.getAttribute("data-cn-anteprima") || 1);
      return;
    }
    var vai = e.target.closest("[data-cn-vai]");
    if (vai && box) { e.preventDefault(); vaiScheda(box, vai.getAttribute("data-cn-vai")); return; }
    var q = e.target.closest("[data-cn-ricorda-q]");
    if (q) ricorda(q.getAttribute("data-cn-ricorda-q"));
    if (tendina && !e.target.closest(".cn-sugg-wrap")) chiudiTendina();
  });

  document.addEventListener("submit", function (e) {
    var chiedi = e.target.closest("[data-cn-chiedi]");
    if (chiedi) {
      var domanda = (chiedi.querySelector("[name=domanda]").value || "").trim();
      if (!domanda) { e.preventDefault(); return; }
      chiedi.querySelector("[name=q]").value = chiedi.getAttribute("data-cn-chiedi") + domanda;
      chiedi.querySelector("[name=domanda]").disabled = true;
      setTimeout(function () { chiedi.querySelector("[name=domanda]").disabled = false; }, 500);
      return;
    }
    var input = e.target.querySelector("[data-cn-ricorda]");
    if (input) ricorda(input.value);
  });

  document.addEventListener("focusin", function (e) {
    if (e.target.matches && e.target.matches("[data-cn-recenti]")) mostraRecenti(e.target);
  });
  document.addEventListener("input", function (e) {
    if (e.target.matches && e.target.matches("[data-cn-recenti]") && !e.target.value.trim()) mostraRecenti(e.target);
  });

  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target === drawer) {
      var x = drawer.querySelector("[data-cn-close]");
      if (x) x.focus();
      var box = drawer.querySelector("[data-cn-scheda]");
      var sel = box && box.querySelector('[data-cn-tab][aria-selected="true"]');
      if (sel && sel.getAttribute("data-cn-tab") === "anteprima") anteprima(box, null);
    }
  });
  document.addEventListener("htmx:afterRequest", function (e) {
    // Ricerca live: la frase entra nelle recenti quando arrivano risultati.
    var t = e.detail.elt;
    if (t && t.id === "cn-form-cerca") {
      var i = t.querySelector("[data-cn-ricorda]");
      if (i && i.value.trim().length >= 3) ricorda(i.value);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { if (tendina && tendina.innerHTML) { chiudiTendina(); return; } chiudi(); return; }
    var tag = (document.activeElement && document.activeElement.tagName) || "";
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(tag) && !document.activeElement.isContentEditable) {
      var q = document.getElementById("cn-q");
      if (q) { e.preventDefault(); q.focus(); }
      return;
    }
    // Frecce nella tendina dei suggerimenti.
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && tendina && tendina.innerHTML) {
      var voci = Array.prototype.slice.call(tendina.querySelectorAll(".cn-sugg-i"));
      if (!voci.length) return;
      var i = voci.indexOf(document.activeElement);
      if (e.key === "ArrowDown") i = i < 0 ? 0 : Math.min(voci.length - 1, i + 1);
      else i = i <= 0 ? -1 : i - 1;
      e.preventDefault();
      if (i < 0) document.getElementById("cn-q").focus(); else voci[i].focus();
    }
  });

  /* ── Gestione «Chi vede cosa»: sezioni e documenti seguono lo scaffale scelto ── */
  var selScaf = document.getElementById("cn-v-scaffale");
  if (selScaf) {
    var filtra = function () {
      var s = selScaf.value;
      ["cn-v-sezione", "cn-v-documento"].forEach(function (id) {
        var sel = document.getElementById(id);
        if (!sel) return;
        Array.prototype.forEach.call(sel.options, function (o) {
          if (!o.value) return;
          var ok = o.getAttribute("data-scaffale") === s;
          o.hidden = !ok; o.disabled = !ok;
          if (!ok && o.selected) sel.value = "";
        });
      });
    };
    selScaf.addEventListener("change", filtra);
    filtra();
    var ruoli = document.getElementById("cn-v-ruoli");
    var aggiornaChi = function () {
      var sel = document.querySelector("input[name=chi]:checked");
      if (ruoli) ruoli.hidden = sel && sel.value === "nessuno";
    };
    document.querySelectorAll("input[name=chi]").forEach(function (r) { r.addEventListener("change", aggiornaChi); });
    aggiornaChi();
  }
})();

/* Filtri che si applicano appena cambiano (selettori) o dopo una pausa di scrittura (campi). */
(function () {
  "use strict";
  var timer = null;
  var campo = document.querySelector("[data-cn-autosubmit-ritardo][autofocus]");
  if (campo) { var n = campo.value.length; try { campo.setSelectionRange(n, n); } catch (e) { /* tipo search */ } }
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches("[data-cn-autosubmit]") && e.target.form) e.target.form.submit();
  });
  document.addEventListener("input", function (e) {
    if (!(e.target.matches && e.target.matches("[data-cn-autosubmit-ritardo]") && e.target.form)) return;
    clearTimeout(timer);
    var form = e.target.form;
    timer = setTimeout(function () { form.submit(); }, 600);
  });
})();
