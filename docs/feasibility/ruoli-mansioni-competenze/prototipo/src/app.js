/* Prototipo RMC — logica.
   MOTORE (stesse regole di build/motore_rif.py): validita, livelloEfficace, valutaMansione,
   requisitiEffettivi, potenziali, quadro, impattoRevisione, simulaCambio.
   VISTE: una funzione per rotta, in fondo al file (oggetto VISTE). */
(function () {
  "use strict";
  var ORIGINALE = JSON.parse(document.getElementById("px-dati").textContent);
  var D = JSON.parse(JSON.stringify(ORIGINALE));
  var ORD = { "": 0, I: 1, L: 2, U: 3, O: 4 };
  var NOME_LV = { I: "In formazione", L: "Intermedio", U: "Autonomo", O: "Esperto / formatore" };
  var NOME_ST = { CONFORME: "Conforme", CON_RISERVA: "Conforme con riserva", SOTTO_SUPERVISIONE: "Sotto supervisione", NON_CONFORME: "Non conforme" };
  var NOME_VAL = { VALIDA: "valida", DA_CONFERMARE: "da confermare", IN_DEROGA: "in deroga", SOSPESA: "non più valida", ASSENTE: "mai valutata" };
  var NOME_CRIT = { B: "bloccante", I: "importante", U: "utile" };
  var stato = { vista: "PROPOSTA", msg: "", coda: null, bozza: null, filtri: { reparto: "", mansione: "", testo: "", soloGap: false } };

  /* ── Utilità ─────────────────────────────────────────────────────────── */
  function giorno(s) { var a = s.split("-"); return Date.UTC(+a[0], +a[1] - 1, +a[2]); }
  function giorniFra(a, b) { return Math.round((giorno(a) - giorno(b)) / 86400000); }
  function dataIt(s) { if (!s) return "—"; var a = s.split("-"); return a[2] + "/" + a[1] + "/" + a[0]; }
  function esc(t) { return String(t == null ? "" : t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function comp(id) { return D.competenze.filter(function (c) { return c.id === id; })[0]; }
  function mans(id) { return D.mansioni.filter(function (m) { return m.id === id; })[0]; }
  function pers(id) { return D.persone.filter(function (p) { return p.id === id; })[0]; }
  function nome(p) { return p.cognome.toUpperCase() + " " + p.nome; }
  function slug(p) { return "dipendente-" + p.cognome.toLowerCase(); }
  function blocco() { return D.parametri.modalita_validita === "BLOCCO"; }

  /* ── MOTORE ──────────────────────────────────────────────────────────── */
  function validita(p, cid) {
    var par = D.parametri, c = comp(cid), l = p.livelli[cid], oggi = D.oggi;
    if (!l) return { stato: "ASSENTE", motivo: "mai valutata", scadenza: null };
    var deroga = (p.deroghe || []).filter(function (d) { return d.competenza === cid && giorniFra(oggi, d.dal) >= 0 && giorniFra(d.fino_al, oggi) >= 0; })[0];
    var req = c.requisito;
    if (req) {
      if (!l.requisito_presente) return { stato: "SOSPESA", motivo: "manca " + req.nome, scadenza: null };
      if (l.requisito_scadenza) {
        var g = giorniFra(l.requisito_scadenza, oggi);
        if (g < 0) {
          if (deroga) return { stato: "IN_DEROGA", motivo: req.nome + " scaduto, deroga fino al " + dataIt(deroga.fino_al), scadenza: l.requisito_scadenza };
          if (-g <= par.grazia_requisito_giorni) return { stato: "DA_CONFERMARE", motivo: req.nome + " scaduto da " + (-g) + " giorni (periodo di grazia)", scadenza: l.requisito_scadenza };
          return { stato: "SOSPESA", motivo: req.nome + " scaduto da " + (-g) + " giorni", scadenza: l.requisito_scadenza };
        }
      }
    }
    if (c.esercizio_critico && l.ultimo_esercizio) {
      var mesi = giorniFra(oggi, l.ultimo_esercizio) / 30.44;
      if (mesi > par.finestra_esercizio_mesi) return { stato: "SOSPESA", motivo: "nessuna esecuzione da " + mesi.toFixed(0) + " mesi", scadenza: null };
      if (mesi >= par.preavviso_esercizio_mesi) return { stato: "DA_CONFERMARE", motivo: "nessuna esecuzione da " + mesi.toFixed(0) + " mesi", scadenza: null };
    }
    var mv = giorniFra(oggi, l.valutato_il) / 30.44;
    if (mv > par.conferma_periodica_mesi) return { stato: "DA_CONFERMARE", motivo: "conferma periodica scaduta (" + mv.toFixed(0) + " mesi)", scadenza: null };
    return { stato: "VALIDA", motivo: "", scadenza: req ? l.requisito_scadenza : null };
  }
  function livelloEfficace(p, cid) {
    var st = validita(p, cid).stato;
    if (st === "ASSENTE") return "";
    if (st === "SOSPESA" && blocco()) return "I";
    return p.livelli[cid].livello;
  }
  function valutaMansione(p, m, statoAss) {
    var righe = [], gB = 0, gI = 0, gU = 0, riserve = 0, segn = 0, ordB = [], ordT = [];
    m.requisiti.forEach(function (r) {
      var v = validita(p, r.competenza), eff = livelloEfficace(p, r.competenza);
      var gap = Math.max(0, ORD[r.minimo] - ORD[eff]);
      ordT.push(ORD[eff]); if (r.criticita === "B") ordB.push(ORD[eff]);
      if (gap) { if (r.criticita === "B") gB++; else if (r.criticita === "I") gI++; else gU++; }
      if (v.stato === "DA_CONFERMARE" || v.stato === "IN_DEROGA") riserve++;
      if (v.stato === "SOSPESA") { segn++; if (!blocco()) riserve++; }
      righe.push({ competenza: r.competenza, minimo: r.minimo, criticita: r.criticita, valutato: (p.livelli[r.competenza] || {}).livello || "", efficace: eff, validita: v.stato, motivo: v.motivo, scadenza: v.scadenza, gap: gap });
    });
    var min = function (a) { return a.length ? Math.min.apply(null, a) : 0; };
    var lm = ["", "I", "L", "U", "O"][ordB.length ? min(ordB) : min(ordT)];
    var st = (gB && statoAss === "EFFETTIVA") ? "NON_CONFORME" : (gB || gI) ? "SOTTO_SUPERVISIONE" : (gU || riserve) ? "CON_RISERVA" : "CONFORME";
    var opera = st === "CONFORME" || st === "CON_RISERVA";
    return { stato: st, livelloM: lm, righe: righe, opera: opera, firma: opera && ORD[lm] >= ORD[D.parametri.soglia_operativa], forma: st === "CONFORME" && lm === "O", gap: gB + gI + gU, segnalazioni: segn };
  }
  function requisitiEffettivi(p) {
    var peso = { U: 1, I: 2, B: 3 }, out = {};
    p.mansioni.forEach(function (a) {
      var m = mans(a.mansione);
      m.requisiti.forEach(function (r) {
        var e = out[r.competenza] || (out[r.competenza] = { competenza: r.competenza, minimo: r.minimo, criticita: r.criticita, fonti: [] });
        if (ORD[r.minimo] > ORD[e.minimo]) e.minimo = r.minimo;
        if (peso[r.criticita] > peso[e.criticita]) e.criticita = r.criticita;
        e.fonti.push({ mansione: m.id, nome: m.nome, minimo: r.minimo, criticita: r.criticita, versione: m.versione });
      });
    });
    return out;
  }
  function potenziali(p) {
    var ass = {}; p.mansioni.forEach(function (a) { ass[a.mansione] = 1; });
    var out = [];
    D.mansioni.forEach(function (m) {
      if (ass[m.id]) return;
      var ok = 0, mancaBI = 0;
      m.requisiti.forEach(function (r) {
        var basta = ORD[livelloEfficace(p, r.competenza)] >= ORD[r.minimo];
        if (basta) ok++; else if (r.criticita !== "U") mancaBI++;
      });
      if (mancaBI === 0) out.push({ mansione: m.id, nome: m.nome, esito: "SODDISFATTA", ok: ok, tot: m.requisiti.length });
      else if (ok > 0 && ok / m.requisiti.length >= D.parametri.soglia_potenziale_parziale) out.push({ mansione: m.id, nome: m.nome, esito: "PARZIALE", ok: ok, tot: m.requisiti.length });
    });
    return out;
  }
  function quadro() {
    var q = { stati: { CONFORME: 0, CON_RISERVA: 0, SOTTO_SUPERVISIONE: 0, NON_CONFORME: 0 }, gap: 0, segn: 0, sospese: 0, daConf: 0, scad: { s: 0, g30: 0, g60: 0, g90: 0 }, potS: 0, potP: 0, rep: {}, nonConf: {}, righeNC: [], righeScad: [] };
    Object.keys(D.reparti).forEach(function (r) { q.rep[r] = { CONFORME: 0, CON_RISERVA: 0, SOTTO_SUPERVISIONE: 0, NON_CONFORME: 0, tot: 0 }; });
    D.persone.forEach(function (p) {
      p.mansioni.forEach(function (a) {
        var m = mans(a.mansione), v = valutaMansione(p, m, a.stato);
        q.stati[v.stato]++; q.gap += v.gap; if (v.segnalazioni) q.segn++;
        q.rep[m.reparto][v.stato]++; q.rep[m.reparto].tot++;
        if (v.stato === "NON_CONFORME") { q.nonConf[p.id] = 1; q.righeNC.push({ p: p, m: m, v: v }); }
        else if (v.segnalazioni) q.righeNC.push({ p: p, m: m, v: v });
      });
      Object.keys(p.livelli).forEach(function (c) {
        var l = p.livelli[c], st = validita(p, c).stato;
        if (st === "SOSPESA") q.sospese++;
        if (st === "DA_CONFERMARE") q.daConf++;
        if (l.requisito_scadenza && l.requisito_presente) {
          var g = giorniFra(l.requisito_scadenza, D.oggi);
          if (g < 0) q.scad.s++; else if (g <= 30) q.scad.g30++; else if (g <= 60) q.scad.g60++; else if (g <= 90) q.scad.g90++;
          if (g <= 90) q.righeScad.push({ p: p, c: comp(c), g: g, quando: l.requisito_scadenza });
        }
      });
      potenziali(p).forEach(function (x) { if (x.esito === "SODDISFATTA") q.potS++; else q.potP++; });
    });
    q.assegnazioni = q.stati.CONFORME + q.stati.CON_RISERVA + q.stati.SOTTO_SUPERVISIONE + q.stati.NON_CONFORME;
    q.personeNC = Object.keys(q.nonConf).length;
    q.righeScad.sort(function (a, b) { return a.g - b.g; });
    return q;
  }
  function impattoRevisione(mid, requisitiNuovi) {
    var m = mans(mid), prima = m.requisiti, cambi = [], titolari = 0, stati = {};
    D.persone.forEach(function (p) {
      var a = p.mansioni.filter(function (x) { return x.mansione === mid; })[0];
      if (!a) return;
      titolari++;
      stati[p.id] = valutaMansione(p, m, a.stato).stato;
    });
    m.requisiti = requisitiNuovi;
    D.persone.forEach(function (p) {
      var a = p.mansioni.filter(function (x) { return x.mansione === mid; })[0];
      if (!a) return;
      var s2 = valutaMansione(p, m, a.stato).stato;
      if (s2 !== stati[p.id]) cambi.push({ p: p, prima: stati[p.id], dopo: s2 });
    });
    m.requisiti = prima;
    return { titolari: titolari, cambi: cambi };
  }
  function simulaCambio(pid, mid) {
    var p = pers(pid), m = mans(mid), v = valutaMansione(p, m, "AVVIATA");
    var attuali = {}; p.mansioni.forEach(function (a) { attuali[mans(a.mansione).mansione_rischio] = 1; });
    return { v: v, coperti: v.righe.filter(function (r) { return !r.gap; }), mancanti: v.righe.filter(function (r) { return r.gap; }), rischioNuovo: !attuali[m.mansione_rischio], rischio: m.mansione_rischio };
  }

  /* ── Pezzi di interfaccia ────────────────────────────────────────────── */
  function lv(l, titolo) { return '<span class="px-lv px-lv-' + (l || "0") + '" title="' + esc(titolo || (l ? NOME_LV[l] : "mai valutata")) + '">' + (l || "–") + "</span>"; }
  function st(s) { return '<span class="px-st px-st-' + s + '">' + NOME_ST[s] + "</span>"; }
  function ico(id) { return '<svg class="fmd-ico"><use href="#' + id + '"/></svg>'; }
  function kpi(valore, label, sub, tono, icona, href) {
    return '<a class="fmd-mtr kpi-link fmd-t-' + (tono || "navy") + '" href="' + (href || "#matrice") + '"><span class="fmd-ribbon"></span><div class="fmd-mtr-top"><span class="fmd-mtr-ic">' + ico(icona || "i-grid") + '</span><span class="fmd-mtr-val">' + valore + '</span></div><div class="fmd-mtr-lbl">' + label + "</div>" + (sub ? '<div class="fmd-mtr-sub">' + sub + "</div>" : "") + "</a>";
  }
  function testata(briciola, titolo, sotto, azioni) {
    return '<div class="fmd-pagehead"><div><div class="fmd-crumb"><a href="#cruscotto-qualita">Competenze</a><span class="fmd-sep"> / </span><span class="fmd-cur">' + esc(briciola) + "</span></div><h1>" + titolo + '</h1><p class="fmd-ph-sub">' + sotto + '</p></div><div class="fmd-pagehead-actions">' + (azioni || "") + '<a class="fmd-btn fmd-btn-ghost" href="#' + location.hash.slice(1) + '" title="Guida della pagina">? Guida</a></div></div>';
  }
  function interruttore() {
    return '<div class="px-barra"><span class="px-seg" role="group" aria-label="Confronto oggi e proposta"><button type="button" class="px-btn" data-vista="OGGI" aria-pressed="' + (stato.vista === "OGGI") + '">Oggi</button><button type="button" class="px-btn" data-vista="PROPOSTA" aria-pressed="' + (stato.vista === "PROPOSTA") + '">Proposta</button></span><span class="px-nota" style="margin:0">' + (stato.vista === "OGGI" ? "Com'è la pagina oggi nel portale." : "Come diventerebbe.") + "</span></div>";
  }
  function messaggio() { var m = stato.msg; stato.msg = ""; return '<div class="px-msg" role="status">' + esc(m) + "</div>"; }
  function selReparto() {
    return '<label>Reparto<select data-filtro="reparto"><option value="">Tutti</option>' + Object.keys(D.reparti).map(function (r) { return '<option value="' + r + '"' + (stato.filtri.reparto === r ? " selected" : "") + ">" + esc(D.reparti[r]) + "</option>"; }).join("") + "</select></label>";
  }
  function asIsLivello(p, m) {
    var b = m.requisiti.filter(function (r) { return r.criticita === "B"; });
    var v = (b.length ? b : m.requisiti).map(function (r) { return ORD[(p.livelli[r.competenza] || {}).livello || "I"]; });
    return ["", "I", "L", "U", "O"][Math.min.apply(null, v)];
  }

  /* ── Pannello «Perché?» ──────────────────────────────────────────────── */
  function apriPerche(pid, cid) {
    var p = pers(pid), c = comp(cid), l = p.livelli[cid], v = validita(p, cid), re = requisitiEffettivi(p)[cid];
    var h = '<button type="button" class="px-btn" data-chiudi style="float:right">Chiudi</button><h2>Perché?</h2><p class="px-nota">' + esc(nome(p)) + " · <b>" + esc(c.nome) + "</b></p>";
    h += "<h3>Che cosa è richiesto</h3>";
    if (re) {
      h += '<p style="font-size:13px;margin:0 0 6px">Livello atteso ' + lv(re.minimo) + " · " + NOME_CRIT[re.criticita] + (re.fonti.length > 1 ? " — vince la richiesta più severa fra " + re.fonti.length + " fonti" : "") + '</p><ul class="px-catena">';
      re.fonti.forEach(function (f) { h += "<li>Ruolo <b>" + esc(p.ruolo) + "</b> → mansione <b>" + esc(f.nome) + "</b> (profilo v" + f.versione + ") → chiede livello <b>" + f.minimo + "</b>, " + NOME_CRIT[f.criticita] + "</li>"; });
      h += "</ul>";
    } else h += '<p class="px-nota">Nessuna mansione assegnata la richiede: è una competenza posseduta in più.</p>';
    if (c.requisito) h += '<ul class="px-catena"><li>La competenza richiede: <b>' + esc(c.requisito.nome) + "</b>" + (c.requisito.validita_mesi ? " (validità " + c.requisito.validita_mesi + " mesi)" : " (una tantum)") + "</li></ul>";
    if (c.esercizio_critico) h += '<ul class="px-catena"><li>Competenza <b>a esercizio critico</b>: va eseguita almeno ogni ' + D.parametri.finestra_esercizio_mesi + " mesi</li></ul>";
    h += "<h3>Che cosa possiede</h3>";
    if (l) {
      h += '<p style="font-size:13px;margin:0">Livello valutato ' + lv(l.livello) + " il " + dataIt(l.valutato_il) + '</p><ul class="px-catena"><li>Sessione formativa <b>' + esc(l.sf) + "</b> · modalità <b>" + { P: "P esperienza verificata", A: "A affiancamento", C: "C corso" }[l.modalita] + "</b> · valutato da " + esc(l.valutato_da) + "</li>";
      if (l.requisito_scadenza) h += "<li>" + esc(c.requisito.nome) + ": scadenza <b>" + dataIt(l.requisito_scadenza) + "</b></li>";
      if (l.ultimo_esercizio) h += "<li>Ultima esecuzione: <b>" + dataIt(l.ultimo_esercizio) + "</b></li>";
      h += "</ul>";
    } else h += '<p class="px-nota">Mai valutata.</p>';
    h += '<h3>Esito</h3><p style="font-size:13px;margin:0"><span class="px-val px-val-' + v.stato + '">' + NOME_VAL[v.stato] + "</span>" + (v.motivo ? " — " + esc(v.motivo) : "") + "</p>";
    if (re) {
      var gap = ORD[re.minimo] - ORD[livelloEfficace(p, cid)];
      h += '<p style="font-size:13px">' + (gap > 0 ? "Manca: da <b>" + (livelloEfficace(p, cid) || "nessun livello") + "</b> a <b>" + re.minimo + "</b>. Serve una sessione formativa." : "Requisito raggiunto.") + "</p>";
    }
    if (v.stato === "SOSPESA") h += '<p class="px-nota">' + (blocco() ? "Modalità blocco: la competenza vale «I» finché non viene ripristinata." : "Modalità segnalazione: il livello resta; il responsabile deve prendere in carico la segnalazione.") + "</p>";
    var el = document.getElementById("px-perche");
    el.innerHTML = h; el.classList.add("px-on"); document.getElementById("px-velo").classList.add("px-on");
    el.querySelector("[data-chiudi]").focus();
  }
  function chiudiPerche() { document.getElementById("px-perche").classList.remove("px-on"); document.getElementById("px-velo").classList.remove("px-on"); }

  /* ── VISTE ───────────────────────────────────────────────────────────── */
  var TOUR = [
    ["cruscotto-qualita", "Cruscotto Qualità", "La Qualità vede in dieci secondi quante persone sono in regola, dove sono i problemi e che cosa scade."],
    ["matrice", "Matrice competenze", "Persone e competenze in una sola tabella: la lettera è il livello, il segno accanto dice se manca o va confermato. Un clic spiega il perché."],
    ["dipendente-rinaldi", "Scheda persona", "Per ogni persona: che cosa le è richiesto, che cosa possiede, che cosa manca e quali mansioni potrebbe già svolgere."],
    ["editor-mansione", "Profilo della mansione", "La Qualità cambia un requisito e vede subito quante persone cambierebbero stato, prima di pubblicare."],
    ["simulatore", "Simulatore cambio mansione", "Prima di chiedere una nuova mansione si vede che cosa è già coperto e che cosa resta da fare."],
    ["coda-car", "Coda del responsabile", "Il responsabile trova in un elenco le valutazioni da fare, le richieste e le segnalazioni da prendere in carico."],
    ["pianificatore", "Pianificatore della formazione", "Le mancanze diventano un piano: per ogni competenza chi va formato e con quale corso o tutor."],
    ["vista-dipendente", "La mia scheda", "Ogni persona vede le proprie mansioni, che cosa le manca e le prossime scadenze, anche da una postazione condivisa."]
  ];
  var VISTE = {};

  VISTE["cruscotto-qualita"] = function () {
    var q = quadro(), h = messaggio();
    h += testata("Cruscotto Qualità", ico("i-shield") + "Competenze: stato al " + dataIt(D.oggi), D.persone.length + " persone · " + D.mansioni.length + " mansioni · " + D.competenze.length + " competenze · " + q.assegnazioni + " mansioni assegnate");
    h += '<section class="fmd fmd-kpi fmd-kpi-auto" style="margin-bottom:16px">';
    h += kpi(q.stati.CONFORME, "Conformi", "su " + q.assegnazioni + " mansioni assegnate", "green", "i-check");
    h += kpi(q.stati.CON_RISERVA, "Conformi con riserva", "qualcosa da confermare", "yellow", "i-clock");
    h += kpi(q.stati.SOTTO_SUPERVISIONE, "Sotto supervisione", "in formazione", "orange", "i-users");
    h += kpi(q.stati.NON_CONFORME, "Non conformi", q.personeNC + " persone", "violet", "i-alert-tri");
    h += kpi(q.segn, "Segnalazioni gravi", "requisito non più valido", "amber", "i-alert-cir", "#coda-car");
    h += kpi(q.gap, "Mancanze aperte", "livelli sotto l'atteso", "cyan", "i-book", "#pianificatore");
    h += "</section>";
    h += '<section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-building") + 'Copertura per reparto</div><div class="fmd-block-aside">conformi e con riserva sul totale</div></div><div class="px-griglia">';
    Object.keys(D.reparti).forEach(function (r) {
      var x = q.rep[r], ok = x.CONFORME + x.CON_RISERVA, pc = function (n) { return x.tot ? (100 * n / x.tot).toFixed(1) : 0; };
      h += '<a class="fmd-cc" href="#matrice" data-vai-reparto="' + r + '"><span class="fmd-cc-h"><b>' + esc(D.reparti[r]) + '</b><span class="fmd-cc-code">' + r + '</span></span><span class="fmd-stk" role="img" aria-label="' + x.CONFORME + " conformi, " + x.CON_RISERVA + " con riserva, " + x.SOTTO_SUPERVISIONE + " sotto supervisione, " + x.NON_CONFORME + ' non conformi"><i class="fmd-k-ok" style="width:' + pc(x.CONFORME) + '%"></i><i class="fmd-k-s90" style="width:' + pc(x.CON_RISERVA) + '%"></i><i class="fmd-k-s30" style="width:' + pc(x.SOTTO_SUPERVISIONE) + '%"></i><i class="fmd-k-ko" style="width:' + pc(x.NON_CONFORME) + '%"></i></span><span class="fmd-stk-l"><span><b>' + ok + "</b> su " + x.tot + " in regola</span>" + (x.NON_CONFORME ? '<span class="fmd-pill fmd-pill-red">' + x.NON_CONFORME + " non conformi</span>" : "") + '</span><span class="fmd-cc-foot"><span class="fmd-muted">' + x.SOTTO_SUPERVISIONE + ' in formazione</span><span class="fmd-cc-go">Apri la matrice →</span></span></a>';
    });
    h += "</div></section>";
    h += '<div class="px-due"><section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-alert-tri") + 'Da sistemare per primi <span class="fmd-count">' + q.righeNC.length + '</span></div></div><div class="fmd-tablewrap"><table class="fmd-table"><thead><tr><th>Persona</th><th>Mansione</th><th>Stato</th><th>Che cosa manca</th></tr></thead><tbody>';
    q.righeNC.forEach(function (x) {
      var manca = x.v.righe.filter(function (r) { return r.gap || r.validita === "SOSPESA"; }).map(function (r) { return esc(comp(r.competenza).nome) + (r.validita === "SOSPESA" ? " (non più valida)" : " " + (r.efficace || "–") + "→" + r.minimo); }).join("; ");
      h += '<tr><td><a class="fmd-data-link" href="#' + slug(x.p) + '">' + esc(nome(x.p)) + '</a></td><td class="fmd-muted">' + esc(x.m.nome) + "</td><td>" + st(x.v.stato) + '</td><td class="fmd-muted" style="font-size:12.5px">' + manca + "</td></tr>";
    });
    h += '</tbody></table></div></section><section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-cal-clock") + 'Scadenze</div></div><div class="px-fatti" style="margin:0 0 10px"><span class="fmd-pill fmd-pill-red">' + q.scad.s + ' scadute</span><span class="fmd-pill fmd-pill-orange">' + q.scad.g30 + ' entro 30 gg</span><span class="fmd-pill fmd-pill-amber">' + q.scad.g60 + ' entro 60 gg</span><span class="fmd-pill fmd-pill-grey">' + q.scad.g90 + ' entro 90 gg</span></div><div class="fmd-tablewrap"><table class="fmd-table"><thead><tr><th>Persona</th><th>Requisito</th><th>Quando</th></tr></thead><tbody>';
    q.righeScad.forEach(function (x) { h += '<tr><td><a class="fmd-data-link" href="#' + slug(x.p) + '">' + esc(nome(x.p)) + '</a></td><td class="fmd-muted">' + esc(x.c.requisito.nome) + "</td><td>" + (x.g < 0 ? '<span class="fmd-pill fmd-pill-red">scaduto da ' + (-x.g) + " gg</span>" : dataIt(x.quando) + ' <span class="fmd-muted">(' + x.g + " gg)</span>") + "</td></tr>"; });
    h += "</tbody></table></div></section></div>";
    h += '<p class="px-nota">Mansioni potenziali: ' + q.potS + " con requisiti già soddisfatti, " + q.potP + " in buona parte. Dati inventati a scopo dimostrativo.</p>";
    return h;
  };

  VISTE["matrice"] = function () {
    var f = stato.filtri, h = messaggio() + testata("Matrice competenze", ico("i-grid") + "Matrice competenze", stato.vista === "OGGI" ? "Persone e mansioni: un livello per mansione, inserito a mano." : "Persone e competenze: livello valutato, validità e mancanze.") + interruttore();
    var persone = D.persone.filter(function (p) { return !f.reparto || p.reparto === f.reparto; }).filter(function (p) { return !f.testo || nome(p).toLowerCase().indexOf(f.testo.toLowerCase()) >= 0; });
    var mansioni = D.mansioni.filter(function (m) { return !f.reparto || m.reparto === f.reparto; });
    h += '<div class="px-barra">' + selReparto() + '<label>Mansione<select data-filtro="mansione"><option value="">Tutte</option>' + mansioni.map(function (m) { return '<option value="' + m.id + '"' + (f.mansione === m.id ? " selected" : "") + ">" + esc(m.nome) + "</option>"; }).join("") + '</select></label><label>Persona<input type="search" data-filtro="testo" value="' + esc(f.testo) + '" placeholder="Cerca per nome"></label>' + (stato.vista === "PROPOSTA" ? '<label style="flex-direction:row;align-items:center;gap:6px"><input type="checkbox" data-filtro="soloGap"' + (f.soloGap ? " checked" : "") + "> Solo chi ha mancanze</label>" : "") + "</div>";
    if (stato.vista === "OGGI") {
      h += '<p class="px-oggi">Oggi la skill matrix ha <b>una lettera per mansione</b>, scritta a mano dal responsabile. Non dice quali competenze mancano né se un requisito è scaduto.</p>';
      var cols = f.mansione ? mansioni.filter(function (m) { return m.id === f.mansione; }) : mansioni;
      h += '<div class="px-scroll"><table class="px-mtx"><thead><tr><th>Persona</th>' + cols.map(function (m) { return '<th class="px-col">' + esc(m.nome) + "</th>"; }).join("") + "</tr></thead><tbody>";
      persone.forEach(function (p) {
        h += '<tr><td><a class="fmd-data-link" href="#' + slug(p) + '">' + esc(nome(p)) + "</a></td>" + cols.map(function (m) { var a = p.mansioni.filter(function (x) { return x.mansione === m.id; })[0]; return "<td>" + (a ? lv(asIsLivello(p, m)) : "") + "</td>"; }).join("") + "</tr>";
      });
      return h + "</tbody></table></div>";
    }
    var ids = {};
    (f.mansione ? [mans(f.mansione)] : mansioni).forEach(function (m) { if (m) m.requisiti.forEach(function (r) { ids[r.competenza] = Math.max(ids[r.competenza] || 0, ORD[r.minimo]); }); });
    var colonne = Object.keys(ids).sort(), righe = 0;
    h += '<p class="px-prop">Ogni cella è il <b>livello valutato</b> della persona sulla competenza. <span class="px-mk px-mk-gap">▼</span> sotto il livello atteso · <span class="px-mk px-mk-ris">◐</span> da confermare o in deroga · <span class="px-mk px-mk-sosp">✕</span> non più valida. Clic sulla cella per il perché.</p>';
    var corpo = "";
    persone.forEach(function (p) {
      var re = requisitiEffettivi(p), haGap = false, celle = "";
      if (f.mansione && !p.mansioni.some(function (a) { return a.mansione === f.mansione; })) return;
      colonne.forEach(function (c) {
        var l = p.livelli[c], r = re[c];
        if (!l && !r) { celle += "<td></td>"; return; }
        var v = validita(p, c), eff = livelloEfficace(p, c), gap = r && ORD[eff] < ORD[r.minimo];
        if (gap) haGap = true;
        var mk = (gap ? '<span class="px-mk px-mk-gap" aria-hidden="true">▼</span>' : "") + (v.stato === "SOSPESA" ? '<span class="px-mk px-mk-sosp" aria-hidden="true">✕</span>' : (v.stato === "DA_CONFERMARE" || v.stato === "IN_DEROGA") ? '<span class="px-mk px-mk-ris" aria-hidden="true">◐</span>' : "");
        celle += '<td><button type="button" class="px-cell" data-perche="' + p.id + "|" + c + '" aria-label="' + esc(nome(p) + ", " + comp(c).nome + ": livello " + (l ? l.livello : "nessuno") + (r ? ", atteso " + r.minimo : "") + ", " + NOME_VAL[v.stato]) + '">' + lv(l ? l.livello : "") + mk + "</button></td>";
      });
      if (f.soloGap && !haGap) return;
      righe++;
      corpo += '<tr><td><a class="fmd-data-link" href="#' + slug(p) + '">' + esc(nome(p)) + '</a><span class="px-min">' + esc(D.reparti[p.reparto]) + "</span></td>" + celle + "</tr>";
    });
    h += '<div class="px-scroll"><table class="px-mtx"><thead><tr><th>Persona <span class="px-min" id="px-conta">' + righe + " persone</span></th>" + colonne.map(function (c) { return '<th class="px-col">' + esc(comp(c).nome) + '<span class="px-min">atteso ' + ["", "I", "L", "U", "O"][ids[c]] + "</span></th>"; }).join("") + "</tr></thead><tbody>" + corpo + "</tbody></table></div>";
    return h;
  };

  function vistaPersona(p) {
    var h = messaggio() + testata("Scheda persona", ico("i-users") + esc(nome(p)), esc(p.ruolo) + " · " + esc(D.reparti[p.reparto]) + " · in azienda dal " + dataIt(p.assunto_il), '<a class="fmd-btn fmd-btn-ghost" href="#simulatore" data-sim="' + p.id + '">Simula una nuova mansione</a>');
    h += '<div class="px-barra"><label>Persona<select data-vai-persona>' + D.persone.map(function (x) { return '<option value="' + slug(x) + '"' + (x.id === p.id ? " selected" : "") + ">" + esc(nome(x)) + "</option>"; }).join("") + "</select></label></div>" + interruttore();
    if (stato.vista === "OGGI") {
      h += '<p class="px-oggi">Oggi la scheda mostra le mansioni con un livello e un esito. «Cosa manca» riporta solo il livello sotto la soglia: le competenze non sono definite.</p>';
      h += '<section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-grid") + 'Mansioni <span class="fmd-count">' + p.mansioni.length + '</span></div></div><div class="fmd-tablewrap"><table class="fmd-table"><thead><tr><th>Mansione</th><th>Reparto</th><th>Livello</th><th>Esito</th><th>Cosa manca</th></tr></thead><tbody>';
      p.mansioni.forEach(function (a) {
        var m = mans(a.mansione), l = asIsLivello(p, m), ok = ORD[l] >= ORD.U;
        h += "<tr><td><b>" + esc(m.nome) + '</b></td><td class="fmd-muted">' + esc(D.reparti[m.reparto]) + "</td><td>" + lv(l) + "</td><td>" + (ok ? '<span class="fmd-badge fmd-b-green">abilitato</span>' : '<span class="fmd-badge fmd-b-amber">in addestramento</span>') + '</td><td class="fmd-muted" style="font-size:12.5px">' + (ok ? "—" : "livello " + l + " sotto la soglia") + "</td></tr>";
      });
      return h + "</tbody></table></div></section>";
    }
    h += '<section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-grid") + 'Mansioni <span class="fmd-count">' + p.mansioni.length + '</span></div></div><div class="px-griglia">';
    p.mansioni.forEach(function (a) {
      var m = mans(a.mansione), v = valutaMansione(p, m, a.stato);
      h += '<div class="px-card"><h3>' + esc(m.nome) + "</h3><div>" + st(v.stato) + ' <span class="fmd-badge ' + (a.stato === "AVVIATA" ? "fmd-b-amber" : "fmd-b-cyan") + '">' + (a.stato === "AVVIATA" ? "avviata · in formazione" : "effettiva") + '</span></div><div class="px-fatti"><span class="px-fatto">Livello sulla mansione ' + lv(v.livelloM) + '</span><span class="px-fatto ' + (v.opera ? "si" : "no") + '">lavora da sola</span><span class="px-fatto ' + (v.firma ? "si" : "no") + '">firma</span><span class="px-fatto ' + (v.forma ? "si" : "no") + '">forma i colleghi</span></div><p class="px-nota">Dal ' + dataIt(a.dal) + " · " + esc(a.ram === "impianto" ? "da impianto" : a.ram) + " · mansione di rischio: " + esc(m.mansione_rischio) + "</p></div>";
    });
    h += "</div></section>";
    var re = requisitiEffettivi(p), chiavi = Object.keys(re).sort();
    h += '<section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-clipboard") + 'Requisiti e competenze <span class="fmd-count">' + chiavi.length + '</span></div><div class="fmd-block-aside">che cosa è richiesto, che cosa possiede</div></div><div class="fmd-tablewrap"><table class="fmd-table"><thead><tr><th>Competenza</th><th>Atteso</th><th>Posseduto</th><th>Validità</th><th>Ultima evidenza</th><th>Esito</th><th></th></tr></thead><tbody>';
    chiavi.forEach(function (c) {
      var r = re[c], l = p.livelli[c], v = validita(p, c), gap = ORD[livelloEfficace(p, c)] < ORD[r.minimo];
      h += "<tr><td><b>" + esc(comp(c).nome) + '</b><div class="px-fonte">' + r.fonti.map(function (x) { return esc(x.nome); }).join(" · ") + "</div></td><td>" + lv(r.minimo) + ' <span class="fmd-muted">' + NOME_CRIT[r.criticita] + "</span></td><td>" + lv(l ? l.livello : "") + '</td><td><span class="px-val px-val-' + v.stato + '">' + NOME_VAL[v.stato] + "</span>" + (v.motivo ? '<div class="px-fonte">' + esc(v.motivo) + "</div>" : "") + '</td><td class="fmd-muted">' + (l ? esc(l.sf) + " · " + l.modalita + " · " + dataIt(l.valutato_il) : "—") + "</td><td>" + (gap ? '<span class="fmd-pill fmd-pill-red">manca</span>' : '<span class="fmd-badge fmd-b-green">raggiunto</span>') + '</td><td class="fmd-r"><button type="button" class="fmd-btn fmd-btn-ghost fmd-btn-mini" data-perche="' + p.id + "|" + c + '">Perché?</button></td></tr>';
    });
    h += "</tbody></table></div></section>";
    var pot = potenziali(p);
    h += '<section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-award") + 'Mansioni potenziali <span class="fmd-count">' + pot.length + '</span></div><div class="fmd-block-aside">segnalate, mai assegnate in automatico</div></div>';
    if (!pot.length) h += '<div class="fmd-muted">Nessuna mansione ulteriore con requisiti in buona parte coperti.</div>';
    else {
      h += '<div class="fmd-tablewrap"><table class="fmd-table"><thead><tr><th>Mansione</th><th>Requisiti coperti</th><th>Esito</th><th></th></tr></thead><tbody>';
      pot.forEach(function (x) { h += "<tr><td><b>" + esc(x.nome) + "</b></td><td>" + x.ok + " su " + x.tot + "</td><td>" + (x.esito === "SODDISFATTA" ? '<span class="fmd-badge fmd-b-green">requisiti soddisfatti</span>' : '<span class="fmd-badge fmd-b-amber">in buona parte</span>') + '</td><td class="fmd-r"><a class="fmd-btn fmd-btn-ghost fmd-btn-mini" href="#simulatore" data-sim="' + p.id + "|" + x.mansione + '">Simula</a></td></tr>'; });
      h += "</tbody></table></div>";
    }
    return h + "</section>";
  }

  VISTE["editor-mansione"] = function () {
    var mid = stato.filtri.mansioneEditor || "M01", m = mans(mid);
    if (!stato.bozza || stato.bozza.id !== mid) stato.bozza = { id: mid, requisiti: JSON.parse(JSON.stringify(m.requisiti)), inviata: false };
    var b = stato.bozza, tit = D.persone.filter(function (p) { return p.mansioni.some(function (a) { return a.mansione === mid; }); }).length;
    var h = messaggio() + testata("Profilo della mansione", ico("i-edit") + esc(m.nome), esc(D.reparti[m.reparto]) + " · mansione di rischio: " + esc(m.mansione_rischio) + " · " + tit + " titolari · profilo versione " + m.versione);
    h += '<div class="px-barra"><label>Mansione<select data-filtro="mansioneEditor">' + D.mansioni.map(function (x) { return '<option value="' + x.id + '"' + (x.id === mid ? " selected" : "") + ">" + esc(x.nome) + "</option>"; }).join("") + "</select></label></div>" + interruttore();
    if (stato.vista === "OGGI") {
      h += '<p class="px-oggi">Oggi in produzione nessuna delle 242 mansioni ha competenze definite: la scheda mostra ruolo, reparto e persone in lista. La modifica vale subito, senza versioni né anteprima.</p>';
      h += '<section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-clipboard") + 'Competenze <span class="fmd-count">0</span></div></div><div class="fmd-muted">Nessuna competenza definita: il livello sulla mansione è quello assegnato a mano.</div></section>';
      return h;
    }
    var libere = D.competenze.filter(function (c) { return !b.requisiti.some(function (r) { return r.competenza === c.id; }); });
    h += '<div class="px-due"><section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-clipboard") + 'Requisiti del profilo <span class="fmd-count">' + b.requisiti.length + '</span></div><div class="fmd-block-aside">bozza della versione ' + (m.versione + 1) + '</div></div><div class="fmd-tablewrap"><table class="fmd-table"><thead><tr><th>Competenza</th><th>Livello atteso</th><th>Criticità</th><th></th></tr></thead><tbody>';
    b.requisiti.forEach(function (r, i) {
      var orig = m.requisiti.filter(function (x) { return x.competenza === r.competenza; })[0], camb = !orig || orig.minimo !== r.minimo || orig.criticita !== r.criticita;
      h += "<tr" + (camb ? ' style="background:#fff7ed"' : "") + "><td><b>" + esc(comp(r.competenza).nome) + "</b>" + (camb ? ' <span class="fmd-badge fmd-b-orange">' + (orig ? "modificato" : "nuovo") + "</span>" : "") + '</td><td><select data-req="' + i + '|minimo" aria-label="Livello atteso">' + ["I", "L", "U", "O"].map(function (x) { return '<option value="' + x + '"' + (r.minimo === x ? " selected" : "") + ">" + x + " · " + NOME_LV[x] + "</option>"; }).join("") + '</select></td><td><select data-req="' + i + '|criticita" aria-label="Criticità">' + ["B", "I", "U"].map(function (x) { return '<option value="' + x + '"' + (r.criticita === x ? " selected" : "") + ">" + NOME_CRIT[x] + "</option>"; }).join("") + '</select></td><td class="fmd-r"><button type="button" class="fmd-btn fmd-btn-ghost fmd-btn-mini" data-req-togli="' + i + '">Togli</button></td></tr>';
    });
    h += '</tbody></table></div><div class="px-barra" style="margin-top:12px"><label>Aggiungi una competenza<select data-req-aggiungi><option value="">Scegli…</option>' + libere.map(function (c) { return '<option value="' + c.id + '">' + esc(c.nome) + "</option>"; }).join("") + "</select></label></div></section>";
    var imp = impattoRevisione(mid, b.requisiti), modificato = JSON.stringify(b.requisiti) !== JSON.stringify(m.requisiti);
    h += '<section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-alert-cir") + "Anteprima d'impatto</div></div>";
    h += '<p style="margin:0 0 4px"><span class="px-big" id="px-impatto">' + imp.cambi.length + '</span> <span class="fmd-muted">su ' + imp.titolari + " titolari cambiano stato</span></p>";
    if (!modificato) h += '<p class="px-nota">Modifica un livello, una criticità o aggiungi una competenza: il conteggio si aggiorna subito.</p>';
    imp.cambi.forEach(function (x) { h += '<div class="px-diff"><a class="fmd-data-link" href="#' + slug(x.p) + '">' + esc(nome(x.p)) + "</a><br>" + st(x.prima) + " → " + st(x.dopo) + "</div>"; });
    h += '<p class="px-nota">Alla pubblicazione parte un transitorio di ' + D.parametri.transitorio_revisione_giorni + ' giorni: nel frattempo vale il profilo attuale e le mancanze nuove sono già visibili.</p><div class="px-barra"><button type="button" class="fmd-btn fmd-btn-primary" data-azione="invia-profilo"' + (modificato && !b.inviata ? "" : " disabled") + ">" + (b.inviata ? "In approvazione da RDD" : "Richiedi approvazione") + '</button><button type="button" class="fmd-btn fmd-btn-ghost" data-azione="annulla-profilo"' + (modificato ? "" : " disabled") + ">Annulla le modifiche</button></div></section></div>";
    return h;
  };

  VISTE["simulatore"] = function () {
    var f = stato.filtri, pid = f.simPersona || "P01", p = pers(pid);
    var libere = D.mansioni.filter(function (m) { return !p.mansioni.some(function (a) { return a.mansione === m.id; }); });
    var mid = (f.simMansione && libere.some(function (m) { return m.id === f.simMansione; })) ? f.simMansione : (pid === "P01" ? "M02" : libere[0].id), m = mans(mid);
    var s = simulaCambio(pid, mid);
    var h = messaggio() + testata("Simulatore cambio mansione", ico("i-refresh") + "Che cosa succede se…", "Nessun dato viene modificato finché non si apre la richiesta.");
    h += '<div class="px-barra"><label>Persona<select data-filtro="simPersona">' + D.persone.map(function (x) { return '<option value="' + x.id + '"' + (x.id === pid ? " selected" : "") + ">" + esc(nome(x)) + "</option>"; }).join("") + '</select></label><label>Nuova mansione<select data-filtro="simMansione">' + libere.map(function (x) { return '<option value="' + x.id + '"' + (x.id === mid ? " selected" : "") + ">" + esc(x.nome) + "</option>"; }).join("") + "</select></label></div>";
    h += '<section class="fmd fmd-kpi fmd-kpi-auto" style="margin-bottom:16px">' + kpi(s.v.righe.length, "Requisiti della mansione", esc(m.nome), "navy", "i-clipboard", "#simulatore") + kpi('<span id="px-coperti">' + s.coperti.length + "</span>", "Già coperti", "dalle evidenze esistenti", "green", "i-check", "#simulatore") + kpi('<span id="px-mancanti">' + s.mancanti.length + "</span>", "Da colmare", s.mancanti.length ? "servono sessioni formative" : "nessuna sessione necessaria", s.mancanti.length ? "orange" : "green", "i-book", "#simulatore") + "</section>";
    h += '<div class="px-due"><section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-clipboard") + 'Confronto</div></div><div class="fmd-tablewrap"><table class="fmd-table"><thead><tr><th>Competenza</th><th>Atteso</th><th>Posseduto</th><th>Esito</th></tr></thead><tbody>';
    s.v.righe.forEach(function (r) { h += "<tr><td><b>" + esc(comp(r.competenza).nome) + '</b> <span class="fmd-muted">' + NOME_CRIT[r.criticita] + "</span></td><td>" + lv(r.minimo) + "</td><td>" + lv(r.valutato) + "</td><td>" + (r.gap ? '<span class="fmd-pill fmd-pill-red">da colmare</span>' : '<span class="fmd-badge fmd-b-green">già coperto</span>') + "</td></tr>"; });
    h += '</tbody></table></div></section><section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-arrow-right") + "Esito della simulazione</div></div>";
    h += "<p>" + (s.mancanti.length ? "La richiesta avvierebbe la mansione in stato " + st(s.v.stato) + ". Servono sessioni formative solo sulle <b>" + s.mancanti.length + "</b> competenze da colmare; le altre <b>" + s.coperti.length + "</b> riusano le evidenze esistenti." : "Tutti i requisiti sono già coperti: la richiesta va <b>direttamente in approvazione</b>, senza nuove sessioni formative.") + "</p>";
    h += '<p class="px-nota">Mansione di rischio: <b>' + esc(s.rischio) + "</b> — " + (s.rischioNuovo ? "diversa da quelle attuali: si apre anche il piano di adeguamento (visita, DPI, formazione di sicurezza)." : "la stessa di oggi: nessuna visita o DPI in più.") + "</p>";
    h += '<div class="px-barra"><button type="button" class="fmd-btn fmd-btn-primary" data-azione="apri-ram" data-arg="' + pid + "|" + mid + '">Apri la richiesta (RAM)</button></div></section></div>';
    return h;
  };

  function codaIniziale() {
    return [
      { id: "SF-2027-0063", tipo: "SF", titolo: "Affiancamento 40 h — Programmazione a bordo macchina", persona: "P01", competenza: "C03", proposto: "L", modalita: "A", nota: "Tutor: Aldo Bianchetti. Chiude il gap della richiesta per DM6." },
      { id: "SF-2027-0071", tipo: "SF", titolo: "Prova pratica — Lettura del disegno tecnico", persona: "P02", competenza: "C01", proposto: "U", modalita: "A", nota: "Prova superata il 12/03/2027." },
      { id: "SF-2027-0072", tipo: "SF", titolo: "Prova pratica — Set-up macchina 5 assi", persona: "P02", competenza: "C02", proposto: "U", modalita: "A", nota: "80 ore di affiancamento registrate." },
      { id: "RAM-2027-0042", tipo: "RAM", titolo: "Nuova mansione: DM3 – Fresatura 5 assi", persona: "P05", mansione: "M01", nota: "Requisiti già soddisfatti: nessuna sessione formativa necessaria." }
    ];
  }
  VISTE["coda-car"] = function () {
    if (!stato.coda) stato.coda = codaIniziale();
    var q = quadro(), segn = q.righeNC.filter(function (x) { return x.v.segnalazioni; });
    var h = messaggio() + testata("Coda del responsabile", ico("i-clipboard") + "Da fare", "Reparto Fresatura 5 assi · responsabile: BIANCHETTI Aldo");
    h += '<section class="fmd fmd-kpi fmd-kpi-auto" style="margin-bottom:16px">' + kpi('<span id="px-coda-n">' + stato.coda.length + "</span>", "Da valutare o approvare", "sessioni e richieste", "cyan", "i-clipboard", "#coda-car") + kpi(segn.length, "Segnalazioni gravi", "da prendere in carico", "amber", "i-alert-cir", "#coda-car") + kpi(q.daConf, "Competenze da confermare", "conferma periodica o grazia", "yellow", "i-clock", "#coda-car") + "</section>";
    h += '<section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-check") + 'Valutazioni e richieste <span class="fmd-count">' + stato.coda.length + "</span></div></div>";
    if (!stato.coda.length) h += '<div class="fmd-muted">Niente in coda.</div>';
    stato.coda.forEach(function (x) {
      var p = pers(x.persona);
      h += '<div class="px-card" style="margin-bottom:10px"><h3><span class="fmd-badge ' + (x.tipo === "SF" ? "fmd-b-cyan" : "fmd-b-violet") + '">' + x.id + "</span> " + esc(x.titolo) + '</h3><p style="margin:4px 0;font-size:13.5px"><a class="fmd-data-link" href="#' + slug(p) + '">' + esc(nome(p)) + "</a>" + (x.tipo === "SF" ? " · livello attuale " + lv((p.livelli[x.competenza] || {}).livello || "") + " → proposto " + lv(x.proposto) : "") + '</p><p class="px-nota">' + esc(x.nota) + '</p><div class="px-barra" style="margin:10px 0 0"><button type="button" class="fmd-btn fmd-btn-primary" data-azione="coda-ok" data-arg="' + x.id + '">' + (x.tipo === "SF" ? "Conferma il livello" : "Approva") + '</button><button type="button" class="fmd-btn fmd-btn-ghost" data-azione="coda-no" data-arg="' + x.id + '">Respingi</button></div></div>';
    });
    h += '</section><section class="fmd-panel fmd-block"><div class="fmd-block-head"><div class="fmd-block-title">' + ico("i-alert-cir") + 'Segnalazioni da prendere in carico <span class="fmd-count">' + segn.length + '</span></div><div class="fmd-block-aside">modalità: ' + (blocco() ? "blocco" : "segnalazione") + "</div></div>";
    if (!segn.length) h += '<div class="fmd-muted">Nessuna.</div>';
    segn.forEach(function (x) {
      var r = x.v.righe.filter(function (y) { return y.validita === "SOSPESA"; })[0];
      h += '<div class="px-diff"><a class="fmd-data-link" href="#' + slug(x.p) + '">' + esc(nome(x.p)) + "</a> · " + esc(x.m.nome) + " · " + st(x.v.stato) + "<br><b>" + esc(comp(r.competenza).nome) + "</b>: " + esc(r.motivo) + '. <span class="fmd-muted">' + (blocco() ? "La persona non risulta operativa." : "La persona continua a operare: indicare che cosa si fa.") + "</span></div>";
    });
    return h + "</section>";
  };

  VISTE["pianificatore"] = function () {
    var per = {};
    D.persone.forEach(function (p) {
      var re = requisitiEffettivi(p);
      Object.keys(re).forEach(function (c) {
        var r = re[c], v = validita(p, c), eff = livelloEfficace(p, c);
        if (ORD[eff] >= ORD[r.minimo] && v.stato !== "SOSPESA") return;
        var x = per[c] || (per[c] = { c: comp(c), persone: [], bloccanti: 0 });
        x.persone.push(p); if (r.criticita === "B") x.bloccanti++;
      });
    });
    var righe = Object.keys(per).map(function (k) { return per[k]; }).sort(function (a, b) { return b.bloccanti - a.bloccanti || b.persone.length - a.persone.length; });
    var h = messaggio() + testata("Pianificatore della formazione", ico("i-book") + "Dalle mancanze al piano", righe.length + " competenze con persone da formare, in ordine di urgenza.");
    h += '<section class="fmd-panel fmd-block"><div class="fmd-tablewrap"><table class="fmd-table"><thead><tr><th>Competenza</th><th class="fmd-num">Persone</th><th class="fmd-num">Di cui bloccanti</th><th>Come</th><th>Chi</th><th></th></tr></thead><tbody>';
    righe.forEach(function (x) {
      var tutor = D.persone.filter(function (p) { var l = p.livelli[x.c.id]; return l && l.livello === "O" && validita(p, x.c.id).stato === "VALIDA"; });
      h += "<tr><td><b>" + esc(x.c.nome) + '</b></td><td class="fmd-num">' + x.persone.length + '</td><td class="fmd-num">' + (x.bloccanti ? '<span class="fmd-pill fmd-pill-red">' + x.bloccanti + "</span>" : "0") + "</td><td>" + (x.c.requisito && x.c.requisito.tipo === "corso" ? '<span class="fmd-badge fmd-b-cyan">C corso</span> ' + esc(x.c.requisito.nome) : x.c.requisito ? '<span class="fmd-badge fmd-b-violet">qualifica</span> ' + esc(x.c.requisito.nome) : '<span class="fmd-badge fmd-b-amber">A affiancamento</span> ' + (tutor.length ? "tutor: " + esc(tutor.slice(0, 2).map(nome).join(", ")) : "nessun tutor a livello O")) + '</td><td class="fmd-muted" style="font-size:12.5px">' + x.persone.slice(0, 4).map(function (p) { return '<a class="fmd-data-link" href="#' + slug(p) + '">' + esc(p.cognome) + "</a>"; }).join(", ") + (x.persone.length > 4 ? " e altri " + (x.persone.length - 4) : "") + '</td><td class="fmd-r"><button type="button" class="fmd-btn fmd-btn-ghost fmd-btn-mini" data-azione="proponi-sf" data-arg="' + x.c.id + '">Proponi una sessione</button></td></tr>';
    });
    return h + "</tbody></table></div></section>";
  };

  VISTE["vista-dipendente"] = function () {
    var p = pers("P02"), h = '<div class="px-mobile">' + messaggio() + '<div class="px-card" style="background:#0c2545;color:#fff"><div style="font-size:13px;opacity:.8">La mia scheda</div><div style="font-size:21px;font-weight:700">' + esc(p.nome + " " + p.cognome) + '</div><div style="font-size:13px;opacity:.85">' + esc(p.ruolo) + " · " + esc(D.reparti[p.reparto]) + "</div></div>";
    p.mansioni.forEach(function (a) {
      var m = mans(a.mansione), v = valutaMansione(p, m, a.stato), mancano = v.righe.filter(function (r) { return r.gap; });
      h += '<div class="px-card"><h3>' + esc(m.nome) + "</h3>" + st(v.stato) + '<p style="font-size:14px;margin:8px 0 0">' + (v.opera ? "Puoi lavorare da sola su questa mansione." : "Stai imparando: lavori insieme a un collega esperto.") + (v.firma ? " Puoi firmare." : " Non firmi ancora.") + "</p>";
      if (mancano.length) {
        h += '<p style="font-size:13px;font-weight:700;margin:12px 0 0;color:#0c2545">Che cosa ti manca</p>';
        mancano.forEach(function (r) { h += '<div class="px-azione"><span>' + esc(comp(r.competenza).nome) + '</span><span style="white-space:nowrap">' + lv(r.valutato) + " → " + lv(r.minimo) + "</span></div>"; });
      }
      h += "</div>";
    });
    var scad = Object.keys(p.livelli).filter(function (c) { return p.livelli[c].requisito_scadenza; });
    h += '<div class="px-card"><h3>Le mie scadenze</h3>';
    scad.forEach(function (c) { h += '<div class="px-azione"><span>' + esc(comp(c).requisito.nome) + "</span><b>" + dataIt(p.livelli[c].requisito_scadenza) + "</b></div>"; });
    h += '</div><div class="px-card"><h3>Le mie valutazioni</h3>';
    Object.keys(p.livelli).forEach(function (c) { var l = p.livelli[c]; h += '<div class="px-azione"><span>' + esc(comp(c).nome) + '<br><span class="px-fonte">' + esc(l.sf) + " · " + dataIt(l.valutato_il) + "</span></span>" + lv(l.livello) + "</div>"; });
    return h + '</div><p class="px-nota" style="text-align:center">Vista pensata per il telefono e per le postazioni condivise: nessun dato di altre persone.</p></div>';
  };

  /* ── Navigazione, eventi, avvio ──────────────────────────────────────── */
  function rotta() { var r = location.hash.replace(/^#/, ""); return r || "cruscotto-qualita"; }
  function disegna() {
    var r = rotta(), el = document.getElementById("vista"), html;
    if (r.indexOf("dipendente-") === 0) {
      var p = D.persone.filter(function (x) { return slug(x) === r; })[0] || pers("P01");
      html = vistaPersona(p);
    } else html = (VISTE[r] || VISTE["cruscotto-qualita"])();
    el.innerHTML = html;
    var i = -1; TOUR.forEach(function (t, k) { if (t[0] === r || (r.indexOf("dipendente-") === 0 && t[0].indexOf("dipendente-") === 0)) i = k; });
    if (i < 0) i = 0;
    document.getElementById("px-tour-n").textContent = (i + 1) + " di " + TOUR.length;
    document.getElementById("px-tour-t").innerHTML = "<b>" + esc(TOUR[i][1]) + ".</b> " + esc(TOUR[i][2]);
    document.getElementById("px-tour-prec").dataset.vai = TOUR[(i + TOUR.length - 1) % TOUR.length][0];
    document.getElementById("px-tour-succ").dataset.vai = TOUR[(i + 1) % TOUR.length][0];
    document.querySelectorAll("[data-nav]").forEach(function (a) { var on = a.dataset.nav === TOUR[i][0]; a.classList.toggle("active", on); if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    document.getElementById("px-percorso-qui").textContent = TOUR[i][1];
    document.querySelectorAll("[data-modalita]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.modalita === D.parametri.modalita_validita)); });
    document.title = TOUR[i][1] + " | Prototipo NOVICROM HUB";
    try { localStorage.setItem("px-rmc-ultima", r); } catch (e) { /* solo comodità */ }
  }
  function vai(r) { if (rotta() === r) disegna(); else location.hash = r; }

  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-perche],[data-chiudi],[data-vista],[data-vai],[data-modalita],[data-azione],[data-req-togli],[data-sim],[data-vai-reparto],#px-velo");
    if (!t) return;
    if (t.id === "px-velo" || t.hasAttribute("data-chiudi")) return chiudiPerche();
    if (t.dataset.perche) { var a = t.dataset.perche.split("|"); return apriPerche(a[0], a[1]); }
    if (t.dataset.vista) { stato.vista = t.dataset.vista; return disegna(); }
    if (t.dataset.vai) return vai(t.dataset.vai);
    if (t.dataset.modalita) { D.parametri.modalita_validita = t.dataset.modalita; stato.msg = t.dataset.modalita === "BLOCCO" ? "Modalità blocco: una competenza non più valida toglie l'operatività." : "Modalità segnalazione: una competenza non più valida viene segnalata, la persona resta operativa."; return disegna(); }
    if (t.dataset.vaiReparto) { stato.filtri.reparto = t.dataset.vaiReparto; stato.filtri.mansione = ""; return; }
    if (t.dataset.sim) { var s = t.dataset.sim.split("|"); stato.filtri.simPersona = s[0]; if (s[1]) stato.filtri.simMansione = s[1]; else delete stato.filtri.simMansione; return; }
    if (t.hasAttribute("data-req-togli")) { stato.bozza.requisiti.splice(+t.dataset.reqTogli, 1); return disegna(); }
    var az = t.dataset.azione, arg = t.dataset.arg || "";
    if (az === "ripristina") { D = JSON.parse(JSON.stringify(ORIGINALE)); stato.coda = null; stato.bozza = null; stato.msg = "Dati riportati allo stato iniziale."; return disegna(); }
    if (az === "invia-profilo") { stato.bozza.inviata = true; stato.msg = "Bozza inviata a RDD per l'approvazione. Nel prototipo il profilo in vigore non cambia."; return disegna(); }
    if (az === "annulla-profilo") { stato.bozza = null; return disegna(); }
    if (az === "apri-ram") { var x = arg.split("|"), n = "RAM-2027-" + String(43 + (stato.coda ? stato.coda.length : 4)).padStart(4, "0"); if (!stato.coda) stato.coda = codaIniziale(); stato.coda.push({ id: n, tipo: "RAM", titolo: "Nuova mansione: " + mans(x[1]).nome, persona: x[0], mansione: x[1], nota: "Aperta dal simulatore." }); stato.msg = "Richiesta " + n + " aperta: è nella coda del responsabile."; return vai("coda-car"); }
    if (az === "proponi-sf") { stato.msg = "Sessione formativa proposta per «" + comp(arg).nome + "»: i candidati vengono dal motore, non da un secondo elenco."; return disegna(); }
    if (az === "coda-ok" || az === "coda-no") {
      var v = stato.coda.filter(function (y) { return y.id === arg; })[0]; if (!v) return;
      stato.coda = stato.coda.filter(function (y) { return y.id !== arg; });
      var p = pers(v.persona);
      if (az === "coda-no") stato.msg = v.id + " respinta: nessun dato modificato.";
      else if (v.tipo === "SF") {
        var prec = p.livelli[v.competenza] || { requisito_scadenza: null, requisito_presente: false, ultimo_esercizio: null };
        p.livelli[v.competenza] = { livello: v.proposto, valutato_il: D.oggi, valutato_da: "P03", modalita: v.modalita, sf: v.id, requisito_scadenza: prec.requisito_scadenza, requisito_presente: prec.requisito_presente, ultimo_esercizio: prec.ultimo_esercizio };
        stato.msg = v.id + " chiusa: " + nome(p) + " ora è a livello " + v.proposto + " su «" + comp(v.competenza).nome + "». Mansioni e mansioni potenziali ricalcolate.";
      } else {
        var m = mans(v.mansione), val = valutaMansione(p, m, "AVVIATA"), eff = !val.righe.some(function (r) { return r.gap && r.criticita !== "U"; });
        p.mansioni.push({ mansione: v.mansione, stato: eff ? "EFFETTIVA" : "AVVIATA", dal: D.oggi, ram: v.id });
        stato.msg = v.id + " approvata: " + m.nome + " è ora " + (eff ? "effettiva" : "avviata (in formazione)") + " per " + nome(p) + ".";
      }
      return disegna();
    }
  });
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (t.dataset.filtro) { stato.filtri[t.dataset.filtro] = t.type === "checkbox" ? t.checked : t.value; if (t.dataset.filtro === "reparto") stato.filtri.mansione = ""; if (t.dataset.filtro === "simPersona") delete stato.filtri.simMansione; if (t.dataset.filtro === "mansioneEditor") stato.bozza = null; if (t.type !== "search") disegna(); return; }
    if (t.hasAttribute("data-vai-persona")) return vai(t.value);
    if (t.dataset.req) { var a = t.dataset.req.split("|"); stato.bozza.requisiti[+a[0]][a[1]] = t.value; stato.bozza.inviata = false; return disegna(); }
    if (t.hasAttribute("data-req-aggiungi") && t.value) { stato.bozza.requisiti.push({ competenza: t.value, minimo: "L", criticita: "I" }); stato.bozza.inviata = false; return disegna(); }
  });
  document.addEventListener("input", function (e) {
    var t = e.target;
    if (t.dataset.filtro === "testo") { stato.filtri.testo = t.value; var pos = t.selectionStart; disegna(); var n = document.querySelector('[data-filtro="testo"]'); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (x) { /* ignora */ } } }
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") chiudiPerche(); });
  window.addEventListener("hashchange", function () { chiudiPerche(); disegna(); window.scrollTo(0, 0); });
  window.PX = { quadro: quadro, dati: function () { return D; }, simulaCambio: simulaCambio, potenziali: potenziali, pers: pers };
  if (!location.hash) { var ultima = null; try { ultima = localStorage.getItem("px-rmc-ultima"); } catch (e) { /* ignora */ } if (ultima) { location.hash = ultima; return; } }
  disegna();
})();
