/* Protocollo del report CMM: scelta della quota (clic, frecce ↑ ↓), dettaglio a destra con l'andamento sugli
   ultimi pezzi dello stesso programma, densità compatta ricordata nel browser. I dati vengono da #prot-dati. */
/* Matrice del pezzo: % tolleranza / deviazione / valore, scelta ricordata nel browser. */
(function () {
  "use strict";
  var mat = document.querySelector("[data-matrice]");
  if (!mat) return;
  var tab = mat.querySelector(".prot-mat");
  var bott = mat.querySelectorAll("[data-vista]");
  var KEY = "nhub.pezzo.vista";
  function vista(v) {
    if (tab) tab.className = tab.className.replace(/\bvista-\w+/g, "").trim() + " vista-" + v;
    Array.prototype.forEach.call(bott, function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-vista") === v ? "true" : "false"); });
  }
  try { var salvata = window.localStorage.getItem(KEY); if (/^(u|dev|x)$/.test(salvata || "")) vista(salvata); } catch (e) { /* storage bloccato */ }
  Array.prototype.forEach.call(bott, function (b) {
    b.addEventListener("click", function () {
      vista(b.getAttribute("data-vista"));
      try { window.localStorage.setItem(KEY, b.getAttribute("data-vista")); } catch (e) { /* storage bloccato */ }
    });
  });
})();

(function () {
  "use strict";
  var sez = document.querySelector("[data-protocollo]");
  var dati = document.getElementById("prot-dati");
  if (!sez || !dati) return;
  var quote = {};
  JSON.parse(dati.textContent).forEach(function (q) { quote[q.i] = q; });
  var det = sez.querySelector("[data-prot-det]");
  var righe = Array.prototype.slice.call(sez.querySelectorAll(".prot-riga"));
  var foglie = sez.querySelectorAll(".prot-foglia");

  function num(v, cifre, segno) {
    if (v === null || v === undefined) return "—";
    var s = Number(v).toFixed(cifre === undefined ? 4 : cifre).replace(".", ",");
    return segno && v > 0 ? "+" + s : s;
  }
  function esc(s) {
    return String(s || "").replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; });
  }

  /* Carta dei singoli valori: fascia di tolleranza, limiti, media; il pezzo di questo report cerchiato. */
  function carta(q) {
    var s = q.serie || [];
    if (s.length < 2) return "<p class='prod-nota'>Andamento: servono almeno due pezzi validi dello stesso programma.</p>";
    var w = 300, h = 130, sx = 28, dx = 6, top = 8, bot = 16;
    var xs = s.map(function (p) { return p[0]; });
    var lo = Math.min(q.lsl, Math.min.apply(null, xs)), hi = Math.max(q.usl, Math.max.apply(null, xs));
    var pad = (hi - lo) * 0.12 || 0.001;
    lo -= pad; hi += pad;
    function y(v) { return top + (hi - v) / (hi - lo) * (h - top - bot); }
    function x(i) { return sx + i * (w - sx - dx) / (s.length - 1); }
    var media = xs.reduce(function (a, b) { return a + b; }, 0) / xs.length;
    var pts = s.map(function (p, i) { return x(i).toFixed(1) + "," + y(p[0]).toFixed(1); }).join(" ");
    var punti = s.map(function (p, i) {
      return "<circle class='p" + (p[1] ? " is-fuori" : "") + (p[2] === q.corrente ? " is-qui" : "") + "' cx='" + x(i).toFixed(1) +
        "' cy='" + y(p[0]).toFixed(1) + "' r='" + (p[2] === q.corrente ? 4 : 2.6) + "'><title>" + num(p[0]) + "</title></circle>";
    }).join("");
    function riga(v, cls, et) {
      return "<line class='" + cls + "' x1='" + sx + "' x2='" + (w - dx) + "' y1='" + y(v).toFixed(1) + "' y2='" + y(v).toFixed(1) + "'/>" +
        "<text x='" + (sx - 3) + "' y='" + (y(v) + 3).toFixed(1) + "' text-anchor='end'>" + et + "</text>";
    }
    return "<svg class='prot-carta' viewBox='0 0 " + w + " " + h + "' preserveAspectRatio='none' role='img' aria-label='Andamento sugli ultimi " + s.length + " pezzi'>" +
      "<rect class='fascia' x='" + sx + "' y='" + y(q.usl).toFixed(1) + "' width='" + (w - sx - dx) + "' height='" + (y(q.lsl) - y(q.usl)).toFixed(1) + "'/>" +
      riga(q.usl, "lim", "LS") + riga(q.lsl, "lim", "LI") +
      riga(media, "med", Math.min(Math.abs(y(media) - y(q.usl)), Math.abs(y(media) - y(q.lsl))) < 10 ? "" : "x̄") +
      "<polyline class='linea' points='" + pts + "'/>" + punti +
      "<text x='" + (w - dx) + "' y='" + (h - 3) + "' text-anchor='end'>ultimi " + s.length + " pezzi →</text></svg>";
  }

  function indice(etichetta, valore, classe) {
    return "<div class='" + (classe || "") + "'>" + etichetta + "<b>" + valore + "</b></div>";
  }

  function mostra(i, scorri) {
    var q = quote[i];
    if (!q) return;
    righe.forEach(function (r) { r.classList.toggle("is-sel", r.getAttribute("data-i") === String(i)); });
    Array.prototype.forEach.call(foglie, function (f) { f.classList.toggle("is-sel", f.getAttribute("data-i") === String(i)); });
    var cpkCl = q.cpk === null || q.cpk === undefined ? "" : (q.cpk < 1 ? "is-ko" : (q.cpk < 1.33 ? "is-wa" : "is-ok"));
    var andamento = sez.getAttribute("data-andamento") + "&q=" + encodeURIComponent(q.chiave) + "&nom=" + Number(q.nom).toFixed(4);
    var anomalia = sez.getAttribute("data-anomalia");
    det.innerHTML =
      "<h3><span class='prot-ic is-" + q.stato + "' aria-hidden='true'></span>" + esc(q.nome) + "</h3>" +
      "<div class='prot-kv'><span>Nominale</span><b>" + num(q.nom) + "</b>" +
      "<span>Tolleranza sup / inf</span><b>" + num(q.sup, 4, true) + " / " + num(q.inf, 4, true) + "</b>" +
      "<span>Misurato</span><b class='" + (q.stato === "fuori" ? "is-fuori" : "") + "'>" + num(q.x) + "</b>" +
      "<span>Deviazione</span><b>" + num(q.dev, 4, true) + "</b>" +
      (q.ecc !== null ? "<span>Fuori di</span><b class='is-fuori'>" + num(q.ecc, 4, true) + "</b>" : "") +
      "<span>Tolleranza usata</span><b>" + (q.u === null ? "—" : q.u + "%") + "</b>" +
      "<span>Pezzo prima</span><b>" + num(q.prima) + "</b></div>" +
      "<div class='prot-det-sez'>Andamento sul programma</div>" + carta(q) +
      "<div class='prot-indici'>" +
      indice("Cpk", q.cpk === null || q.cpk === undefined ? "—" : num(q.cpk, 2), cpkCl) +
      indice("Deriva", q.deriva ? "sì" : "no", q.deriva ? "is-wa" : "") +
      indice("Fuori", q.n ? q.n_fuori + " / " + q.n : "—", q.n_fuori ? "is-ko" : "") +
      "</div>" +
      "<div class='prot-det-azioni'><a class='prod-btn prod-btn-piccolo' href='" + esc(andamento) + "'>Analisi quote</a>" +
      (anomalia ? "<a class='prod-btn prod-btn-piccolo prod-btn-primary' href='" + esc(anomalia) + "'>Apri anomalia</a>" : "") + "</div>";
    if (scorri) {
      var r = sez.querySelector(".prot-riga[data-i='" + i + "']");
      if (r) { r.focus({ preventScroll: true }); r.scrollIntoView({ block: "nearest" }); }
    }
  }

  righe.forEach(function (r) {
    r.addEventListener("click", function () { mostra(r.getAttribute("data-i"), false); });
    r.addEventListener("keydown", function (e) {
      var k = righe.indexOf(r);
      if (e.key === "ArrowDown" && k < righe.length - 1) { e.preventDefault(); mostra(righe[k + 1].getAttribute("data-i"), true); }
      else if (e.key === "ArrowUp" && k > 0) { e.preventDefault(); mostra(righe[k - 1].getAttribute("data-i"), true); }
      else if (e.key === "Enter") { mostra(r.getAttribute("data-i"), false); }
    });
  });
  Array.prototype.forEach.call(foglie, function (f) {
    f.addEventListener("click", function (e) { e.preventDefault(); mostra(f.getAttribute("data-i"), true); });
  });

  var KEY = "nhub.prot.compatta";
  var bott = sez.querySelector("[data-prot-densita]");
  function densita(on) {
    sez.classList.toggle("is-compatta", on);
    if (bott) bott.setAttribute("aria-pressed", on ? "true" : "false");
  }
  try { densita(window.localStorage.getItem(KEY) === "1"); } catch (e) { /* storage bloccato */ }
  if (bott) bott.addEventListener("click", function () {
    var on = !sez.classList.contains("is-compatta");
    densita(on);
    try { window.localStorage.setItem(KEY, on ? "1" : "0"); } catch (e) { /* storage bloccato */ }
  });

  /* All'apertura: la quota dell'indirizzo (#q-…), altrimenti la prima fuori, altrimenti la prima. */
  var dalHash = /^#q-(\d+)$/.exec(window.location.hash || "");
  var prima = righe.filter(function (r) { return r.classList.contains("is-fuori"); })[0] || righe[0];
  if (dalHash && quote[dalHash[1]]) mostra(dalHash[1], true);
  else if (prima) mostra(prima.getAttribute("data-i"), false);
})();

/* Qualità CMM della scheda P/N: carta di controllo dei singoli valori e istogramma della quota scelta. */
(function () {
  "use strict";
  var dati = document.getElementById("qualita-dati");
  var box = document.querySelector("[data-carta-qualita]");
  if (!dati || !box) return;
  var q = JSON.parse(dati.textContent);
  if (!q || !q.serie || q.serie.length < 2) { box.innerHTML = "<p class='prod-nota'>Servono almeno due pezzi validi.</p>"; return; }
  function num(v) { return Number(v).toFixed(4).replace(".", ","); }
  var s = q.serie, xs = s.map(function (p) { return p[0]; });
  var w = 720, h = 230, sx = 34, dx = 8, top = 10, bot = 18;
  var lo = Math.min(q.lsl, Math.min.apply(null, xs)), hi = Math.max(q.usl, Math.max.apply(null, xs));
  var pad = (hi - lo) * 0.1 || 0.001;
  lo -= pad; hi += pad;
  function y(v) { return top + (hi - v) / (hi - lo) * (h - top - bot); }
  function x(i) { return sx + i * (w - sx - dx) / (s.length - 1); }
  var media = q.media !== null && q.media !== undefined ? q.media : xs.reduce(function (a, b) { return a + b; }, 0) / xs.length;
  function riga(v, cls, et) {
    return "<line class='" + cls + "' x1='" + sx + "' x2='" + (w - dx) + "' y1='" + y(v).toFixed(1) + "' y2='" + y(v).toFixed(1) + "'/>" +
      "<text x='" + (sx - 4) + "' y='" + (y(v) + 3).toFixed(1) + "' text-anchor='end'>" + et + "</text>";
  }
  var pts = s.map(function (p, i) { return x(i).toFixed(1) + "," + y(p[0]).toFixed(1); }).join(" ");
  var punti = s.map(function (p, i) {
    var ultimo = i === s.length - 1;
    return "<circle class='p" + (p[1] ? " is-fuori" : "") + (ultimo ? " is-qui" : "") + "' cx='" + x(i).toFixed(1) + "' cy='" + y(p[0]).toFixed(1) +
      "' r='" + (ultimo ? 4.5 : 3) + "'><title>" + num(p[0]) + "</title></circle>";
  }).join("");
  box.innerHTML = "<svg class='prot-carta prot-carta-grande' viewBox='0 0 " + w + " " + h + "' role='img' aria-label='Carta di controllo di " + String(q.nome).replace(/'/g, "") + "'>" +
    "<rect class='fascia' x='" + sx + "' y='" + y(q.usl).toFixed(1) + "' width='" + (w - sx - dx) + "' height='" + (y(q.lsl) - y(q.usl)).toFixed(1) + "'/>" +
    riga(q.usl, "lim", "LS") + riga(q.lsl, "lim", "LI") +
    riga(media, "med", Math.min(Math.abs(y(media) - y(q.usl)), Math.abs(y(media) - y(q.lsl))) < 12 ? "" : "x̄") +
    "<polyline class='linea' points='" + pts + "'/>" + punti +
    "<text x='" + (w - dx) + "' y='" + (h - 3) + "' text-anchor='end'>" + s.length + " pezzi, dal più vecchio →</text></svg>";

  /* Istogramma: 10 classi fra il minimo e il massimo del grafico, limiti in rosso. */
  var ist = document.querySelector("[data-istogramma-qualita]");
  if (!ist) return;
  var n = 10, classi = [], i;
  for (i = 0; i < n; i++) classi.push(0);
  xs.forEach(function (v) { classi[Math.min(n - 1, Math.max(0, Math.floor((v - lo) / (hi - lo) * n)))] += 1; });
  var max = Math.max.apply(null, classi) || 1, W = 230, H = 230, base = H - 18;
  function hx(v) { return 6 + (v - lo) / (hi - lo) * (W - 12); }
  var barre = classi.map(function (c, k) {
    var x0 = 6 + k * (W - 12) / n, bw = (W - 12) / n - 3, bh = c / max * (base - 14);
    var centro = lo + (k + 0.5) * (hi - lo) / n, fuori = centro < q.lsl || centro > q.usl;
    return "<rect class='" + (fuori ? "is-fuori" : "") + "' x='" + x0.toFixed(1) + "' y='" + (base - bh).toFixed(1) + "' width='" + bw.toFixed(1) + "' height='" + bh.toFixed(1) + "' rx='2'><title>" + c + " pezzi</title></rect>";
  }).join("");
  ist.innerHTML = "<div class='prot-det-sez'>Distribuzione</div><svg class='prot-istogramma' viewBox='0 0 " + W + " " + H + "' role='img' aria-label='Distribuzione dei valori'>" + barre +
    "<line class='lim' x1='" + hx(q.lsl).toFixed(1) + "' x2='" + hx(q.lsl).toFixed(1) + "' y1='4' y2='" + base + "'/>" +
    "<line class='lim' x1='" + hx(q.usl).toFixed(1) + "' x2='" + hx(q.usl).toFixed(1) + "' y1='4' y2='" + base + "'/>" +
    "<text x='" + hx(q.lsl).toFixed(1) + "' y='" + (H - 4) + "' text-anchor='middle'>LI</text><text x='" + hx(q.usl).toFixed(1) + "' y='" + (H - 4) + "' text-anchor='middle'>LS</text></svg>";
})();
