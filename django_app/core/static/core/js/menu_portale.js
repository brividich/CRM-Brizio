/* Menu del portale (admin_portale/pages/menu_portale.html).
   Albero delle voci per area + scheda della voce scelta + «Guarda il menu come».
   I dati arrivano dal server (json_script #mp-dati); chi vede cosa lo calcola il server. */
(function () {
  "use strict";

  var root = document.getElementById("menu-portale");
  if (!root) return;
  var datiEl = document.getElementById("mp-dati");
  var D = JSON.parse(datiEl ? datiEl.textContent : "{}");
  var url = root.dataset;
  var csrf = (root.querySelector("input[name=csrfmiddlewaretoken]") || {}).value || "";

  var S = { ruolo: "tutti", persona: null, scelta: null };
  var voci = {};
  (D.aree || []).forEach(function (a) {
    a.voci.forEach(function (v) {
      v.area = a.nome; v.areaChiave = a.chiave; voci[v.id] = v;
      (v.figli || []).forEach(function (f) { f.area = a.nome + " › " + v.nome; f.areaChiave = a.chiave; f.padreNome = v.nome; voci[f.id] = f; });
    });
  });
  var ruoliById = {};
  (D.ruoli || []).forEach(function (r) { ruoliById[r.id] = r; });

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
    immagine: svg('<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>'),
    persona: svg('<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/><path d="M3 3l18 18"/>'),
    apri: svg('<path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>'),
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

  /* ── chi vede cosa nella vista scelta ───────────────── */
  function vede(v) {
    if (S.persona) { var p = S.persona.voci[String(v.id)]; return !!(p && p.vede); }
    if (S.ruolo === "tutti") return true;
    return v.ruoli.indexOf(S.ruolo) >= 0;
  }
  function nomeVista() {
    if (S.persona) return S.persona.nome;
    if (S.ruolo === "tutti") return "";
    return (ruoliById[S.ruolo] || {}).nome || "";
  }

  /* ── «Guarda il menu come» ───────────────────────────── */
  function disegnaRuoli() {
    var box = document.getElementById("mp-ruoli");
    box.innerHTML = "";
    function vai(id) { S.ruolo = id; S.persona = null; document.getElementById("mp-persona").value = ""; aggiornaTutto(); }
    var base = (D.ruoli || []).filter(function (r) { return r.base; })[0];
    var fissi = [{ id: "tutti", nome: "Tutti (amministratore)" }];
    if (base) fissi.push({ id: base.id, nome: base.nome + " (tutti)" });
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
      box.appendChild(el("button", { type: "button", testo: v.nome, onclick: function () { scegli(v.id); } }));
    });
  }

  /* ── albero ──────────────────────────────────────────── */
  function rigaVoce(v, fratelli) {
    var mostra = vede(v);
    var classi = "mp-voce" + (S.scelta === v.id ? " scelta" : "") + (!mostra || !v.visibile ? " sbiadita" : "");
    var stato = null;
    if (!v.visibile) stato = el("span", { "class": "mp-voce-stato", html: ICO.occhioNo + " tolta dal menu" });
    else if (!mostra) stato = el("span", { "class": "mp-voce-stato", html: ICO.occhioNo + " non la vede" });
    var btn = el("button", {
      type: "button", "class": classi, draggable: "true", "data-id": v.id,
      onclick: function () { scegli(v.id); },
    }, [
      el("span", { "class": "mp-maniglia", html: ICO.maniglia, title: "Trascina per riordinare" }),
      el("span", { "class": "mp-voce-icona", html: v.icona_html || "" }),
      el("span", { "class": "mp-voce-nome", testo: v.nome }),
      stato,
      v.problema ? el("span", { "class": "mp-pallino", "aria-label": "Da sistemare", title: "Da sistemare" }) : null,
    ]);
    trascinabile(btn, v, fratelli);
    var li = el("li", {}, [btn]);
    if (v.figli && v.figli.length) {
      var sotto = el("ul", { "class": "mp-lista" });
      v.figli.forEach(function (f) { sotto.appendChild(rigaVoce(f, v.figli)); });
      li.appendChild(sotto);
    }
    return li;
  }

  function disegnaAlbero() {
    var box = document.getElementById("mp-aree");
    box.innerHTML = "";
    var vista = nomeVista();
    document.getElementById("mp-albero-titolo").textContent = vista ? "Il menu di «" + vista + "»" : "Tutte le voci del menu";
    (D.aree || []).forEach(function (a) {
      var visibili = a.voci.filter(function (v) { return v.visibile && vede(v); }).length;
      var lista = el("ul", { "class": "mp-lista" });
      a.voci.forEach(function (v) { lista.appendChild(rigaVoce(v, a.voci)); });
      box.appendChild(el("div", { "class": "mp-area" }, [
        el("div", { "class": "mp-area-nome" }, [a.nome, el("span", { testo: visibili + " di " + a.voci.length })]),
        lista,
      ]));
    });
  }

  /* trascina e rilascia fra voci sorelle (stessa area o stesso modulo) */
  var trascinata = null;
  function trascinabile(btn, v, fratelli) {
    btn.addEventListener("dragstart", function (e) { trascinata = { v: v, fratelli: fratelli }; btn.classList.add("trascina"); e.dataTransfer.effectAllowed = "move"; });
    btn.addEventListener("dragend", function () { btn.classList.remove("trascina"); trascinata = null; });
    btn.addEventListener("dragover", function (e) {
      if (!trascinata || trascinata.fratelli !== fratelli || trascinata.v === v) return;
      e.preventDefault(); btn.classList.add("sopra");
    });
    btn.addEventListener("dragleave", function () { btn.classList.remove("sopra"); });
    btn.addEventListener("drop", function (e) {
      btn.classList.remove("sopra");
      if (!trascinata || trascinata.fratelli !== fratelli || trascinata.v === v) return;
      e.preventDefault();
      var da = fratelli.indexOf(trascinata.v);
      fratelli.splice(da, 1);
      fratelli.splice(fratelli.indexOf(v), 0, trascinata.v);
      disegnaAlbero();
      post(url.urlRiordina, { ordered_ids: fratelli.map(function (x) { return x.id; }) })
        .then(function () { avviso("Ordine salvato."); })
        .catch(function (err) { avviso(err.message, "error"); });
    });
  }

  /* ── scheda della voce ──────────────────────────────── */
  function scegli(id) { S.scelta = id; disegnaAlbero(); disegnaScheda(); }

  function risposta(v) {
    var box = el("div", { "class": "mp-risposta" });
    var titolo; var testo; var chips = null; var si = true;
    if (S.persona) {
      var p = S.persona.voci[String(v.id)] || { vede: false, perche: "" };
      si = p.vede;
      titolo = S.persona.nome + (si ? " la vede" : " non la vede");
      testo = p.perche;
    } else if (S.ruolo === "tutti") {
      var nomi = v.ruoli.map(function (id) { return (ruoliById[id] || {}).nome; }).filter(Boolean);
      si = nomi.length > 0;
      titolo = v.tutti ? "La vedono tutti" : (si ? "La vedono questi ruoli" : "La vedono solo gli amministratori");
      testo = v.tutti ? "Ogni persona del portale può aprire la pagina, quindi trova la voce nel menu." : (si ? "Chi può aprire la pagina a cui porta:" : "Nessun ruolo del portale può aprire la pagina a cui porta.");
      if (si && !v.tutti) chips = el("div", { "class": "mp-chips" }, nomi.map(function (n) { return el("span", { "class": "mp-chip", testo: n }); }));
    } else {
      var nome = nomeVista();
      si = v.ruoli.indexOf(S.ruolo) >= 0;
      titolo = nome + (si ? " la vede" : " non la vede");
      if (si) testo = "Può aprire la pagina a cui porta, quindi la trova nel menu.";
      else {
        var altri = v.ruoli.map(function (id) { return (ruoliById[id] || {}).nome; }).filter(Boolean);
        testo = "Non può aprire la pagina a cui porta, quindi la voce non compare." + (altri.length ? " La vedono: " + altri.join(", ") + "." : "");
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
        post(url.urlSistema, { id: v.id }).then(function () {
          avviso("Sistemata: ora la voce segue la pagina.");
          window.location.reload();
        }).catch(function (err) { avviso(err.message, "error"); });
      } });
    } else if (v.problema.tipo === "nessuno") {
      azione = el("a", { "class": "mp-btn mp-btn-light", href: url.urlRuoli, testo: "Apri Ruoli e permessi" });
    }
    return el("div", { "class": "mp-problema" }, [
      el("div", { "class": "mp-problema-testo" }, [el("strong", { testo: v.problema.titolo }), v.problema.testo]),
      azione,
    ]);
  }

  function disegnaScheda() {
    var box = document.getElementById("mp-scheda");
    box.innerHTML = "";
    var v = voci[S.scelta];
    if (!v) {
      box.appendChild(el("p", { "class": "mp-sub", testo: "Scegli una voce a sinistra per vedere chi la vede e cambiarla." }));
      return;
    }
    var bozza = { nome: v.nome, icona: v.icona, icona_html: v.icona_html, categoria: v.categoria, padre: v.padre };

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
    box.appendChild(el("div", { "class": "mp-scheda-testa" }, [
      iconaBox,
      el("div", { "class": "mp-scheda-nomi" }, [
        el("div", { "class": "mp-scheda-area", testo: v.sezione === "subnav" ? "dentro " + v.padreNome : "nell'area " + v.area }),
        el("h2", { "class": "mp-scheda-nome", testo: v.nome }),
      ]),
      interruttore,
    ]));

    box.appendChild(risposta(v));
    var pr = problema(v); if (pr) box.appendChild(pr);

    /* Cosa vuoi fare */
    var campoNome = el("input", { type: "text", value: v.nome, maxlength: "120", disabled: v.nome_da_branding, oninput: function (e) { bozza.nome = e.target.value; } });
    var notaNome = v.nome_da_branding ? el("span", { "class": "mp-nota" }, ["Il nome di questo modulo si cambia in ", el("a", { href: url.urlBranding, testo: "Branding" }), "."]) : null;
    var selArea;
    if (v.sezione === "subnav") {
      selArea = el("select", { onchange: function (e) { bozza.padre = e.target.value; } },
        (D.moduli || []).map(function (m) { return el("option", { value: m.code, selected: m.code === v.padre, testo: m.nome }); }));
    } else {
      selArea = el("select", { onchange: function (e) { bozza.categoria = e.target.value ? parseInt(e.target.value, 10) : null; } },
        [el("option", { value: "", selected: !v.categoria, testo: "Altre voci" })].concat(
          (D.categorie || []).map(function (c) { return el("option", { value: c.id, selected: c.id === v.categoria, testo: c.nome }); })));
    }
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
        el("label", { "class": "mp-campo" }, [v.sezione === "subnav" ? "Spostala sotto un altro modulo" : "Spostala in un'altra area", selArea]),
        azioneIcona, azionePersona, apri,
      ]),
    ]));

    var salva = el("button", { type: "button", "class": "mp-btn mp-btn-primary", testo: "Salva", onclick: function () {
      var dati = { id: v.id, icona: bozza.icona };
      if (!v.nome_da_branding) dati.nome = bozza.nome;
      if (v.sezione === "subnav") dati.padre = bozza.padre; else dati.categoria = bozza.categoria;
      salva.disabled = true;
      post(url.urlSalva, dati).then(function () {
        avviso("Salvato.");
        window.location.reload();
      }).catch(function (err) { salva.disabled = false; avviso(err.message, "error"); });
    } });
    var piedeTesto = el("span", { "class": "mp-piede-testo" }, ["Chi la vede dipende da chi può aprire la pagina. Per cambiarlo: ", el("a", { href: url.urlRuoli, testo: "Ruoli e permessi" }), "."]);
    box.appendChild(el("div", { "class": "mp-piede" }, [piedeTesto, salva]));
  }

  /* ── galleria icone ─────────────────────────────────── */
  var dlgIcone = document.getElementById("mp-icone");
  var sceltaIcona = null;
  function apriIcone(cb) { sceltaIcona = cb; dlgIcone.showModal(); }
  dlgIcone.querySelectorAll(".mp-icona").forEach(function (b) {
    b.addEventListener("click", function () { if (sceltaIcona) sceltaIcona(b.dataset.icona, b.innerHTML); dlgIcone.close(); });
  });

  /* ── aggiungi una voce ──────────────────────────────── */
  var dlgNuova = document.getElementById("mp-nuova");
  var selNuovaArea = document.getElementById("mp-nuova-area");
  (D.categorie || []).forEach(function (c) { selNuovaArea.appendChild(el("option", { value: c.id, testo: c.nome })); });
  selNuovaArea.appendChild(el("option", { value: "", testo: "Altre voci" }));
  document.getElementById("mp-aggiungi").addEventListener("click", function () { dlgNuova.showModal(); });
  dlgNuova.querySelectorAll("[data-chiudi]").forEach(function (b) { b.addEventListener("click", function () { dlgNuova.close(); }); });
  document.getElementById("mp-nuova-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var f = e.target;
    var pagina = f.pagina.value.trim();
    var opt = Array.prototype.find.call(document.querySelectorAll("#mp-pagine option"), function (o) { return o.value === pagina; });
    var dati = { label: f.nome.value.trim(), section: "topbar" };
    if (opt) dati.route_name = opt.dataset.route; else dati.url_path = pagina;
    post(url.urlCrea, dati).then(function (j) {
      return post(url.urlSalva, { id: j.id, categoria: f.categoria.value ? parseInt(f.categoria.value, 10) : null });
    }).then(function () {
      avviso("Voce aggiunta.");
      window.location.reload();
    }).catch(function (err) { avviso(err.message, "error"); });
  });

  function aggiornaTutto() { disegnaRuoli(); disegnaProblemi(); disegnaAlbero(); disegnaScheda(); }

  var prima = Object.keys(voci).map(function (k) { return voci[k]; }).filter(function (v) { return v.problema; })[0];
  S.scelta = prima ? prima.id : ((D.aree && D.aree[0] && D.aree[0].voci[0]) || {}).id || null;
  aggiornaTutto();
})();
