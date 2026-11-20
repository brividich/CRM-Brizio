/*
 * Percorso di navigazione (in alto, sotto la barra del modulo), su tutte le pagine del portale.
 *
 * Mostra le pagine aperte in questa scheda del browser, nell'ordine in cui ci si è arrivati:
 * ogni tappa è un link vero, quindi si apre anche con tasto destro → «Apri in nuova scheda»,
 * clic centrale o Ctrl+clic, senza dover usare la freccia «Indietro» del browser.
 *
 * Regole:
 *  - il percorso vive in sessionStorage: è della scheda, una scheda nuova parte da zero;
 *  - arrivando da fuori (mail, link, indirizzo scritto a mano, scheda nuova) il percorso
 *    riparte da «Home › Modulo › Sezione», ricavati dalle voci di menu visibili all'utente;
 *  - tornare su una pagina già nel percorso taglia le tappe successive (come «Indietro»);
 *  - stessa pagina con filtri o pagina diversi (?q=, ?page=) sostituisce l'ultima tappa;
 *  - al massimo MAX tappe, le più vecchie escono;
 *  - con una sola tappa (la Home) la barra resta nascosta.
 */
(function () {
  "use strict";
  var KEY = "nhub.percorso";
  var MAX = 8;
  var bar = document.querySelector("[data-hub-percorso]");
  if (!bar || window.top !== window.self) return;

  function leggi() {
    try {
      var arr = JSON.parse(window.sessionStorage.getItem(KEY) || "[]");
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  }
  function salva(arr) {
    try { window.sessionStorage.setItem(KEY, JSON.stringify(arr)); } catch (e) { /* storage bloccato */ }
  }
  function pulisci(s) { return String(s || "").replace(/\s+/g, " ").trim(); }
  function soloPercorso(href) {
    try {
      var p = new URL(href, window.location.href).pathname.replace(/\/+$/, "");
      return p || "/";
    } catch (e) { return ""; }
  }

  /* Nome della tappa: titolo visibile della pagina, altrimenti la prima parte del <title>. */
  function nomePagina() {
    var parti = pulisci(document.title).split(" | ");
    var titolo = parti[0] || "";
    var modulo = parti.length > 1 ? parti[parti.length - 1] : "";
    var h = document.querySelector(".content .page-h, .content h1");
    var testo = "";
    if (h) {
      /* Senza contatori, badge e sottotitoli che stanno dentro il titolo (es. «Corsi 693»). */
      var copia = h.cloneNode(true);
      Array.prototype.forEach.call(
        copia.querySelectorAll("small, sup, button, svg, [class*='badge'], [class*='count'], [class*='pill'], [class*='chip'], [class*='tag'], [class*='kpi'], .sr-only"),
        function (n) { n.remove(); }
      );
      testo = pulisci(copia.textContent);
    }
    var nome = testo && testo.length <= 60 ? testo : titolo;
    return { t: nome || window.location.pathname, m: modulo && modulo !== nome ? modulo : "" };
  }

  /* Breadcrumb fissi dei moduli (nascosti dal CSS di theme.css, stesso elenco): i loro link sono
     la gerarchia scritta a mano per quella pagina, quindi la partenza migliore. */
  var VECCHI = ".fmd-crumb,.fm-crumb,.as-crumbs,.auto-breadcrumbs,.gm-crumb,.hg-crumb,.sp-crumb,.ana-breadcrumb,.cn-crumb,.sic-breadcrumb,.soc-crumb,.dp-breadcrumb";
  function dalBreadcrumbDellaPagina(pHome, pCorrente) {
    var box = document.querySelector(".content :is(" + VECCHI + ")");
    if (!box) return null;
    var visti = {};
    var tappe = [];
    Array.prototype.forEach.call(box.querySelectorAll("a[href]"), function (a) {
      var href = a.getAttribute("href");
      var p = soloPercorso(href);
      var t = pulisci(a.textContent).replace(/^[←‹<\s]+/, "");
      if (!p || !t || /guida/i.test(t) || p === pHome || p === "/" || p === pCorrente || visti[p]) return;
      visti[p] = true;
      tappe.push({ u: href, p: p, t: t, m: "" });
    });
    return tappe.length ? tappe : null;
  }

  /* «Home › Modulo › Sezione»: breadcrumb del modulo, altrimenti le voci di menu il cui
     indirizzo contiene quello della pagina. */
  function partenza(pCorrente) {
    var home = bar.getAttribute("data-home") || "/";
    var pHome = soloPercorso(home);
    var tappe = [{ u: home, p: pHome, t: "Home", m: "" }];
    if (pCorrente === pHome || pCorrente === "/") return tappe;
    var dalModulo = dalBreadcrumbDellaPagina(pHome, pCorrente);
    if (dalModulo) return tappe.concat(dalModulo);
    var tpl = document.querySelector("template[data-hub-percorso-voci]");
    if (!tpl) return tappe;
    var visti = {};
    var voci = [];
    Array.prototype.forEach.call(tpl.content.querySelectorAll("a[href]"), function (a) {
      var href = a.getAttribute("href");
      var p = soloPercorso(href);
      if (!p || p === "/" || p === pHome || visti[p]) return;
      if (p === pCorrente || pCorrente.indexOf(p + "/") !== 0) return;
      visti[p] = true;
      voci.push({ u: href, p: p, t: pulisci(a.textContent) || p, m: "" });
    });
    voci.sort(function (a, b) { return a.p.length - b.p.length; });
    if (voci.length > 2) voci = [voci[0], voci[voci.length - 1]];
    return tappe.concat(voci);
  }

  function arrivoDaFuori() {
    var nav = window.performance && performance.getEntriesByType ? performance.getEntriesByType("navigation")[0] : null;
    if (nav && (nav.type === "back_forward" || nav.type === "reload")) return false;
    if (!document.referrer) return true;
    try { return new URL(document.referrer).origin !== window.location.origin; } catch (e) { return true; }
  }

  var pRaw = window.location.pathname;
  var p = pRaw.replace(/\/+$/, "") || "/";
  var u = pRaw + window.location.search;
  var info = nomePagina();
  var trail = leggi();
  if (!trail.length || arrivoDaFuori()) trail = partenza(p);

  var idx = -1;
  for (var i = 0; i < trail.length; i++) { if (trail[i].u === u || (trail[i].p === p && !window.location.search)) { idx = i; break; } }
  if (idx === -1 && trail.length && trail[trail.length - 1].p === p) idx = trail.length - 1;
  if (idx >= 0) trail = trail.slice(0, idx);
  var pHome = soloPercorso(bar.getAttribute("data-home") || "/");
  trail.push({ u: u, p: p, t: p === pHome ? "Home" : info.t, m: info.m });
  if (trail.length > MAX) trail = trail.slice(trail.length - MAX);
  salva(trail);

  if (trail.length < 2) return;

  var ol = document.createElement("ol");
  ol.className = "hub-percorso-lista";
  trail.forEach(function (e, n) {
    var li = document.createElement("li");
    var ultima = n === trail.length - 1;
    var el = document.createElement(ultima ? "span" : "a");
    el.className = "hub-percorso-tappa";
    el.textContent = e.t;
    el.title = e.m ? e.t + " · " + e.m : e.t;
    if (ultima) el.setAttribute("aria-current", "page");
    else el.href = e.u;
    li.appendChild(el);
    ol.appendChild(li);
  });
  bar.appendChild(ol);
  bar.hidden = false;
  /* Su schermi stretti la barra scorre: tiene in vista la pagina corrente. */
  bar.scrollLeft = bar.scrollWidth;
})();
