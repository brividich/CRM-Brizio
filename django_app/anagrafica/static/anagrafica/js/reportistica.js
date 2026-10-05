/* Reportistica — editor dei blocchi e filtro delle select multiple.
 *
 * Il formset Django resta la fonte di verità: qui si aggiungono blocchi
 * clonando l'empty_form, si spostano nel DOM (l'ordine si scrive nel campo
 * nascosto "ordine" al submit) e si eliminano spuntando DELETE.
 */
(function () {
  "use strict";

  var TIPI = { TESTO: "Testo", SEZIONE: "Sezione dati", PAGINA: "Nuova pagina", FIRME: "Firme" };
  var sezioni = {};
  var dati = document.getElementById("rp-sezioni");
  if (dati) {
    try { sezioni = JSON.parse(dati.textContent) || {}; } catch (e) { sezioni = {}; }
  }

  // ── Filtro testuale per le select multiple (persone) ─────────────────────
  document.querySelectorAll("[data-rp-filtra]").forEach(function (input) {
    var select = document.getElementById(input.getAttribute("data-rp-filtra"));
    if (!select) return;
    input.addEventListener("input", function () {
      var q = input.value.trim().toLowerCase();
      Array.prototype.forEach.call(select.options, function (opt) {
        opt.hidden = !!q && opt.text.toLowerCase().indexOf(q) === -1 && !opt.selected;
      });
    });
  });

  var lista = document.getElementById("rp-blocchi");
  var form = document.getElementById("rp-form");
  if (!lista || !form) return;
  var totale = form.querySelector('input[name="blocchi-TOTAL_FORMS"]');
  var tpl = document.getElementById("rp-tpl");

  function campo(blocco, suffisso) {
    return blocco.querySelector('[name$="-' + suffisso + '"]');
  }

  function visibili() {
    return Array.prototype.filter.call(lista.querySelectorAll("[data-rp-blocco]"), function (b) {
      return !b.classList.contains("rp-eliminato");
    });
  }

  function aggiornaColonne(blocco) {
    var sel = campo(blocco, "sezione");
    var chiave = sel ? sel.value : "";
    // Colonne e opzioni sono rese per ogni sezione: si mostra solo il gruppo di quella scelta.
    blocco.querySelectorAll("[data-rp-opz]").forEach(function (gruppo) {
      gruppo.classList.toggle("rp-blocco-hidden", gruppo.getAttribute("data-rp-opz") !== chiave);
    });
    var info = blocco.querySelector("[data-rp-sez-info]");
    if (info) {
      var s = sezioni[chiave];
      info.textContent = "";
      if (s) {
        var testo = s.descrizione + (s.riferimenti ? " — " + s.riferimenti : "");
        testo += s.perimetro ? " · usa il perimetro di persone" : " · perimetro aziendale";
        if (s.periodo) testo += " · usa il periodo";
        info.textContent = testo;
      }
    }
  }

  function aggiornaTesta(blocco, n) {
    var tipo = blocco.getAttribute("data-tipo");
    blocco.querySelector("[data-rp-n]").textContent = n;
    blocco.querySelector("[data-rp-tipo-label]").textContent = TIPI[tipo] || tipo;
    var anteprima = "";
    var titolo = campo(blocco, "titolo");
    var testo = campo(blocco, "testo");
    var sel = campo(blocco, "sezione");
    if (titolo && titolo.value.trim()) anteprima = titolo.value.trim();
    else if (tipo === "SEZIONE" && sel && sel.selectedIndex > 0) anteprima = sel.options[sel.selectedIndex].text;
    else if (tipo === "TESTO" && testo && testo.value.trim()) anteprima = testo.value.trim().split("\n")[0];
    blocco.querySelector("[data-rp-anteprima]").textContent = anteprima ? "— " + anteprima : "";
  }

  function rinumera() {
    visibili().forEach(function (b, i) { aggiornaTesta(b, i + 1); });
  }

  function collega(blocco) {
    blocco.querySelector("[data-rp-su]").addEventListener("click", function () {
      var prec = blocco.previousElementSibling;
      while (prec && prec.classList.contains("rp-eliminato")) prec = prec.previousElementSibling;
      if (prec) lista.insertBefore(blocco, prec);
      rinumera();
    });
    blocco.querySelector("[data-rp-giu]").addEventListener("click", function () {
      var succ = blocco.nextElementSibling;
      while (succ && succ.classList.contains("rp-eliminato")) succ = succ.nextElementSibling;
      if (succ) lista.insertBefore(succ, blocco);
      rinumera();
    });
    blocco.querySelector("[data-rp-elimina]").addEventListener("click", function () {
      var del = campo(blocco, "DELETE");
      if (del) del.checked = true;
      blocco.classList.add("rp-eliminato");
      rinumera();
    });
    blocco.querySelector("[data-rp-apri]").addEventListener("click", function () {
      blocco.classList.toggle("rp-chiuso");
    });
    // Colonne: spunta = stampata; ↑ ↓ = ordine di stampa (il browser invia le spunte nell'ordine del DOM).
    blocco.addEventListener("click", function (ev) {
      var su = ev.target.closest("[data-rp-col-su]");
      var giu = ev.target.closest("[data-rp-col-giu]");
      if (!su && !giu) return;
      var voce = ev.target.closest(".rp-col");
      if (su && voce.previousElementSibling) voce.parentNode.insertBefore(voce, voce.previousElementSibling);
      if (giu && voce.nextElementSibling) voce.parentNode.insertBefore(voce.nextElementSibling, voce);
    });
    blocco.addEventListener("change", function (ev) {
      if (ev.target.matches(".rp-col input[type=checkbox]")) {
        ev.target.closest(".rp-col").classList.toggle("rp-col-on", ev.target.checked);
      }
    });
    var sel = campo(blocco, "sezione");
    if (sel) sel.addEventListener("change", function () { aggiornaColonne(blocco); rinumera(); });
    ["titolo", "testo"].forEach(function (nome) {
      var el = campo(blocco, nome);
      if (el) el.addEventListener("input", rinumera);
    });
    aggiornaColonne(blocco);
  }

  lista.querySelectorAll("[data-rp-blocco]").forEach(function (b) {
    var del = campo(b, "DELETE");
    if (del && del.checked) b.classList.add("rp-eliminato");
    collega(b);
  });
  rinumera();

  document.querySelectorAll("[data-rp-aggiungi]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (!tpl || !totale) return;
      var indice = parseInt(totale.value, 10) || 0;
      var html = tpl.innerHTML.replace(/__prefix__/g, String(indice));
      var box = document.createElement("div");
      box.innerHTML = html.trim();
      var blocco = box.firstElementChild;
      var tipo = btn.getAttribute("data-rp-aggiungi");
      blocco.setAttribute("data-tipo", tipo);
      var campoTipo = campo(blocco, "tipo");
      if (campoTipo) campoTipo.value = tipo;
      lista.appendChild(blocco);
      totale.value = String(indice + 1);
      collega(blocco);
      rinumera();
      var focus = blocco.querySelector(tipo === "SEZIONE" ? "select" : "input[type=text], textarea");
      if (focus) focus.focus();
    });
  });

  form.addEventListener("submit", function () {
    visibili().forEach(function (b, i) {
      var ordine = campo(b, "ordine");
      if (ordine) ordine.value = String((i + 1) * 10);
    });
  });
})();
