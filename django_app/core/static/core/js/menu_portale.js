/* Menu del portale (admin_portale/pages/menu_portale.html).
   In alto la barra del portale com'è (categorie = tendine, voci da sole), sotto il
   contenuto di ogni tendina con i sottogruppi e le sottovoci, a destra la scheda
   della voce o della categoria scelta. I dati arrivano dal server (json_script
   #mp-dati); chi vede cosa lo calcola il server. */
(function () {
  "use strict";

  var root = document.getElementById("menu-portale");
  if (!root) return;
  var datiEl = document.getElementById("mp-dati");
  var D = JSON.parse(datiEl ? datiEl.textContent : "{}");
  var url = root.dataset;
  var csrf = (root.querySelector("input[name=csrfmiddlewaretoken]") || {}).value || "";

  /* scelta = {tipo: "voce"|"categoria", id} */
  var S = { ruolo: "tutti", persona: null, scelta: null };
  var voci = {};
  Object.keys(D.voci || {}).forEach(function (k) { voci[k] = D.voci[k]; });
  var categorie = {};
  (D.barra || []).forEach(function (n) { if (n.tipo === "categoria") categorie[n.id] = n; });
  var ruoliById = {};
  (D.ruoli || []).forEach(function (r) { ruoliById[r.id] = r; });
  var nomeApp = {};
  (D.moduli || []).forEach(function (m) { nomeApp[m.app] = m.nome; });

  /* ── utilità ─────────────────────────────────────────── */
  function el(tag, attrs, figli) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "testo") n.textContent = attrs[k];
      else if (k === "html") n.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) n.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    });
    (figli || []).forEach(function (f) { if (f) n.appendChild(typeof f === "string" ? document.createTextNode(f) : f); });
    return n;
  }
  function svg(path) {
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">' + path + "</svg>";
  }
  var ICO = {
    maniglia: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="8" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="8" cy="18" r="2"/><circle cx="16" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="16" cy="18" r="2"/></svg>',
    occhioNo: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 3l18 18M6.1 6.1A17 17 0 0 0 2 12s3.6 7 10 7a9.6 9.6 0 0 0 4-.9M9.9 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4"/></svg>',
    si: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>',
    freccia: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>',
    sotto: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M6 4v8a4 4 0 0 0 4 4h8m-3-3 3 3-3 3"/></svg>',
    cartella: svg('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
    immagine: svg('<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>'),
    persona: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/><path d="M3 3l18 18"/>'),
    apri: svg('<path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>'),
    cestino: svg('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>'),
  };
  function avviso(testo, livello) {
    if (window.hubFlash) window.hubFlash.show([{ text: testo, level: livello || "success" }]);
  }
  function post(indirizzo, dati) {
    return fetch(indirizzo, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify(dati),
      credentials: "same-origin",
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok || j.ok === false) throw new Error(j.error || j.message || "Salvataggio non riuscito.");
        return j;
      });
    });
  }
  function ricarica(testo, scelta) {
    try { sessionStorage.setItem("mp-dopo", JSON.stringify({ testo: testo, scelta: scelta || S.scelta })); } catch (e) { /* niente */ }
    window.location.reload();
  }

  /* Sottogruppi della tendina come li disegna la barra (core.context_processors._nav_sections). */
  function sezioni(ids) {
    var out = [];
    ids.forEach(function (id) {
      var g = (voci[id] || {}).gruppo || "";
      if (out.length && out[out.length - 1].nome === g) out[out.length - 1].voci.push(id);
      else out.push({ nome: g, voci: [id] });
    });
    var distinti = {};
    out.forEach(function (s) { if (s.nome) distinti[s.nome] = 1; });
    return Object.keys(distinti).length < 2 ? [{ nome: "", voci: ids.slice() }] : out;
  }

  /* ── chi vede cosa nella vista scelta ───────────────── */
  function vede(v) {
    if (S.persona) { var p = S.persona.voci[String(v.id)]; return !!(p && p.vede); }
    if (S.ruolo === "tutti") return true;
    return v.ruoli.indexOf(S.ruolo) >= 0;
  }
  function inBarra(v) { return v.visibile && vede(v); }
  function nomeVista() {
    if (S.persona) return S.persona.nome;
    if (S.ruolo === "tutti") return "";
    return (ruoliById[S.ruolo] || {}).nome || "";
  }
  function dove(v) {
    if (v.sezione === "subnav") {
      var madre = voci[v.sotto];
      return madre ? "Nella barra delle pagine di «" + madre.nome + "»" : "Nelle pagine di «" + (v.padre || "?") + "», che non hanno una voce nel menu";
    }
    var c = categorie[v.categoria];
    if (!c) return "Da sola nella barra in alto";
    return "Nella tendina «" + c.nome + "»" + (v.gruppo ? " › " + v.gruppo : "");
  }

  /* ── «Guarda il menu come» ───────────────────────────── */
  function disegnaRuoli() {
    var box = document.getElementById("mp-ruoli");
    box.innerHTML = "";
    function vai(id) { S.ruolo = id; S.persona = null; document.getElementById("mp-persona").value = ""; aggiornaTutto(); }
    var base = (D.ruoli || []).filter(function (r) { return r.base; })[0];
    var fissi = [{ id: "tutti", nome: "Tutti (amministratore)" }];
    if (base) fissi.push({ id: base.id, nome: base.nome + " (senza altri ruoli)" });
    fissi.forEach(function (r) {
      box.appendChild(el("button", {
        type: "button", "class": "mp-pill", "aria-pressed": !S.persona && S.ruolo === r.id ? "true" : "false",
        testo: r.nome, onclick: function () { vai(r.id); },
      }));
    });
    var altri = (D.ruoli || []).filter(function (r) { return !r.base; });
    if (altri.length) {
      var scelto = !S.persona && altri.some(function (r) { return r.id === S.ruolo; });
      var sel = el("select", { "class": "mp-pill mp-pill-select" + (scelto ? " attiva" : ""), "aria-label": "Un altro ruolo",
        onchange: function (e) { if (e.target.value) vai(parseInt(e.target.value, 10)); } },
        [el("option", { value: "", testo: "Un altro ruolo…" })].concat(altri.map(function (r) {
          return el("option", { value: r.id, selected: scelto && r.id === S.ruolo, testo: r.nome });
        })));
      box.appendChild(sel);
    }
    document.querySelector(".mp-cerca").classList.toggle("attiva", !!S.persona);
  }

  var cercaTimer = null;
  var inputPersona = document.getElementById("mp-persona");
  var esiti = document.getElementById("mp-persona-esiti");
  inputPersona.addEventListener("input", function () {
    clearTimeout(cercaTimer);
    var q = inputPersona.value.trim();
    if (q.length < 2) { esiti.hidden = true; return; }
    cercaTimer = setTimeout(function () {
      fetch(url.urlCerca + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          esiti.innerHTML = "";
          (j.results || []).slice(0, 12).forEach(function (u) {
            esiti.appendChild(el("button", { type: "button", testo: u.display, onclick: function () { scegliPersona(u); } }));
          });
          if (!esiti.children.length) esiti.appendChild(el("div", { "class": "mp-nota", style: "padding:10px 12px", testo: "Nessuna persona trovata." }));
          esiti.hidden = false;
        });
    }, 250);
  });
  document.addEventListener("click", function (e) { if (!esiti.contains(e.target) && e.target !== inputPersona) esiti.hidden = true; });

  function scegliPersona(u) {
    esiti.hidden = true;
    var nome = String(u.display || "").split(" — ")[0];
    inputPersona.value = nome;
    caricaPersona(u.id, nome);
  }
  function caricaPersona(id, nome) {
    return fetch(url.urlPersona + "?user_id=" + id, { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.ok) throw new Error(j.error || "Persona non trovata.");
        S.persona = { id: id, nome: nome, voci: j.voci };
        aggiornaTutto();
      })
      .catch(function (err) { avviso(err.message, "error"); });
  }

  /* ── «Da sistemare» ──────────────────────────────────── */
  function disegnaProblemi() {
    var box = document.getElementById("mp-problemi");
    var lista = Object.keys(voci).map(function (k) { return voci[k]; }).filter(function (v) { return v.problema; });
    box.innerHTML = "";
    box.hidden = !lista.length;
    if (!lista.length) return;
    box.appendChild(el("strong", { testo: "Da sistemare (" + lista.length + "):" }));
    lista.forEach(function (v) {
      box.appendChild(el("button", { type: "button", testo: v.nome, onclick: function () { scegli("voce", v.id); } }));
    });
  }

  function scelto(tipo, id) { return !!S.scelta && S.scelta.tipo === tipo && S.scelta.id === id; }

  /* ── trascina e rilascia ─────────────────────────────── */
  /* Si sposta solo fra elementi della stessa lista (stessa barra, stessa tendina, stesse sottovoci). */
  var trascinata = null;
  function trascinabile(nodo, elemento, lista, salva) {
    nodo.setAttribute("draggable", "true");
    nodo.addEventListener("dragstart", function (e) { trascinata = { elemento: elemento, lista: lista }; nodo.classList.add("trascina"); e.dataTransfer.effectAllowed = "move"; e.stopPropagation(); });
    nodo.addEventListener("dragend", function () { nodo.classList.remove("trascina"); trascinata = null; });
    nodo.addEventListener("dragover", function (e) {
      if (!trascinata || trascinata.lista !== lista || trascinata.elemento === elemento) return;
      e.preventDefault(); nodo.classList.add("sopra");
    });
    nodo.addEventListener("dragleave", function () { nodo.classList.remove("sopra"); });
    nodo.addEventListener("drop", function (e) {
      nodo.classList.remove("sopra");
      if (!trascinata || trascinata.lista !== lista || trascinata.elemento === elemento) return;
      e.preventDefault(); e.stopPropagation();
      lista.splice(lista.indexOf(trascinata.elemento), 1);
      lista.splice(lista.indexOf(elemento), 0, trascinata.elemento);
      aggiornaTutto();
      salva().then(function () { avviso("Ordine salvato."); }).catch(function (err) { avviso(err.message, "error"); });
    });
  }
  function salvaBarra() {
    return post(url.urlBarra, { elementi: D.barra.map(function (n) { return { tipo: n.tipo, id: n.id }; }) });
  }
  function salvaLista(ids) { return function () { return post(url.urlRiordina, { ordered_ids: ids.slice() }); }; }

  /* ── la barra in alto, come la vede chi hai scelto ──── */
  function disegnaBarra() {
    var box = document.getElementById("mp-barra");
    box.innerHTML = "";
    var vista = nomeVista();
    document.getElementById("mp-barra-titolo").textContent = vista ? "La barra in alto di «" + vista + "»" : "La barra in alto del portale";
    D.barra.forEach(function (n) {
      var b;
      if (n.tipo === "categoria") {
        var dentro = n.voci.filter(function (id) { return inBarra(voci[id]); }).length;
        if (!dentro && (S.persona || S.ruolo !== "tutti")) return; // tendina vuota: nella barra non c'è
        b = el("button", { type: "button", "class": "mp-barra-el" + (scelto("categoria", n.id) ? " scelta" : "") + (dentro ? "" : " vuota"),
          title: dentro ? dentro + " voci nella tendina" : "Tendina vuota: oggi non compare",
          onclick: function () { scegli("categoria", n.id, true); } },
          [el("span", { testo: n.nome }), el("span", { "class": "mp-barra-freccia", html: ICO.freccia })]);
      } else {
        var v = voci[n.id];
        if (!inBarra(v) && (S.persona || S.ruolo !== "tutti" || !v.visibile)) return;
        b = el("button", { type: "button", "class": "mp-barra-el" + (scelto("voce", v.id) ? " scelta" : ""),
          onclick: function () { scegli("voce", v.id, true); } }, [el("span", { testo: v.nome })]);
      }
      trascinabile(b, n, D.barra, salvaBarra);
      box.appendChild(b);
    });
    if (!box.children.length) box.appendChild(el("span", { "class": "mp-barra-vuota", testo: "Non vede nessuna voce." }));
  }

  /* ── il contenuto di ogni tendina ────────────────────── */
  function rigaVoce(v, lista, livello) {
    var mostra = vede(v);
    var classi = "mp-voce" + (livello ? " mp-voce-sotto" : "") + (scelto("voce", v.id) ? " scelta" : "") + (!mostra || !v.visibile ? " sbiadita" : "");
    var stato = null;
    if (!v.visibile) stato = el("span", { "class": "mp-voce-stato", html: ICO.occhioNo + " tolta dal menu" });
    else if (!mostra) stato = el("span", { "class": "mp-voce-stato", html: ICO.occhioNo + " non la vede" });
    var btn = el("button", { type: "button", "class": classi, "data-id": v.id, onclick: function () { scegli("voce", v.id); } }, [
      lista ? el("span", { "class": "mp-maniglia", html: ICO.maniglia, title: "Trascina per riordinare" }) : null,
      el("span", { "class": "mp-voce-icona", html: v.icona_html || "" }),
      el("span", { "class": "mp-voce-nome", testo: v.nome }),
      stato,
      v.problema ? el("span", { "class": "mp-pallino", "aria-label": "Da sistemare", title: "Da sistemare" }) : null,
    ]);
    if (lista) trascinabile(btn, v.id, lista, salvaLista(lista));
    var li = el("li", {}, [btn]);
    if (v.figli && v.figli.length) {
      var sotto = el("ul", { "class": "mp-lista mp-sottovoci" }, [
        el("li", { "class": "mp-sottovoci-nota", html: ICO.sotto + "<span>nella barra delle sue pagine</span>" }),
      ]);
      v.figli.forEach(function (id) { sotto.appendChild(rigaVoce(voci[id], v.figli, 1)); });
      li.appendChild(sotto);
    }
    return li;
  }

  function bloccoCategoria(n) {
    var dentro = n.voci.filter(function (id) { return inBarra(voci[id]); }).length;
    var testa = el("button", { type: "button", "class": "mp-cat-testa" + (scelto("categoria", n.id) ? " scelta" : ""),
      onclick: function () { scegli("categoria", n.id); } }, [
      el("span", { "class": "mp-cat-icona", html: n.icona_html || ICO.cartella }),
      el("span", { "class": "mp-cat-nome", testo: n.nome }),
      el("span", { "class": "mp-cat-conta", testo: n.voci.length ? dentro + " di " + n.voci.length : "vuota" }),
    ]);
    var corpo = el("div", { "class": "mp-cat-corpo" });
    if (!n.voci.length) {
      corpo.appendChild(el("p", { "class": "mp-nota mp-cat-vuota", testo: "Nessuna voce: nella barra non compare." }));
    }
    sezioni(n.voci).forEach(function (s) {
      if (s.nome) corpo.appendChild(el("div", { "class": "mp-gruppo", testo: s.nome }));
      var ul = el("ul", { "class": "mp-lista" });
      s.voci.forEach(function (id) { ul.appendChild(rigaVoce(voci[id], n.voci, 0)); });
      corpo.appendChild(ul);
    });
    return el("section", { "class": "mp-cat", id: "mp-cat-" + n.id }, [testa, corpo]);
  }

  function disegnaAlbero() {
    var box = document.getElementById("mp-aree");
    box.innerHTML = "";
    var sole = [];
    D.barra.forEach(function (n) {
      if (n.tipo === "categoria") box.appendChild(bloccoCategoria(n));
      else sole.push(n.id);
    });
    if (sole.length) {
      var ul = el("ul", { "class": "mp-lista" });
      // L'ordine delle voci da sole si cambia nella barra qui sopra, insieme alle tendine.
      sole.forEach(function (id) { ul.appendChild(rigaVoce(voci[id], null, 0)); });
      box.appendChild(el("section", { "class": "mp-cat mp-cat-sole" }, [
        el("div", { "class": "mp-cat-testa mp-cat-testa-fissa" }, [
          el("span", { "class": "mp-cat-nome", testo: "Da sole nella barra" }),
          el("span", { "class": "mp-cat-conta", testo: "senza tendina" }),
        ]),
        el("div", { "class": "mp-cat-corpo" }, [ul]),
      ]));
    }
    (D.orfani || []).forEach(function (o) {
      var ul = el("ul", { "class": "mp-lista" });
      o.voci.forEach(function (id) { ul.appendChild(rigaVoce(voci[id], o.voci, 1)); });
      box.appendChild(el("section", { "class": "mp-cat mp-cat-sole" }, [
        el("div", { "class": "mp-cat-testa mp-cat-testa-fissa" }, [
          el("span", { "class": "mp-cat-nome", testo: "Sottovoci senza voce nel menu" }),
          el("span", { "class": "mp-cat-conta", testo: "pagine «" + o.app + "»" }),
        ]),
        el("div", { "class": "mp-cat-corpo" }, [el("p", { "class": "mp-nota mp-cat-vuota", testo: "Compaiono solo dentro queste pagine: nella barra in alto nessuna voce ci porta." }), ul]),
      ]));
    });
  }

  /* ── scheda ──────────────────────────────────────────── */
  function scegli(tipo, id, scorri) {
    S.scelta = { tipo: tipo, id: id };
    aggiornaTutto();
    if (scorri) {
      var bersaglio = tipo === "categoria" ? document.getElementById("mp-cat-" + id) : document.querySelector('.mp-voce[data-id="' + id + '"]');
      if (bersaglio) bersaglio.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function chipsRuoli(ids) {
    return el("div", { "class": "mp-chips" }, ids.map(function (id) { return (ruoliById[id] || {}).nome; }).filter(Boolean).map(function (n) {
      return el("span", { "class": "mp-chip", testo: n });
    }));
  }

  function risposta(v) {
    var box = el("div", { "class": "mp-risposta" });
    var titolo; var testo; var chips = null; var si = true;
    if (S.persona) {
      var p = S.persona.voci[String(v.id)] || { vede: false, perche: "" };
      si = p.vede;
      titolo = S.persona.nome + (si ? " la vede" : " non la vede");
      testo = p.perche;
    } else if (S.ruolo === "tutti") {
      // v.ruoli comprende anche i ruoli amministratore: contano solo gli altri.
      var nonAdmin = v.ruoli.filter(function (id) { return ruoliById[id]; });
      si = nonAdmin.length > 0;
      titolo = v.tutti ? "La vedono tutti" : (si ? "La vedono questi ruoli" : "La vedono solo gli amministratori");
      if (v.esterno) testo = v.tutti ? "È un link a un sito esterno senza permesso: lo trova nel menu ogni persona del portale." : (si ? "Chi ha il permesso scelto per il link:" : "Nessun ruolo del portale ha il permesso scelto per il link.");
      else testo = v.tutti ? "Ogni persona del portale può aprire la pagina, quindi trova la voce nel menu." : (si ? "Chi può aprire la pagina a cui porta:" : "Nessun ruolo del portale può aprire la pagina a cui porta.");
      if (si && !v.tutti) chips = chipsRuoli(nonAdmin);
    } else {
      var nome = nomeVista();
      si = v.ruoli.indexOf(S.ruolo) >= 0;
      titolo = nome + (si ? " la vede" : " non la vede");
      if (si) testo = v.esterno ? "Il link esterno lo vede." : "Può aprire la pagina a cui porta, quindi la trova nel menu.";
      else {
        var altri = v.ruoli.map(function (id) { return (ruoliById[id] || {}).nome; }).filter(Boolean);
        testo = (v.esterno ? "Non ha il permesso scelto per il link, quindi la voce non compare." : "Non può aprire la pagina a cui porta, quindi la voce non compare.") + (altri.length ? " La vedono: " + altri.join(", ") + "." : "");
      }
    }
    if (!v.visibile) { si = false; titolo = "Tolta dal menu"; testo = "Non la vede nessuno finché non la rimetti nel menu."; chips = null; }
    box.classList.toggle("si", si);
    box.appendChild(el("div", { "class": "mp-risposta-titolo", html: (si ? ICO.si : ICO.occhioNo.replace(/14/g, "22")) }, []));
    box.firstChild.appendChild(document.createTextNode(" " + titolo));
    if (testo) box.appendChild(el("div", { "class": "mp-risposta-testo", testo: testo }));
    if (chips) box.appendChild(chips);
    return box;
  }

  function problema(v) {
    if (!v.problema) return null;
    var azione;
    if (v.problema.tipo === "vecchio") {
      azione = el("button", { type: "button", "class": "mp-btn mp-btn-warn", testo: v.problema.rimedio, onclick: function () {
        post(url.urlSistema, { id: v.id }).then(function () { ricarica("Sistemata: ora la voce segue la pagina."); })
          .catch(function (err) { avviso(err.message, "error"); });
      } });
    } else if (v.problema.tipo === "nessuno") {
      azione = el("a", { "class": "mp-btn mp-btn-light", href: url.urlRuoli, testo: "Apri Ruoli e permessi" });
    }
    return el("div", { "class": "mp-problema" }, [
      el("div", { "class": "mp-problema-testo" }, [el("strong", { testo: v.problema.titolo }), v.problema.testo]),
      azione,
    ]);
  }

  function testa(iconaBox, sopra, nome, destra) {
    return el("div", { "class": "mp-scheda-testa" }, [
      iconaBox,
      el("div", { "class": "mp-scheda-nomi" }, [
        el("div", { "class": "mp-scheda-area", testo: sopra }),
        el("h2", { "class": "mp-scheda-nome", testo: nome }),
      ]),
      destra,
    ]);
  }

  function campoDove(v, bozza) {
    if (v.sezione === "subnav") {
      var perCat = {};
      (D.moduli || []).forEach(function (m) { (perCat[m.categoria || "Da sole nella barra"] = perCat[m.categoria || "Da sole nella barra"] || []).push(m); });
      var sel = el("select", { onchange: function (e) { bozza.padre = e.target.value; } },
        Object.keys(perCat).map(function (c) {
          return el("optgroup", { label: c }, perCat[c].map(function (m) { return el("option", { value: m.app, selected: m.app === v.padre, testo: m.nome }); }));
        }));
      if (!nomeApp[v.padre]) sel.insertBefore(el("option", { value: v.padre, selected: true, testo: "(pagine «" + v.padre + "»)" }), sel.firstChild);
      return el("label", { "class": "mp-campo" }, ["Sotto quale voce", sel,
        el("span", { "class": "mp-nota", testo: "Compare nella barra dentro le pagine di quella voce." })]);
    }
    var lista = el("datalist", { id: "mp-gruppi-" + v.id });
    var gruppo = el("input", { type: "text", value: v.gruppo, maxlength: "80", list: "mp-gruppi-" + v.id, placeholder: "nessuno",
      oninput: function (e) { bozza.gruppo = e.target.value; } });
    var rigaGruppo = el("div", { "class": "mp-sottocampo" }, ["Sottogruppo nella tendina", gruppo, lista]);
    function riempiGruppi() {
      var c = categorie[bozza.categoria];
      lista.innerHTML = "";
      ((c && c.gruppi) || []).forEach(function (g) { lista.appendChild(el("option", { value: g })); });
      rigaGruppo.hidden = !c;
    }
    var sel2 = el("select", { onchange: function (e) { bozza.categoria = e.target.value ? parseInt(e.target.value, 10) : null; riempiGruppi(); } },
      [el("option", { value: "", selected: !v.categoria, testo: "Nessuna: da sola nella barra" })].concat(
        D.barra.filter(function (n) { return n.tipo === "categoria"; }).map(function (c) {
          return el("option", { value: c.id, selected: c.id === v.categoria, testo: "Tendina «" + c.nome + "»" });
        })));
    riempiGruppi();
    return el("label", { "class": "mp-campo" }, ["In quale categoria", sel2, rigaGruppo]);
  }

  function esternoUrl(indirizzo) { return /^https?:\/\//i.test(String(indirizzo || "").trim()); }

  /* Pagina del portale (dall'elenco) -> route_name; altrimenti l'indirizzo cosi' com'e'. */
  function destinazione(indirizzo) {
    var opt = Array.prototype.find.call(document.querySelectorAll("#mp-pagine option"), function (o) { return o.value === indirizzo; });
    return opt ? { route_name: opt.dataset.route } : { route_name: "", url_path: indirizzo };
  }

  function campiIndirizzo(v, bozza) {
    var selPermesso = el("select", { onchange: function (e) { bozza.permesso = e.target.value; } },
      [el("option", { value: "", selected: !v.permesso, testo: "Tutti: nessun permesso" })]);
    var perModulo = {};
    (D.permessi || []).forEach(function (p) { (perModulo[p.modulo] = perModulo[p.modulo] || []).push(p); });
    Object.keys(perModulo).forEach(function (m) {
      selPermesso.appendChild(el("optgroup", { label: m }, perModulo[m].map(function (p) {
        return el("option", { value: p.code, selected: p.code === v.permesso, testo: p.nome });
      })));
    });
    if (v.permesso && !(D.permessi || []).some(function (p) { return p.code === v.permesso; })) {
      selPermesso.insertBefore(el("option", { value: v.permesso, selected: true, testo: v.permesso + " (non protegge più nessuna pagina)" }), selPermesso.children[1] || null);
    }
    var rigaPermesso = el("label", { "class": "mp-campo" }, ["Chi vede il link esterno", selPermesso,
      el("span", { "class": "mp-nota", testo: "Lo vede chi ha questo permesso in «Ruoli e permessi» (gli amministratori sempre). «Tutti» = ogni persona del portale." })]);
    function aggiorna() { rigaPermesso.hidden = !esternoUrl(bozza.indirizzo); }
    var campo = el("input", { type: "text", id: "mp-indirizzo-" + v.id, value: v.indirizzo, list: "mp-pagine", maxlength: "500", placeholder: "es. /tickets/ oppure https://…",
      oninput: function (e) { bozza.indirizzo = e.target.value.trim(); aggiorna(); } });
    var spunta = el("input", { type: "checkbox", checked: v.nuova_scheda, onchange: function (e) { bozza.nuova_scheda = e.target.checked; } });
    aggiorna();
    return [
      el("div", { "class": "mp-campo" }, [el("label", { "for": "mp-indirizzo-" + v.id, testo: "Pagina a cui porta" }), campo,
        el("span", { "class": "mp-nota", testo: "Una pagina del portale dall'elenco, oppure un indirizzo esterno (https://…)." }),
        el("label", { "class": "mp-spunta" }, [spunta, "Apri in una nuova scheda"])]),
      rigaPermesso,
    ];
  }

  function schedaVoce(box, v) {
    var bozza = { nome: v.nome, icona: v.icona, categoria: v.categoria, gruppo: v.gruppo, padre: v.padre,
      indirizzo: v.indirizzo, nuova_scheda: v.nuova_scheda, permesso: v.permesso };
    var interruttore = el("button", {
      type: "button", "class": "mp-interruttore", "aria-pressed": v.visibile ? "true" : "false",
      testo: v.visibile ? "Nel menu" : "Tolta dal menu",
      onclick: function () {
        var nuovo = !v.visibile;
        post(url.urlSalva, { id: v.id, visibile: nuovo }).then(function () {
          v.visibile = nuovo; avviso(nuovo ? "Rimessa nel menu." : "Tolta dal menu."); aggiornaTutto();
        }).catch(function (err) { avviso(err.message, "error"); });
      },
    });
    var iconaBox = el("div", { "class": "mp-scheda-icona", html: v.icona_html || "" });
    box.appendChild(testa(iconaBox, dove(v), v.nome, interruttore));
    box.appendChild(risposta(v));
    var pr = problema(v); if (pr) box.appendChild(pr);

    var campoNome = el("input", { type: "text", value: v.nome, maxlength: "120", disabled: v.nome_da_branding, oninput: function (e) { bozza.nome = e.target.value; } });
    var notaNome = v.nome_da_branding ? el("span", { "class": "mp-nota" }, ["Il nome di questo modulo si cambia in ", el("a", { href: url.urlBranding, testo: "Branding" }), "."]) : null;
    var azioneIcona = el("button", { type: "button", "class": "mp-azione", html: ICO.immagine + "<span>Cambia l'icona<small>scegli dalla galleria</small></span>",
      onclick: function () { apriIcone(function (nome, html) { bozza.icona = nome; iconaBox.innerHTML = html; }); } });
    var azionePersona;
    if (S.persona) {
      var p = S.persona.voci[String(v.id)] || {};
      azionePersona = el("button", { type: "button", "class": "mp-azione",
        html: ICO.persona + "<span>" + (p.nascosta_a_lui ? "Rimettila a " : "Nascondila solo a ") + "<b></b><small>le altre persone non cambiano</small></span>",
        onclick: function () {
          post(url.urlNascondi.replace("/0/", "/" + S.persona.id + "/"), { item_id: v.id, state: p.nascosta_a_lui ? "inherit" : "hide" })
            .then(function () { avviso("Fatto."); return caricaPersona(S.persona.id, S.persona.nome); })
            .catch(function (err) { avviso(err.message, "error"); });
        } });
      azionePersona.querySelector("b").textContent = S.persona.nome;
    } else {
      azionePersona = el("button", { type: "button", "class": "mp-azione",
        html: ICO.persona + "<span>Nascondila a una persona sola<small>scegli prima la persona in alto, in «Guarda il menu come»</small></span>",
        onclick: function () { inputPersona.focus(); } });
    }
    var apri = v.href ? el("a", { "class": "mp-azione", href: v.href, target: "_blank", rel: "noopener", html: ICO.apri + "<span>Apri la pagina<small></small></span>" }) : null;
    if (apri) apri.querySelector("small").textContent = v.href;

    box.appendChild(el("div", {}, [
      el("div", { "class": "mp-fare-titolo", testo: "Cosa vuoi fare" }),
      el("div", { "class": "mp-fare" }, [
        el("label", { "class": "mp-campo" }, ["Cambia il nome", campoNome, notaNome]),
        campoDove(v, bozza),
      ].concat(campiIndirizzo(v, bozza), [azioneIcona, azionePersona, apri])),
    ]));

    var salva = el("button", { type: "button", "class": "mp-btn mp-btn-primary", testo: "Salva", onclick: function () {
      var dati = { id: v.id, icona: bozza.icona };
      if (!v.nome_da_branding) dati.nome = bozza.nome;
      if (v.sezione === "subnav") dati.padre = bozza.padre;
      else { dati.categoria = bozza.categoria; dati.gruppo = bozza.categoria ? bozza.gruppo : ""; }
      if (!bozza.indirizzo) { avviso("Scrivi la pagina a cui porta la voce.", "error"); return; }
      if (bozza.indirizzo !== v.indirizzo) Object.assign(dati, destinazione(bozza.indirizzo));
      dati.nuova_scheda = !!bozza.nuova_scheda;
      if (esternoUrl(bozza.indirizzo)) dati.permesso = bozza.permesso || "";
      salva.disabled = true;
      post(url.urlSalva, dati).then(function () { ricarica("Salvato."); })
        .catch(function (err) { salva.disabled = false; avviso(err.message, "error"); });
    } });
    var piedeTesto = el("span", { "class": "mp-piede-testo" }, [v.esterno ? "Chi vede il link lo decide il permesso scelto sopra; chi ha quel permesso si cambia in " : "Chi la vede dipende da chi può aprire la pagina. Per cambiarlo: ", el("a", { href: url.urlRuoli, testo: "Ruoli e permessi" }), "."]);
    box.appendChild(el("div", { "class": "mp-piede" }, [piedeTesto, salva]));
  }

  function schedaCategoria(box, c) {
    var bozza = { nome: c.nome, icona: c.icona };
    var dentro = c.voci.map(function (id) { return voci[id]; });
    var visibili = dentro.filter(inBarra);
    var iconaBox = el("div", { "class": "mp-scheda-icona", html: c.icona_html || ICO.cartella });
    box.appendChild(testa(iconaBox, "Categoria: una tendina nella barra in alto", c.nome, null));

    var r = el("div", { "class": "mp-risposta" + (visibili.length ? " si" : "") });
    var titolo; var testo; var chips = null;
    var vista = nomeVista();
    if (!c.voci.length) { titolo = "È vuota"; testo = "Una categoria senza voci non compare nella barra. Spostaci una voce o eliminala."; }
    else if (vista) {
      titolo = visibili.length ? vista + " la vede, con " + visibili.length + (visibili.length === 1 ? " voce" : " voci") : vista + " non la vede";
      testo = visibili.length ? "Nella tendina trova solo le voci che può aprire." : "Non può aprire nessuna delle pagine dentro, quindi la tendina non compare.";
    } else {
      var ruoli = {}; var tutti = false;
      dentro.forEach(function (v) { if (v.visibile) { v.ruoli.forEach(function (id) { ruoli[id] = 1; }); if (v.tutti) tutti = true; } });
      var ids = Object.keys(ruoli).map(Number).filter(function (id) { return ruoliById[id]; });
      titolo = tutti ? "La vedono tutti" : (ids.length ? "La vedono questi ruoli" : "La vedono solo gli amministratori");
      testo = "La tendina compare a chi può aprire almeno una delle sue voci; dentro, ognuno trova solo le sue.";
      if (!tutti && ids.length) chips = chipsRuoli(ids);
    }
    r.appendChild(el("div", { "class": "mp-risposta-titolo", html: visibili.length ? ICO.si : ICO.occhioNo.replace(/14/g, "22") }));
    r.firstChild.appendChild(document.createTextNode(" " + titolo));
    r.appendChild(el("div", { "class": "mp-risposta-testo", testo: testo }));
    if (chips) r.appendChild(chips);
    box.appendChild(r);

    if (c.voci.length) {
      var anteprima = el("div", { "class": "mp-tendina", "aria-label": "Anteprima della tendina" });
      sezioni(c.voci).forEach(function (s) {
        if (s.nome) anteprima.appendChild(el("div", { "class": "mp-tendina-gruppo", testo: s.nome }));
        s.voci.forEach(function (id) {
          var v = voci[id];
          anteprima.appendChild(el("button", { type: "button", "class": "mp-tendina-voce" + (inBarra(v) ? "" : " sbiadita"),
            onclick: function () { scegli("voce", v.id, true); } }, [
            el("span", { "class": "mp-voce-icona", html: v.icona_html || "" }), el("span", { testo: v.nome }),
          ]));
        });
      });
      box.appendChild(el("div", {}, [el("div", { "class": "mp-fare-titolo", testo: "Così si apre la tendina" }), anteprima,
        el("p", { "class": "mp-nota", testo: "I sottogruppi si scelgono nella scheda di ogni voce; l'ordine si cambia trascinando le voci a sinistra." })]));
    }

    var campoNome = el("input", { type: "text", value: c.nome, maxlength: "80", oninput: function (e) { bozza.nome = e.target.value; } });
    var azioneIcona = el("button", { type: "button", "class": "mp-azione", html: ICO.immagine + "<span>Cambia l'icona<small>si vede nel menu laterale e qui</small></span>",
      onclick: function () { apriIcone(function (nome, html) { bozza.icona = nome; iconaBox.innerHTML = html; }); } });
    var elimina = el("button", { type: "button", "class": "mp-azione", disabled: c.voci.length > 0,
      html: ICO.cestino + "<span>Elimina la categoria<small>" + (c.voci.length ? "prima sposta le sue voci in un'altra categoria" : "è vuota, si può togliere") + "</small></span>",
      onclick: function () {
        post(url.urlCatElimina, { id: c.id }).then(function () { ricarica("Categoria eliminata.", null); })
          .catch(function (err) { avviso(err.message, "error"); });
      } });
    box.appendChild(el("div", {}, [
      el("div", { "class": "mp-fare-titolo", testo: "Cosa vuoi fare" }),
      el("div", { "class": "mp-fare" }, [el("label", { "class": "mp-campo" }, ["Cambia il nome", campoNome]), azioneIcona, elimina]),
    ]));
    var salva = el("button", { type: "button", "class": "mp-btn mp-btn-primary", testo: "Salva", onclick: function () {
      salva.disabled = true;
      post(url.urlCatSalva, { id: c.id, nome: bozza.nome, icona: bozza.icona }).then(function () { ricarica("Salvato."); })
        .catch(function (err) { salva.disabled = false; avviso(err.message, "error"); });
    } });
    box.appendChild(el("div", { "class": "mp-piede" }, [
      el("span", { "class": "mp-piede-testo", testo: "Per cambiare la posizione nella barra trascina la tendina nella barra qui sopra." }), salva]));
  }

  function disegnaScheda() {
    var box = document.getElementById("mp-scheda");
    box.innerHTML = "";
    if (S.scelta && S.scelta.tipo === "categoria" && categorie[S.scelta.id]) return schedaCategoria(box, categorie[S.scelta.id]);
    var v = S.scelta && voci[S.scelta.id];
    if (!v) {
      box.appendChild(el("p", { "class": "mp-sub", testo: "Scegli una voce o una categoria per vedere chi la vede e cambiarla." }));
      return;
    }
    schedaVoce(box, v);
  }

  /* ── galleria icone ─────────────────────────────────── */
  var dlgIcone = document.getElementById("mp-icone");
  var sceltaIcona = null;
  function apriIcone(cb) { sceltaIcona = cb; dlgIcone.showModal(); }
  dlgIcone.querySelectorAll(".mp-icona").forEach(function (b) {
    b.addEventListener("click", function () { if (sceltaIcona) sceltaIcona(b.dataset.icona, b.innerHTML); dlgIcone.close(); });
  });

  /* ── aggiungi una voce / una categoria ──────────────── */
  var dlgNuova = document.getElementById("mp-nuova");
  var selNuovaCat = document.getElementById("mp-nuova-area");
  D.barra.filter(function (n) { return n.tipo === "categoria"; }).forEach(function (c) {
    selNuovaCat.appendChild(el("option", { value: c.id, testo: "Tendina «" + c.nome + "»" }));
  });
  selNuovaCat.appendChild(el("option", { value: "", testo: "Nessuna: da sola nella barra" }));
  document.getElementById("mp-aggiungi").addEventListener("click", function () {
    if (S.scelta && S.scelta.tipo === "categoria") selNuovaCat.value = String(S.scelta.id);
    else if (S.scelta && voci[S.scelta.id] && voci[S.scelta.id].categoria) selNuovaCat.value = String(voci[S.scelta.id].categoria);
    dlgNuova.showModal();
  });
  dlgNuova.querySelectorAll("[data-chiudi]").forEach(function (b) { b.addEventListener("click", function () { dlgNuova.close(); }); });
  document.getElementById("mp-nuova-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    var pagina = f.pagina.value.trim();
    var dati = Object.assign({ label: f.nome.value.trim(), section: "topbar" }, destinazione(pagina));
    post(url.urlCrea, dati).then(function (j) {
      return post(url.urlSalva, { id: j.id, categoria: f.categoria.value ? parseInt(f.categoria.value, 10) : null }).then(function () { return j; });
    }).then(function (j) { ricarica("Voce aggiunta.", { tipo: "voce", id: j.id }); })
      .catch(function (err) { avviso(err.message, "error"); });
  });

  var dlgCat = document.getElementById("mp-nuova-cat");
  document.getElementById("mp-aggiungi-cat").addEventListener("click", function () { dlgCat.showModal(); });
  dlgCat.querySelectorAll("[data-chiudi]").forEach(function (b) { b.addEventListener("click", function () { dlgCat.close(); }); });
  document.getElementById("mp-nuova-cat-form").addEventListener("submit", function (e) {
    e.preventDefault();
    post(url.urlCatSalva, { nome: e.target.nome.value.trim() })
      .then(function (j) { ricarica("Categoria creata: in fondo alla barra. Spostaci le voci dalla loro scheda.", { tipo: "categoria", id: j.id }); })
      .catch(function (err) { avviso(err.message, "error"); });
  });

  function aggiornaTutto() { disegnaRuoli(); disegnaProblemi(); disegnaBarra(); disegnaAlbero(); disegnaScheda(); }

  /* Dopo un salvataggio la pagina si ricarica: torna sulla stessa scelta. */
  var dopo = null;
  try { dopo = JSON.parse(sessionStorage.getItem("mp-dopo") || "null"); sessionStorage.removeItem("mp-dopo"); } catch (e) { dopo = null; }
  if (dopo && dopo.scelta && (dopo.scelta.tipo === "categoria" ? categorie[dopo.scelta.id] : voci[dopo.scelta.id])) S.scelta = dopo.scelta;
  if (!S.scelta) {
    var prima = Object.keys(voci).map(function (k) { return voci[k]; }).filter(function (v) { return v.problema; })[0];
    if (prima) S.scelta = { tipo: "voce", id: prima.id };
    else if (D.barra.length) S.scelta = { tipo: D.barra[0].tipo, id: D.barra[0].id };
  }
  aggiornaTutto();
  if (dopo && dopo.testo) avviso(dopo.testo);
})();
