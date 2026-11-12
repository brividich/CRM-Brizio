/* Reception: ricerca live per compilare i form in un tocco.
 *
 * <input data-cerca-url="/reception/api/ospiti/" data-riempi='{"nome":"#r-nome",...}' data-formato="ospite">
 *   cerca sul server mentre scrivi e, alla scelta, riempie i campi indicati.
 * <input data-scegli="#id-json" data-valore="#campo-nascosto">
 *   sceglie da un elenco già nella pagina (json_script), filtrato mentre scrivi.
 * Tastiera: frecce, Invio per scegliere, Esc per chiudere. Nessuna libreria.
 */
(function () {
  "use strict";

  function el(tag, cls, testo) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (testo) e.textContent = testo;
    return e;
  }

  function norm(s) {
    return (s || "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function formato(tipo, r) {
    if (tipo === "dipendente") {
      return {
        titolo: (r.cognome + " " + r.nome).trim(),
        sotto: [r.reparto, r.email || "senza email di notifica", r.telefono].filter(Boolean).join(" · "),
        badge: r.referente ? "Già referente" : "",
      };
    }
    if (tipo === "referente") {
      return { titolo: r.nome, sotto: r.reparto || "", badge: "" };
    }
    return {
      titolo: (r.cognome + " " + r.nome).trim(),
      sotto: [r.azienda, r.email, r.ultima ? "ultima visita " + r.ultima : ""].filter(Boolean).join(" · "),
      badge: r.dentro ? "Già dentro" : "",
    };
  }

  function valore(r, chiave) {
    if (chiave === "nome_completo") return (r.nome + " " + r.cognome).trim();
    return r[chiave] == null ? "" : String(r[chiave]);
  }

  function attiva(input, cerca, alScegliere) {
    var tipo = input.getAttribute("data-formato") || "ospite";
    var box = el("div", "rc-sugg");
    box.setAttribute("role", "listbox");
    box.hidden = true;
    input.parentNode.classList.add("rc-cerca-wrap");
    input.parentNode.appendChild(box);
    input.setAttribute("autocomplete", "off");
    input.setAttribute("aria-autocomplete", "list");
    var risultati = [], scelto = -1, timer = null, ultimaRichiesta = 0;

    function chiudi() { box.hidden = true; scelto = -1; }

    function evidenzia(i) {
      scelto = i;
      Array.prototype.forEach.call(box.children, function (c, k) { c.classList.toggle("on", k === i); });
    }

    function mostra(lista, vuoto) {
      risultati = lista;
      box.innerHTML = "";
      if (!lista.length) {
        if (vuoto) { box.appendChild(el("div", "rc-sugg-vuoto", vuoto)); box.hidden = false; } else { chiudi(); }
        return;
      }
      lista.forEach(function (r, i) {
        var f = formato(tipo, r);
        var riga = el("button", "rc-sugg-riga");
        riga.type = "button";
        riga.setAttribute("role", "option");
        var testa = el("span", "rc-sugg-titolo", f.titolo);
        if (f.badge) testa.appendChild(el("span", "rc-sugg-badge", f.badge));
        riga.appendChild(testa);
        if (f.sotto) riga.appendChild(el("span", "rc-sugg-sotto", f.sotto));
        riga.addEventListener("mousedown", function (ev) { ev.preventDefault(); scegli(i); });
        box.appendChild(riga);
      });
      box.hidden = false;
      evidenzia(-1);
    }

    function scegli(i) {
      var r = risultati[i];
      if (!r) return;
      chiudi();
      alScegliere(r);
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      timer = setTimeout(function () {
        var n = ++ultimaRichiesta;
        cerca(q, function (lista, vuoto) { if (n === ultimaRichiesta) mostra(lista, vuoto); });
      }, 180);
    });
    input.addEventListener("focus", function () { if (input.value.trim().length >= (tipo === "referente" ? 0 : 2)) input.dispatchEvent(new Event("input")); });
    input.addEventListener("blur", function () { setTimeout(chiudi, 120); });
    input.addEventListener("keydown", function (ev) {
      if (box.hidden) return;
      if (ev.key === "ArrowDown") { ev.preventDefault(); evidenzia(Math.min(scelto + 1, risultati.length - 1)); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); evidenzia(Math.max(scelto - 1, 0)); }
      else if (ev.key === "Enter" && scelto >= 0) { ev.preventDefault(); scegli(scelto); }
      else if (ev.key === "Escape") { chiudi(); }
    });
  }

  // Ricerca sul server
  document.querySelectorAll("[data-cerca-url]").forEach(function (input) {
    var url = input.getAttribute("data-cerca-url");
    var riempi = JSON.parse(input.getAttribute("data-riempi") || "{}");
    var vuoto = input.getAttribute("data-vuoto") || "";
    attiva(input, function (q, fatto) {
      if (q.length < 2) { fatto([]); return; }
      fetch(url + "?q=" + encodeURIComponent(q), { headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : { results: [] }; })
        .then(function (d) { fatto(d.results || [], vuoto); })
        .catch(function () { fatto([]); });
    }, function (r) {
      Object.keys(riempi).forEach(function (chiave) {
        var campo = document.querySelector(riempi[chiave]);
        if (campo) { campo.value = valore(r, chiave); campo.dispatchEvent(new Event("change")); }
      });
      if (input.hasAttribute("data-svuota")) input.value = "";
      var avviso = document.querySelector(input.getAttribute("data-avviso") || "#_nessuno");
      if (avviso) {
        var testo = r.dentro ? "Attenzione: risulta già dentro." : (r.referente ? "È già tra i referenti: salvando aggiorni i suoi dati." : (r.email === "" && input.getAttribute("data-formato") === "dipendente" ? "In anagrafica manca l'email di notifica: scrivila a mano." : ""));
        avviso.textContent = testo;
        avviso.hidden = !testo;
      }
      var focus = document.querySelector(input.getAttribute("data-poi") || "#_nessuno");
      if (focus) focus.focus();
    });
  });

  // Scelta da un elenco nella pagina (referenti)
  document.querySelectorAll("[data-scegli]").forEach(function (input) {
    var fonte = document.querySelector(input.getAttribute("data-scegli"));
    var nascosto = document.querySelector(input.getAttribute("data-valore"));
    if (!fonte || !nascosto) return;
    var elenco = JSON.parse(fonte.textContent || "[]");
    var pulisci = function () { if (nascosto.value && input.value !== input.getAttribute("data-scelto")) nascosto.value = ""; };
    input.addEventListener("input", pulisci);
    attiva(input, function (q, fatto) {
      var parole = norm(q).split(/\s+/).filter(Boolean);
      fatto(elenco.filter(function (r) {
        var testo = norm(r.nome + " " + (r.reparto || ""));
        return parole.every(function (p) { return testo.indexOf(p) >= 0; });
      }).slice(0, 12), "Nessun referente con questo nome.");
    }, function (r) {
      nascosto.value = r.id;
      input.value = r.nome;
      input.setAttribute("data-scelto", r.nome);
      var focus = document.querySelector(input.getAttribute("data-poi") || "#_nessuno");
      if (focus) focus.focus();
    });
    var form = input.form;
    if (form) form.addEventListener("submit", function (ev) {
      if (!nascosto.value) { ev.preventDefault(); input.focus(); input.classList.add("rc-errore"); input.setAttribute("placeholder", "Scegli il referente dall'elenco"); }
    });
  });
})();
