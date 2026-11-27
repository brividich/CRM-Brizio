/* NOVICROM HUB — Controllo dimensionale: statistica di processo per Analisi quote.
   Stesse formule di produzione/spc.py (tests_spc.py controlla che diano gli stessi numeri): σ di breve periodo
   (MR̄/1,128) per Cp/Cpk, σ totale per Pp/Ppk, percentili Weibull per le quote di forma e posizione, intervallo
   di confidenza del Cpk, regole di Nelson 1-8, EWMA, rischio del prossimo pezzo, punti di cambio. */
var SPC = (function () {
  "use strict";
  var D2 = 1.128, CAPACE = 1.33, AL_LIMITE = 1.0, MIN_CAPACITA = 5, POCHI_DATI = 25, P_ALTO = 0.99865;
  var EWMA_LAMBDA = 0.2, EWMA_L = 3.0;

  function media(xs) { if (!xs.length) return null; var s = 0; for (var i = 0; i < xs.length; i++) s += xs[i]; return s / xs.length; }
  function devStd(xs) {
    var n = xs.length; if (n < 2) return 0;
    var m = media(xs), s = 0; for (var i = 0; i < n; i++) s += (xs[i] - m) * (xs[i] - m);
    return Math.sqrt(s / (n - 1));
  }
  function sigmaBreve(xs) {
    if (xs.length < 2) return 0;
    var s = 0; for (var i = 1; i < xs.length; i++) s += Math.abs(xs[i] - xs[i - 1]);
    return (s / (xs.length - 1)) / D2;
  }
  function unilaterale(nom, lsl, usl) { return Math.abs(nom || 0) < 1e-12 && Math.abs(lsl) < 1e-12 && usl > 0; }
  function erf(x) {
    /* Abramowitz-Stegun 7.1.26 raffinata con una serie: errore < 1e-9 */
    var s = x < 0 ? -1 : 1; x = Math.abs(x);
    if (x < 3) {
      var somma = x, termine = x, n = 0;
      while (Math.abs(termine) > 1e-17 * Math.abs(somma) && n < 200) { n++; termine *= -x * x / n; somma += termine / (2 * n + 1); }
      return s * 2 / Math.sqrt(Math.PI) * somma;
    }
    var t = 1 / (1 + 0.5 * x);
    var y = 1 - t * Math.exp(-x * x - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 +
      t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
    return s * y;
  }
  function phi(z) { return 0.5 * (1 + erf(z / Math.SQRT2)); }

  function weibull(xs) {
    var pos = xs.filter(function (x) { return x > 0; });
    var distinti = {}; pos.forEach(function (x) { distinti[x] = 1; });
    if (pos.length < MIN_CAPACITA || Object.keys(distinti).length < 3) return null;
    var minimo = Math.min.apply(null, pos) / 2;
    var v = xs.map(function (x) { return x > 0 ? x : minimo; });
    var ln = v.map(Math.log), mln = media(ln);
    function f(k) {
      var a = 0, b = 0; for (var i = 0; i < v.length; i++) { var xk = Math.pow(v[i], k); a += xk * ln[i]; b += xk; }
      return a / b - 1 / k - mln;
    }
    var lo = 0.05, hi = 60.0;
    if (f(lo) > 0 || f(hi) < 0) return null;
    for (var it = 0; it < 80; it++) { var mid = (lo + hi) / 2; if (f(mid) > 0) hi = mid; else lo = mid; }
    var k = (lo + hi) / 2, s = 0;
    for (var i = 0; i < v.length; i++) s += Math.pow(v[i], k);
    return { k: k, lam: Math.pow(s / v.length, 1 / k) };
  }
  function weibullQuantile(w, p) { return w.lam * Math.pow(-Math.log(1 - p), 1 / w.k); }

  function intervalloCpk(cpk, n) {
    if (cpk === null || cpk === undefined || n < 2) return [null, null];
    var se = Math.sqrt(1 / (9 * n) + cpk * cpk / (2 * (n - 1)));
    return [cpk - 1.96 * se, cpk + 1.96 * se];
  }
  /* L'unico giudizio di capacita: indice (peggiore fra Cpk e Ppk) contro 1,33 e 1,00; «pochi dati» sotto 25 pezzi. */
  function verdetto(indice, n) {
    if (indice === null || indice === undefined) return null;
    if (n < POCHI_DATI) return "pochi dati";
    return indice >= CAPACE ? "capace" : (indice >= AL_LIMITE ? "al limite" : "non capace");
  }
  function sottoObiettivo(v) { return v === "al limite" || v === "non capace"; }
  function daGuardare(fuoriUltimo, deriva, v) { return !!(fuoriUltimo || deriva || sottoObiettivo(v)); }
  /* Tolleranza usata: 0 = ideale, +-1 = limite. Unilaterali: rilevato / limite superiore; le altre dal centro. */
  function usata(x, nom, lsl, usl) {
    if (unilaterale(nom, lsl, usl)) return x / usl;
    var banda = usl - lsl;
    return banda > 0 ? (x - (usl + lsl) / 2) / (banda / 2) : null;
  }
  function pezziAlLimite(b, seB, fine) {
    if (!b) return [null, null];
    var verso = b > 0 ? 1 : -1;
    function pezzi(pend) {
      if (pend * verso <= 0) return null;
      var p = Math.max(0, Math.ceil((verso - fine) / pend));
      return p <= 200 ? p : null;
    }
    return [pezzi(b + 1.96 * seB * verso), pezzi(b - 1.96 * seB * verso)];
  }
  /* Tendenza degli ultimi 20 valori di tolleranza usata: stessa regola di spc.deriva. */
  function deriva(us, ultimi) {
    ultimi = ultimi || 20;
    var v = us.filter(function (u) { return u !== null && u !== undefined && isFinite(u); }).slice(-ultimi);
    var n = v.length;
    if (n < 10) return null;
    var mx = (n - 1) / 2, my = media(v), num = 0, den = 0, i;
    for (i = 0; i < n; i++) { num += (i - mx) * (v[i] - my); den += (i - mx) * (i - mx); }
    var b = num / den, fine = my + b * (n - 1 - mx);
    if (Math.abs(b * n) < 0.2 || b * fine <= 0 || Math.abs(fine) < 0.5) return null;
    var pezzi = Math.max(0, Math.ceil(((b > 0 ? 1 : -1) - fine) / b));
    if (pezzi > 50) return null;
    var res = 0;
    for (i = 0; i < n; i++) { var d = v[i] - (my + b * (i - mx)); res += d * d; }
    var seB = n > 2 ? Math.sqrt(res / (n - 2) / den) : 0;
    var f = pezziAlLimite(b, seB, fine);
    return { pendenza: b, pezzi: pezzi, verso: b > 0 ? "sup" : "inf", pezzi_min: f[0], pezzi_max: f[1], n: n, my: my, mx: mx };
  }
  function capacita(xs, lsl, usl, nom) {
    var n = xs.length;
    var out = { n: n, media: media(xs), sd: devStd(xs), sigma_breve: sigmaBreve(xs), cp: null, cpk: null, pp: null, ppk: null,
      cpk_basso: null, cpk_alto: null, metodo: "normale", verdetto: null, indice: null };
    var banda = usl - lsl;
    if (n < MIN_CAPACITA || banda <= 0) return out;
    var m = out.media, sd = out.sd, sb = out.sigma_breve || out.sd;
    if (unilaterale(nom, lsl, usl)) {
      var w = weibull(xs);
      if (w) {
        var x50 = weibullQuantile(w, 0.5), xa = weibullQuantile(w, P_ALTO);
        if (xa > x50) {
          out.metodo = "percentili"; out.ppk = (usl - x50) / (xa - x50); out.weibull = w;
          var r = sd > 0 ? sb / sd : 1.0;
          out.cpk = r > 0 ? (usl - x50) / ((xa - x50) * r) : out.ppk;
        }
      }
      if (out.ppk === null && sd > 0) { out.ppk = (usl - m) / (3 * sd); out.cpk = sb > 0 ? (usl - m) / (3 * sb) : null; }
    } else {
      if (sb > 0) { out.cp = banda / (6 * sb); out.cpk = Math.min(usl - m, m - lsl) / (3 * sb); }
      if (sd > 0) { out.pp = banda / (6 * sd); out.ppk = Math.min(usl - m, m - lsl) / (3 * sd); }
    }
    var valori = [out.cpk, out.ppk].filter(function (v) { return v !== null && v !== undefined; });
    out.indice = valori.length ? Math.min.apply(null, valori) : null;
    var ic = intervalloCpk(out.indice, n); out.cpk_basso = ic[0]; out.cpk_alto = ic[1];
    out.verdetto = verdetto(out.indice, n);
    return out;
  }

  /* Base congelata dei limiti di controllo: la prima meta, almeno 15 pezzi; sotto 25 pezzi tutti (come spc.py). */
  function baseControllo(n) { return n < POCHI_DATI ? n : Math.max(15, Math.floor(n / 2)); }
  function pezziBase(xs, base) {
    if (base && base >= 2 && base < xs.length && sigmaBreve(xs.slice(0, base)) > 0) return xs.slice(0, base);
    return xs;
  }
  /* Indice del primo punto del tratto finale con la tolleranza dell'ultima misura (0 = mai cambiata), come spc.py. */
  function trattoTolleranza(limiti) {
    if (!limiti.length) return 0;
    var l0 = limiti[limiti.length - 1][0], u0 = limiti[limiti.length - 1][1], i = limiti.length;
    while (i > 0 && Math.abs(limiti[i - 1][0] - l0) <= 1e-6 && Math.abs(limiti[i - 1][1] - u0) <= 1e-6) i--;
    return i;
  }
  function limitiControllo(xs, base) {
    if (xs.length < 2) return null;
    var b = pezziBase(xs, base), m = media(b), sb = sigmaBreve(b);
    return { centro: m, lcs: m + 3 * sb, lci: m - 3 * sb, sigma: sb, mr_lcs: 3.267 * sb * D2, base: b.length };
  }
  function finestre(fine, lung) {
    var tratti = [];
    fine.forEach(function (i) {
      var da = Math.max(0, i - lung + 1);
      if (tratti.length && da <= tratti[tratti.length - 1][1] + 1) tratti[tratti.length - 1][1] = i; else tratti.push([da, i]);
    });
    return tratti;
  }
  function ewma(xs, centro, sigma) {
    var z = centro, valori = [], allarmi = [];
    for (var i = 0; i < xs.length; i++) {
      z = EWMA_LAMBDA * xs[i] + (1 - EWMA_LAMBDA) * z;
      valori.push(z);
      var lim = EWMA_L * sigma * Math.sqrt(EWMA_LAMBDA / (2 - EWMA_LAMBDA) * (1 - Math.pow(1 - EWMA_LAMBDA, 2 * (i + 1))));
      if (sigma > 0 && Math.abs(z - centro) > lim) allarmi.push([i, z > centro]);
    }
    return { valori: valori, allarmi: allarmi };
  }
  var TESTI = {
    "1": ["Oltre 3σ", "misura anomala anche se in tolleranza: verificare il pezzo"],
    "2": ["9 punti dallo stesso lato", "la media si è spostata: piazzamento, utensile o correttore"],
    "3": ["6 punti in salita o discesa", "tendenza costante: usura o deriva termica"],
    "4": ["14 punti a zig-zag", "due cause che si alternano: due mandrini, due pallet, due operatori"],
    "5": ["2 su 3 oltre 2σ", "spostamento in arrivo"],
    "6": ["4 su 5 oltre 1σ", "piccolo spostamento della media"],
    "7": ["15 punti vicini alla media", "variabilità più bassa del solito: controllare misura o limiti"],
    "8": ["8 punti lontani dalla media", "due popolazioni mescolate: due macchine o due lotti"],
    "ewma": ["Spostamento (EWMA)", "piccolo spostamento persistente, visto prima che diventi deriva"]
  };
  function segnali(xs, base) {
    var n = xs.length; if (n < 9) return [];
    var bb = pezziBase(xs, base), m = media(bb), s = sigmaBreve(bb); if (s <= 0) return [];
    var z = xs.map(function (x) { return (x - m) / s; }), out = [], i, j, k;
    for (i = 0; i < n; i++) if (Math.abs(z[i]) > 3) out.push({ regola: 1, da: i, a: i, sopra: z[i] > 0 });
    function corse(lato, lung, regola) {
      var i = 0;
      while (i < n) {
        var l = lato(i); if (l === null) { i++; continue; }
        var j = i; while (j + 1 < n && lato(j + 1) === l) j++;
        if (j - i + 1 >= lung) { var g = { regola: regola, da: i, a: j }; if (regola !== 7 && regola !== 8) g.sopra = l; out.push(g); }
        i = j + 1;
      }
    }
    corse(function (i) { return z[i] !== 0 ? z[i] > 0 : null; }, 9, 2);
    i = 0;
    while (i < n - 1) {
      if (xs[i + 1] === xs[i]) { i++; continue; }
      var su = xs[i + 1] > xs[i]; j = i;
      while (j + 1 < n && (su ? xs[j + 1] > xs[j] : xs[j + 1] < xs[j])) j++;
      if (j - i + 1 >= 6) out.push({ regola: 3, da: i, a: j, sopra: su });
      i = Math.max(j, i + 1);
    }
    var segni = []; for (k = 0; k < n - 1; k++) segni.push(xs[k + 1] > xs[k] ? 1 : (xs[k + 1] < xs[k] ? -1 : 0));
    k = 0;
    while (k < segni.length) {
      j = k; while (j + 1 < segni.length && segni[j] !== 0 && segni[j + 1] === -segni[j]) j++;
      if (j - k + 2 >= 14) out.push({ regola: 4, da: k, a: j + 1 });
      k = j + 1;
    }
    [[5, 2, 3, 2.0], [6, 4, 5, 1.0]].forEach(function (r) {
      [true, false].forEach(function (lato) {
        var fine = [];
        for (var t = r[2] - 1; t < n; t++) {
          var c = 0; for (var q = t - r[2] + 1; q <= t; q++) if (lato ? z[q] > r[3] : z[q] < -r[3]) c++;
          if (c >= r[1]) fine.push(t);
        }
        finestre(fine, r[2]).forEach(function (f) { out.push({ regola: r[0], da: f[0], a: f[1], sopra: lato }); });
      });
    });
    corse(function (i) { return Math.abs(z[i]) < 1 ? true : null; }, 15, 7);
    corse(function (i) { return Math.abs(z[i]) > 1 ? true : null; }, 8, 8);
    var base = xs.slice(0, Math.max(9, Math.floor(n / 2)));
    var e = ewma(xs, media(base), sigmaBreve(base) || s);
    [true, false].forEach(function (lato) {
      var idx = e.allarmi.filter(function (a) { return a[1] === lato; }).map(function (a) { return a[0]; });
      finestre(idx, 1).forEach(function (f) { if (f[1] - f[0] + 1 >= 3) out.push({ regola: "ewma", da: f[0], a: f[1], sopra: lato }); });
    });
    out.sort(function (a, b) { return a.da - b.da || (String(a.regola) < String(b.regola) ? -1 : (String(a.regola) > String(b.regola) ? 1 : 0)); });
    return out;
  }

  function rischioProssimo(xs, lsl, usl, nom, pendenzaX) {
    if (xs.length < MIN_CAPACITA) return null;
    var sb = sigmaBreve(xs) || devStd(xs);
    var e = ewma(xs, xs[0], sb), livello = e.valori[e.valori.length - 1] + (pendenzaX || 0);
    if (unilaterale(nom, lsl, usl)) {
      var w = weibull(xs);
      if (w) {
        var m = media(xs) || 0, scala = w.lam * (m > 0 && livello > 0 ? livello / m : 1);
        return scala > 0 ? Math.exp(-Math.pow(usl / scala, w.k)) : null;
      }
      return sb > 0 ? 1 - phi((usl - livello) / sb) : (livello > usl ? 1 : 0);
    }
    if (sb <= 0) return (livello > usl || livello < lsl) ? 1 : 0;
    return phi((lsl - livello) / sb) + 1 - phi((usl - livello) / sb);
  }

  function puntiCambio(xs, maxCambi, minSeg) {
    maxCambi = maxCambi || 3; minSeg = minSeg || 6;
    var n = xs.length, sb = sigmaBreve(xs);
    if (n < 2 * minSeg || sb <= 0) return [];
    var pen = 3 * sb * sb * Math.log(n);
    function costo(a, b) { var seg = xs.slice(a, b), m = media(seg), s = 0; seg.forEach(function (x) { s += (x - m) * (x - m); }); return s; }
    var tagli = [], segmenti = [[0, n]];
    while (segmenti.length && tagli.length < maxCambi) {
      var migliore = null;
      segmenti.forEach(function (sg) {
        var a = sg[0], b = sg[1]; if (b - a < 2 * minSeg) return;
        var tot = costo(a, b);
        for (var t = a + minSeg; t <= b - minSeg; t++) {
          var g = tot - costo(a, t) - costo(t, b);
          if (migliore === null || g > migliore[0]) migliore = [g, a, t, b];
        }
      });
      if (!migliore || migliore[0] <= pen) break;
      var a = migliore[1], t = migliore[2], b = migliore[3];
      var m1 = media(xs.slice(a, t)), m2 = media(xs.slice(t, b));
      segmenti = segmenti.filter(function (sg) { return !(sg[0] === a && sg[1] === b); });
      if (Math.abs(m2 - m1) >= sb) { tagli.push(t); segmenti.push([a, t], [t, b]); }
    }
    tagli.sort(function (x, y) { return x - y; });
    var bordi = [0].concat(tagli, [n]);
    return tagli.map(function (t, i) { return { indice: t, prima: media(xs.slice(bordi[i], t)), dopo: media(xs.slice(t, bordi[i + 2])) }; });
  }

  return { media: media, dev_std: devStd, sigma_breve: sigmaBreve, unilaterale: unilaterale, phi: phi, weibull: weibull,
    capacita: capacita, intervallo_cpk: intervalloCpk, verdetto: verdetto, limiti_controllo: limitiControllo, ewma: ewma,
    segnali: segnali, testi: TESTI, rischio_prossimo: rischioProssimo, punti_cambio: puntiCambio, CAPACE: CAPACE,
    usata: usata, deriva: deriva, base_controllo: baseControllo, tratto_tolleranza: trattoTolleranza, sotto_obiettivo: sottoObiettivo, da_guardare: daGuardare, TOLLERANZA_AL_LIMITE: 0.8 };
})();
if (typeof window !== "undefined") window.SPC = SPC;
