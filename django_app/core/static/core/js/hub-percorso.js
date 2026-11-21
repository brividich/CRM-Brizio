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
 *    riparte da «Home › Modulo › Sezione»: la gerarchia scritta nella pagina
 *    (<template data-hub-percorso-gerarchia>), altrimenti le voci di menu visibili all'utente;
 *  - tornare su una pagina già nel percorso taglia le tappe successive (come «Indietro»);
 *  - stessa pagina con filtri o pagina diversi (?q=, ?page=) sostituisce l'ultima tappa;
 *  - al massimo MAX tappe, le più vecchie escono;
 *  - con più di VISIBILI tappe si vedono «Home › … › ultime 3»: i «…» aprono l'elenco completo
 *    in una finestra al centro; su telefono resta solo «‹ tappa precedente» (hub-percorso.css);
 *  - nomi generici («Guida», «Impostazioni»…) o ripetuti portano il nome del modulo;
 *  - con una sola tappa (la Home) la barra resta nascosta.
 */
(function () {
  "use strict";
  var KEY = "nhub.percorso";
  var MAX = 8;
  var VISIBILI = 5;
  var GENERICI = /^(guida|impostazioni|configurazione|dashboard|cruscotto|panoramica|report|elenco|archivio|storico|registro|ricerca|statistiche|calendario|nuov[oa]|modifica|dettaglio|scheda|import|export|aiuto)$/i;
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
  function vociMenu() {
    var tpl = document.querySelector("template[data-hub-percorso-voci]");
    return tpl ? Array.prototype.slice.call(tpl.content.querySelectorAll("a[href]")) : [];
  }

  /* Modulo della pagina: la voce di menu con l'indirizzo più lungo che contiene quello della pagina
     (es. /anagrafica/formazione/guida/ → «Formazione»), altrimenti l'ultima parte del <title>. */
  function moduloPagina(pCorrente, nome) {
    var meglio = null;
    vociMenu().forEach(function (a) {
      var p = soloPercorso(a.getAttribute("href"));
      var t = pulisci(a.textContent);
      if (!p || p === "/" || !t || t === nome) return;
      if (p !== pCorrente && pCorrente.indexOf(p + "/") !== 0) return;
      if (!meglio || p.length > meglio.p.length) meglio = { p: p, t: t };
    });
    if (meglio) return meglio.t;
    var parti = pulisci(document.title).split(/\s+[|·—–-]\s+/);
    var ultimo = parti.length > 1 ? parti[parti.length - 1] : "";
    return ultimo && !/novicrom/i.test(ultimo) && ultimo !== nome ? ultimo : "";
  }

  /* Nome della tappa: titolo visibile della pagina, altrimenti la prima parte del <title>. */
  function nomePagina() {
    var fisso = bar.getAttribute("data-nome");
    if (fisso) return pulisci(fisso);
    /* «Pagina | Modulo», «Pagina — Dettaglio · NOVICROM HUB», «Pagina - Portale»: il nome è la prima parte. */
    var titolo = pulisci(document.title).split(/\s+[|·—–-]\s+/)[0] || "";
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
    return (testo && testo.length <= 60 ? testo : titolo) || window.location.pathname;
  }

  /* Gerarchia scritta nella pagina (ex breadcrumb dei moduli, ora invisibile): i suoi link sono
     la partenza migliore quando si arriva da fuori. */
  function dallaGerarchiaDellaPagina(pHome, pCorrente) {
    var tpl = document.querySelector("template[data-hub-percorso-gerarchia]");
    if (!tpl) return null;
    var visti = {};
    var tappe = [];
    Array.prototype.forEach.call(tpl.content.querySelectorAll("a[href]"), function (a) {
      var href = a.getAttribute("href");
      var p = soloPercorso(href);
      var t = pulisci(a.textContent).replace(/^[←‹<\s]+/, "");
      if (!p || !t || /guida/i.test(t) || p === pHome || p === "/" || p === pCorrente || visti[p]) return;
      visti[p] = true;
      tappe.push({ u: href, p: p, t: t });
    });
    return tappe.length ? tappe : null;
  }

  /* «Home › Modulo › Sezione»: gerarchia della pagina, altrimenti le voci di menu il cui
     indirizzo contiene quello della pagina. */
  function partenza(pCorrente) {
    var home = bar.getAttribute("data-home") || "/";
    var pHome = soloPercorso(home);
    var tappe = [{ u: home, p: pHome, t: "Home" }];
    if (pCorrente === pHome || pCorrente === "/") return tappe;
    var dallaPagina = dallaGerarchiaDellaPagina(pHome, pCorrente);
    if (dallaPagina) return tappe.concat(dallaPagina);
    var visti = {};
    var voci = [];
    vociMenu().forEach(function (a) {
      var href = a.getAttribute("href");
      var p = soloPercorso(href);
      if (!p || p === "/" || p === pHome || visti[p]) return;
      if (p === pCorrente || pCorrente.indexOf(p + "/") !== 0) return;
      visti[p] = true;
      voci.push({ u: href, p: p, t: pulisci(a.textContent) || p });
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
  var nome = nomePagina();
  var trail = leggi();
  if (!trail.length || arrivoDaFuori()) trail = partenza(p);

  var idx = -1;
  for (var i = 0; i < trail.length; i++) { if (trail[i].u === u || (trail[i].p === p && !window.location.search)) { idx = i; break; } }
  if (idx === -1 && trail.length && trail[trail.length - 1].p === p) idx = trail.length - 1;
  if (idx >= 0) trail = trail.slice(0, idx);
  var pHome = soloPercorso(bar.getAttribute("data-home") || "/");
  var casa = p === pHome;
  trail.push({ u: u, p: p, t: casa ? "Home" : nome, mod: casa ? "" : moduloPagina(p, nome) });
  if (trail.length > MAX) trail = trail.slice(trail.length - MAX);
  salva(trail);

  if (trail.length < 2) return;

  /* Il modulo si mostra solo dove serve: nomi generici o nomi uguali ad altre tappe. */
  var conteggio = {};
  trail.forEach(function (e) { conteggio[e.t] = (conteggio[e.t] || 0) + 1; });
  function conModulo(e) { return !!e.mod && (GENERICI.test(e.t) || conteggio[e.t] > 1); }
  function etichetta(e) { return conModulo(e) ? e.t + " · " + e.mod : e.t; }

  var ICONA_HOME = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false"><path d="M2.5 7.2 8 2.8l5.5 4.4V13a.9.9 0 0 1-.9.9H9.8V10H6.2v3.9H3.4a.9.9 0 0 1-.9-.9z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>';

  function tappa(e, ultima, inElenco) {
    var el = document.createElement(ultima ? "span" : "a");
    el.className = "hub-percorso-tappa";
    if (ultima) el.setAttribute("aria-current", "page");
    else el.href = e.u;
    el.title = etichetta(e);
    var isHome = e.t === "Home" && e.p === pHome;
    if (isHome && !inElenco) {
      el.classList.add("hub-percorso-tappa--home");
      el.innerHTML = ICONA_HOME;
      el.setAttribute("aria-label", "Home");
      return el;
    }
    var t = document.createElement("span");
    t.className = "hub-percorso-nome";
    t.textContent = e.t;
    el.appendChild(t);
    if (conModulo(e)) {
      var m = document.createElement("span");
      m.className = "hub-percorso-modulo";
      m.textContent = "· " + e.mod;
      el.appendChild(m);
    }
    return el;
  }

  /* Elenco completo in una finestra al centro (regola del portale: niente popup ancorati). */
  var modale = null;
  function apriElenco(daBottone) {
    if (!modale) {
      modale = document.createElement("div");
      modale.className = "hub-percorso-velo";
      modale.hidden = true;
      var box = document.createElement("div");
      box.className = "hub-percorso-modale";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      box.setAttribute("aria-labelledby", "hub-percorso-modale-t");
      var testa = document.createElement("div");
      testa.className = "hub-percorso-modale-testa";
      testa.innerHTML = '<h2 id="hub-percorso-modale-t">Il percorso di questa scheda</h2>';
      var chiudi = document.createElement("button");
      chiudi.type = "button";
      chiudi.className = "hub-percorso-chiudi";
      chiudi.setAttribute("aria-label", "Chiudi");
      chiudi.textContent = "×";
      chiudi.addEventListener("click", chiudiElenco);
      testa.appendChild(chiudi);
      var ol = document.createElement("ol");
      ol.className = "hub-percorso-elenco";
      trail.forEach(function (e, n) {
        var li = document.createElement("li");
        var num = document.createElement("span");
        num.className = "hub-percorso-num";
        num.textContent = String(n + 1);
        li.appendChild(num);
        li.appendChild(tappa(e, n === trail.length - 1, true));
        ol.appendChild(li);
      });
      var nota = document.createElement("p");
      nota.className = "hub-percorso-nota";
      nota.textContent = "Clic per tornare a una pagina; tasto destro o clic centrale per aprirla in un'altra scheda.";
      box.appendChild(testa);
      box.appendChild(ol);
      box.appendChild(nota);
      modale.appendChild(box);
      modale.addEventListener("click", function (ev) { if (ev.target === modale) chiudiElenco(); });
      document.body.appendChild(modale);
    }
    modale._da = daBottone;
    modale.hidden = false;
    document.addEventListener("keydown", tasto);
    var primo = modale.querySelector("a, button");
    if (primo) primo.focus();
  }
  function chiudiElenco() {
    if (!modale) return;
    modale.hidden = true;
    document.removeEventListener("keydown", tasto);
    if (modale._da) modale._da.focus();
  }
  function tasto(ev) { if (ev.key === "Escape") chiudiElenco(); }

  var nascoste = trail.length > VISIBILI ? trail.length - 4 : 0; /* Home + ultime 3 */
  var ol = document.createElement("ol");
  ol.className = "hub-percorso-lista" + (nascoste ? " ha-nascoste" : "");
  trail.forEach(function (e, n) {
    var li = document.createElement("li");
    var ultima = n === trail.length - 1;
    if (n === trail.length - 2) li.className = "is-precedente";
    if (nascoste && n >= 1 && n <= nascoste) li.className = (li.className + " is-nascosta").trim();
    li.appendChild(tappa(e, ultima, false));
    ol.appendChild(li);
    if (n === 0 && trail.length > 2) {
      var altre = document.createElement("li");
      altre.className = "hub-percorso-altre";
      var b = document.createElement("button");
      b.type = "button";
      b.className = "hub-percorso-tutte";
      b.title = "Mostra tutto il percorso";
      b.setAttribute("aria-label", "Mostra tutto il percorso (" + trail.length + " pagine)");
      b.setAttribute("aria-haspopup", "dialog");
      b.textContent = "…";
      b.addEventListener("click", function () { apriElenco(b); });
      altre.appendChild(b);
      ol.appendChild(altre);
    }
  });
  bar.appendChild(ol);
  bar.hidden = false;
  /* Su schermi stretti la barra scorre: tiene in vista la pagina corrente. */
  bar.scrollLeft = bar.scrollWidth;
})();
