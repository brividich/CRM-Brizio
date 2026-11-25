/* Analisi quote CMM (Ordini di produzione › P/N › Analisi quote).
   Dati da /produzione/api/quote/ (un programma alla volta); filtri, viste e grafici qui, senza librerie.
   Testi che arrivano dai report (nomi, S/N, gruppi) sempre con textContent. */
(function () {
  'use strict';
  const root = document.querySelector('[data-analisi]');
  if (!root || !document.getElementById('aq-stato')) return;

  const SVG = 'http://www.w3.org/2000/svg';
  const iniziale = JSON.parse(document.getElementById('aq-stato').textContent || '{}');
  const $ = (sel, el) => (el || root).querySelector(sel);
  const $$ = (sel, el) => Array.from((el || root).querySelectorAll(sel));
  const tooltip = $('[data-tooltip]');

  const S = {
    prog: iniziale.prog || '', per: iniziale.per || '', da: iniziale.da || '', a: iniziale.a || '',
    ops: new Set((iniziale.op || '').split('~').filter(Boolean)), sn: /^\d+$/.test(iniziale.r || '') ? +iniziale.r : null,
    tab: ['quota', 'mappa', 'confronto', 'pezzo'].includes(iniziale.tab) ? iniziale.tab : 'quota',
    q: iniziale.q || '', nom: iniziale.nom || '', cmp: (iniziale.cmp || '').split('~').filter(Boolean),
    filtro: iniziale.f || 'tutte', ord: iniziale.ord || '', cerca: '',
    media: true, sigma: false, perOp: false, scala: 'valore', zoom: null, pezzo2: null,
  };
  let D = null;          // dati del programma
  let vis = [];          // report visibili (filtro OP)
  let info = [];         // per quota: punti visibili e statistiche
  let richiesta = 0;

  /* ── utilità ─────────────────────────────────────────────────────────── */
  const el = (tag, attrs, ...figli) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    figli.flat().forEach(f => { if (f !== null && f !== undefined && f !== false) n.append(f.nodeType ? f : document.createTextNode(String(f))); });
    return n;
  };
  const sv = (tag, attrs) => {
    const n = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) n.setAttribute(k, v);
    return n;
  };
  const num = (v, d = 4) => (v === null || v === undefined || !isFinite(v)) ? '—' : v.toFixed(d).replace('.', ',');
  const pct = v => (v === null || v === undefined || !isFinite(v)) ? '—' : `${Math.round(v * 100)}%`;
  const segno = (v, d = 4) => (v > 0 ? '+' : '') + num(v, d);
  const dataIt = iso => iso ? iso.split('-').reverse().join('/') : '—';
  const css = nome => getComputedStyle(root).getPropertyValue(nome).trim();
  const urlReport = id => root.dataset.urlReport.replace(/0\/?$/, `${id}/`);

  function ticks(lo, hi, n = 5) {
    const passo0 = (hi - lo) / Math.max(n, 1);
    const p = Math.pow(10, Math.floor(Math.log10(passo0 || 1)));
    const passo = [1, 2, 2.5, 5, 10].map(m => m * p).find(s => s >= passo0) || passo0;
    const out = [];
    for (let v = Math.ceil(lo / passo) * passo; v <= hi + passo * 1e-9; v += passo) out.push(+v.toFixed(10));
    return out;
  }
  function decimali(lo, hi) {
    const r = Math.abs(hi - lo);
    return r >= 50 ? 1 : r >= 5 ? 2 : r >= 0.5 ? 3 : 4;
  }

  /* Quanta tolleranza usa una misura: 0 = ideale, +-1 = limite (segno: sopra o sotto).
     Forma, posizione, concentricita (nominale 0 e limite inferiore 0): ideale 0, si conta verso il limite superiore.
     Le altre: dal centro della zona di tolleranza. */
  const unilaterale = (nom, lsl, usl) => Math.abs(nom) < 1e-12 && Math.abs(lsl) < 1e-12 && usl > 0;
  function usata(x, nom, lsl, usl) {
    if (unilaterale(nom, lsl, usl)) return x / usl;
    const banda = usl - lsl;
    return banda > 0 ? (x - (usl + lsl) / 2) / (banda / 2) : null;
  }
  function statistiche(pts) {
    const n = pts.length;
    if (!n) return { n: 0 };
    const xs = pts.map(p => p.x);
    const media = xs.reduce((a, b) => a + b, 0) / n;
    const sd = n > 1 ? Math.sqrt(xs.reduce((a, x) => a + (x - media) ** 2, 0) / (n - 1)) : 0;
    const ult = pts[n - 1];
    const banda = ult.usl - ult.lsl;
    const s = { n, media, sd, min: Math.min(...xs), max: Math.max(...xs), ultimo: ult, cp: null, cpk: null,
      nFuori: pts.filter(p => p.f).length, nVer: pts.filter(p => p.dv).length };
    if (n >= 5 && sd > 0 && banda > 0) {
      if (ult.uni) {
        s.cpk = (ult.usl - media) / (3 * sd);   // solo limite superiore: Cpk = CPU, Cp non si calcola
      } else {
        s.cp = banda / (6 * sd);
        s.cpk = Math.min(ult.usl - media, media - ult.lsl) / (3 * sd);
      }
    }
    return s;
  }
  const statoCpk = cpk => cpk === null || cpk === undefined ? null
    : cpk >= 1.33 ? { c: 'ok', t: 'Capace' } : cpk >= 1 ? { c: 'warn', t: 'Al limite' } : { c: 'crit', t: 'Non capace' };
  const vicina = s => s.n && !s.ultimo.f && s.ultimo.u !== null && Math.abs(s.ultimo.u) >= 0.8;

  /* ── stato nell'indirizzo (link condivisibili) ───────────────────────── */
  function salvaUrl() {
    const p = new URLSearchParams({ pn: root.dataset.pn, prog: S.prog });
    if (S.q) p.set('q', S.q);
    if (S.tab !== 'quota') p.set('tab', S.tab);
    if (S.per) p.set('per', S.per);
    if (S.per === 'custom') { if (S.da) p.set('da', S.da); if (S.a) p.set('a', S.a); }
    if (S.ops.size) p.set('op', [...S.ops].join('~'));
    if (S.cmp.length) p.set('cmp', S.cmp.join('~'));
    if (S.sn) p.set('r', S.sn);
    if (S.filtro !== 'tutte') p.set('f', S.filtro);
    if (S.ord) p.set('ord', S.ord);
    history.replaceState(null, '', `${root.dataset.urlPagina}?${p}`);
  }

  /* ── dati ────────────────────────────────────────────────────────────── */
  function periodo() {
    if (S.per === 'custom') return { da: S.da, a: S.a };
    if (!S.per) return { da: '', a: '' };
    const d = new Date(); d.setDate(d.getDate() - (+S.per));
    return { da: d.toISOString().slice(0, 10), a: '' };
  }
  async function carica() {
    const mia = ++richiesta;
    root.classList.add('is-carica');
    const { da, a } = periodo();
    const p = new URLSearchParams({ pn: root.dataset.pn, prog: S.prog });
    if (da) p.set('da', da);
    if (a) p.set('a', a);
    try {
      const r = await fetch(`${root.dataset.api}?${p}`, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
      const j = await r.json();
      if (mia !== richiesta) return;
      if (!r.ok || !j.ok) throw new Error(j.error || `HTTP ${r.status}`);
      D = j;
      risolviQuota();
      S.cmp = S.cmp.filter(id => D.quote.some(q => q.id === id));
      if (S.sn && !D.report.some(r => r[0] === S.sn)) S.sn = null;
      $('[data-azione="csv"]').disabled = false;
      calcola();
      disegnaTutto();
    } catch (e) {
      if (mia !== richiesta) return;
      const av = $('[data-avviso]');
      av.textContent = `Dati non caricati: ${e.message}`;
      av.hidden = false;
    } finally {
      if (mia === richiesta) root.classList.remove('is-carica');
    }
  }
  function risolviQuota() {
    if (!D.quote.length) { S.q = ''; return; }
    if (D.quote.some(q => q.id === S.q)) return;
    if (S.q) {   // link da un report: q = nome (chiave) e nom = nominale
      const chiave = S.q.split('|')[0];
      const con = D.quote.filter(q => q.id.split('|')[0] === chiave);
      const nom = S.nom ? con.find(q => Math.abs(q.nominale - parseFloat(S.nom)) < 5e-5) : null;
      const t = nom || con[con.length - 1];
      if (t) { S.q = t.id; S.nom = ''; return; }
    }
    S.q = '';
  }
  function calcola() {
    vis = D.report.map(r => !S.ops.size || S.ops.has(r[2] || '—'));
    info = D.quote.map((q, qi) => {
      const pts = [];
      for (const v of D.valori[qi]) {
        if (!vis[v[0]] || v[1] === null) continue;
        const lsl = q.nominale + v[3], usl = q.nominale + v[2];
        pts.push({ ri: v[0], x: v[1], ts: v[2], ti: v[3], f: !!v[4], fd: v[5], dv: !!v[6], lsl, usl,
          uni: unilaterale(q.nominale, lsl, usl), u: usata(v[1], q.nominale, lsl, usl) });
      }
      return { q, qi, pts, s: statistiche(pts) };
    });
  }

  /* ── filtri globali ──────────────────────────────────────────────────── */
  function disegnaFiltri() {
    $$('[data-filtro="per"] button').forEach(b => b.classList.toggle('is-on', b.dataset.v === S.per));
    $('[data-date]').hidden = S.per !== 'custom';
    $('[data-filtro="da"]').value = S.da;
    $('[data-filtro="a"]').value = S.a;
    // OP: elenco con conteggi, spunte
    const conta = new Map();
    D.report.forEach(r => conta.set(r[2] || '—', (conta.get(r[2] || '—') || 0) + 1));
    const lista = $('[data-op-lista]');
    lista.replaceChildren();
    [...conta.entries()].sort((a, b) => b[0].localeCompare(a[0])).forEach(([op, n]) => {
      const cb = el('input', { type: 'checkbox', value: op, checked: S.ops.has(op) });
      cb.addEventListener('change', () => {
        cb.checked ? S.ops.add(op) : S.ops.delete(op);
        aggiorna();
      });
      lista.append(el('label', {}, cb, el('span', { text: op }), el('small', { text: `${n}` })));
    });
    lista.append(el('div', { class: 'aq-pop-azioni' },
      el('button', { type: 'button', text: 'Tutti', onclick: () => { S.ops.clear(); aggiorna(); disegnaFiltri(); } }),
      el('button', { type: 'button', text: 'Solo l\'ultimo', onclick: () => {
        const ult = D.report.length ? (D.report[D.report.length - 1][2] || '—') : null;
        S.ops = new Set(ult ? [ult] : []); aggiorna(); disegnaFiltri();
      } })));
    $('[data-op-etichetta]').textContent = S.ops.size ? (S.ops.size === 1 ? [...S.ops][0] : `${S.ops.size} scelti`) : 'tutti';
    const dl = $('#aq-sn');
    dl.replaceChildren(...D.report.slice().reverse().map(r => el('option', { value: r[1] }, `${r[2] || ''} · ${dataIt(r[3])}`)));
    const scelto = D.report.find(r => r[0] === S.sn);
    $('[data-filtro="sn"]').value = scelto ? scelto[1] : '';
  }
  function aggiorna() { calcola(); disegnaTutto(); }

  $('[data-filtro="prog"]').addEventListener('change', e => { S.prog = e.target.value; S.q = ''; S.cmp = []; S.zoom = null; carica(); });
  $$('[data-filtro="per"] button').forEach(b => b.addEventListener('click', () => {
    S.per = b.dataset.v; S.zoom = null;
    disegnaFiltri();
    if (S.per !== 'custom' || (S.da || S.a)) carica();
  }));
  ['da', 'a'].forEach(k => $(`[data-filtro="${k}"]`).addEventListener('change', e => { S[k] = e.target.value; carica(); }));
  $('[data-filtro="sn"]').addEventListener('change', e => {
    const v = e.target.value.trim().toLowerCase();
    const r = D && D.report.slice().reverse().find(x => (x[1] || '').toLowerCase() === v);
    S.sn = r ? r[0] : null;
    disegnaTutto();
  });
  $('[data-filtro="cerca"]').addEventListener('input', e => { S.cerca = e.target.value.trim().toLowerCase(); disegnaLista(); if (S.tab === 'mappa' || S.tab === 'pezzo') disegnaVista(); });
  $('[data-filtro="ord"]').value = S.ord;
  $('[data-filtro="ord"]').addEventListener('change', e => { S.ord = e.target.value; disegnaLista(); salvaUrl(); });
  $$('[data-tab]').forEach(b => b.addEventListener('click', () => { S.tab = b.dataset.tab; disegnaTutto(); }));
  document.addEventListener('click', e => { const pop = $('[data-pop="op"]'); if (pop.open && !pop.contains(e.target)) pop.open = false; });

  /* ── KPI del programma ───────────────────────────────────────────────── */
  function disegnaKpi() {
    const box = $('[data-kpi]');
    const rv = D.report.filter((r, i) => vis[i]);
    const sn = new Set(rv.map(r => r[1]));
    let mis = 0, fuori = 0;
    info.forEach(x => { mis += x.pts.length; fuori += x.s.nFuori || 0; });
    const nonCap = info.filter(x => x.s.cpk !== null && x.s.cpk !== undefined && x.s.cpk < 1.33).length;
    const conFuori = info.filter(x => x.s.nFuori).length;
    const ult = rv[rv.length - 1];
    const tile = (et, val, sub, opts = {}) => el(opts.onclick ? 'button' : 'div', { class: `aq-tile${opts.allerta ? ' is-allerta' : ''}`, type: opts.onclick ? 'button' : null, onclick: opts.onclick, title: opts.title },
      el('span', { text: et }), el('b', { text: val }), sub ? el('small', { text: sub }) : null);
    box.replaceChildren(
      tile('Report', `${rv.length}`, D.tagliati ? `ultimi ${D.limite} di ${D.totale}: restringi il periodo` : `${sn.size} S/N`),
      tile('Quote', `${info.filter(x => x.pts.length).length}`, `${mis} misure`),
      tile('Misure fuori', mis ? pct(fuori / mis) : '—', `${fuori} su ${mis}`, { allerta: fuori > 0 }),
      tile('Quote andate fuori', `${conFuori}`, 'almeno una volta', { allerta: conFuori > 0, onclick: () => scegliFiltro('fuori'), title: 'Mostra solo queste' }),
      tile('Cpk sotto 1,33', `${nonCap}`, 'processo non capace o al limite', { allerta: nonCap > 0, onclick: () => scegliFiltro('cpk'), title: 'Mostra solo queste' }),
      tile('Ultimo report', ult ? dataIt(ult[3]) : '—', ult ? `${ult[1]} · ${ult[2] || ''}` : ''),
    );
    const av = $('[data-avviso]');
    av.hidden = !D.tagliati;
    if (D.tagliati) av.textContent = `Mostrati i ${D.limite} report più recenti su ${D.totale}: scegli un periodo per vedere i più vecchi.`;
  }

  /* ── elenco delle quote ──────────────────────────────────────────────── */
  const FILTRI = [
    ['tutte', 'Tutte', () => true],
    ['fuori', 'Andate fuori', x => x.s.nFuori > 0],
    ['cpk', 'Cpk < 1,33', x => x.s.cpk !== null && x.s.cpk !== undefined && x.s.cpk < 1.33],
    ['limite', 'Vicine al limite', x => vicina(x.s)],
    ['verifica', 'Da verificare', x => x.s.nVer > 0],
  ];
  function scegliFiltro(f) { S.filtro = f; disegnaLista(); if (S.tab !== 'quota' && S.tab !== 'confronto') disegnaVista(); salvaUrl(); }
  function quoteFiltrate() {
    const f = (FILTRI.find(x => x[0] === S.filtro) || FILTRI[0])[2];
    let l = info.filter(x => x.pts.length && f(x));
    if (S.cerca) l = l.filter(x => `${x.q.nome} ${x.q.sezione}`.toLowerCase().includes(S.cerca));
    const per = {
      fuori: (a, b) => b.s.nFuori - a.s.nFuori,
      cpk: (a, b) => (a.s.cpk ?? 99) - (b.s.cpk ?? 99),
      limite: (a, b) => Math.abs(b.s.ultimo.u ?? 0) - Math.abs(a.s.ultimo.u ?? 0),
      nome: (a, b) => a.q.nome.localeCompare(b.q.nome, 'it', { numeric: true }),
    }[S.ord];
    return per ? l.slice().sort(per) : l;
  }
  function sparkline(x) {
    const pts = x.pts.slice(-30).filter(p => p.u !== null);
    const s = sv('svg', { class: 'aq-spark', viewBox: '0 0 64 20', 'aria-hidden': 'true' });
    s.append(sv('rect', { x: 0, y: 4, width: 64, height: 12, fill: 'var(--aq-banda)' }));
    if (pts.length > 1) {
      const y = u => (10 - Math.max(-1.6, Math.min(1.6, u)) * 6).toFixed(1);
      const xx = i => (i * 62 / (pts.length - 1) + 1).toFixed(1);
      s.append(sv('polyline', { points: pts.map((p, i) => `${xx(i)},${y(p.u)}`).join(' '), fill: 'none', stroke: 'var(--aq-serie)', 'stroke-width': 1.3 }));
      pts.forEach((p, i) => { if (p.f) s.append(sv('circle', { cx: xx(i), cy: y(p.u), r: 1.8, fill: 'var(--aq-crit)' })); });
    }
    return s;
  }
  function badge(x) {
    if (x.s.nFuori) return el('span', { class: 'aq-badge is-crit', title: `${x.s.nFuori} volte fuori su ${x.s.n}` }, `${x.s.nFuori} fuori`);
    const st = statoCpk(x.s.cpk);
    if (st) return el('span', { class: `aq-badge is-${st.c}`, title: `Cpk ${num(x.s.cpk, 2)}: ${st.t}` }, `Cpk ${num(x.s.cpk, 2)}`);
    return el('span', { class: 'aq-badge' }, `${x.s.n}`);
  }
  function disegnaLista() {
    const chips = $('[data-chips]');
    chips.replaceChildren(...FILTRI.map(([k, et, f]) => {
      const n = info.filter(x => x.pts.length && f(x)).length;
      return el('button', { type: 'button', class: `aq-chip${S.filtro === k ? ' is-on' : ''}`, 'aria-pressed': S.filtro === k ? 'true' : 'false', onclick: () => scegliFiltro(k) }, et, el('b', { text: `${n}` }));
    }));
    const box = $('[data-lista]');
    const l = quoteFiltrate();
    box.replaceChildren();
    if (!l.length) { box.append(el('p', { class: 'aq-vuoto', text: 'Nessuna quota con questi filtri.' })); return; }
    let gruppo = null;
    l.forEach(x => {
      if (!S.ord && x.q.sezione !== gruppo) { gruppo = x.q.sezione; box.append(el('div', { class: 'aq-gruppo', text: gruppo || 'Senza gruppo' })); }
      const cb = el('input', { type: 'checkbox', title: 'Confronta', 'aria-label': `Confronta ${x.q.nome}`, checked: S.cmp.includes(x.q.id) });
      cb.addEventListener('click', e => e.stopPropagation());
      cb.addEventListener('change', () => {
        if (cb.checked) { if (S.cmp.length >= 6) { cb.checked = false; return; } S.cmp.push(x.q.id); } else S.cmp = S.cmp.filter(id => id !== x.q.id);
        $('[data-conta-cmp]').textContent = S.cmp.length || '';
        if (S.tab === 'confronto') disegnaVista();
        salvaUrl();
      });
      const voce = el('div', { class: `aq-voce${x.q.id === S.q ? ' is-on' : ''}`, role: 'option', tabindex: 0, 'aria-selected': x.q.id === S.q ? 'true' : 'false',
        onclick: () => apriQuota(x.q.id), onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); apriQuota(x.q.id); } } },
        cb,
        el('div', { class: 'aq-voce-nome' }, el('b', { text: x.q.nome }), el('small', { text: `${S.ord ? (x.q.sezione || '') + ' · ' : ''}nom. ${num(x.q.nominale)}` })),
        sparkline(x), badge(x));
      box.append(voce);
    });
    const on = box.querySelector('.aq-voce.is-on');
    if (on && S.tab === 'quota') on.scrollIntoView({ block: 'nearest' });
  }
  function apriQuota(id, sn) {
    S.q = id; S.tab = 'quota';
    if (sn) S.sn = sn;
    disegnaTutto();
  }

  /* ── tooltip ─────────────────────────────────────────────────────────── */
  function mostraTooltip(ev, righe) {
    tooltip.replaceChildren(...righe.filter(Boolean));   // le righe facoltative arrivano come null
    tooltip.hidden = false;
    const w = tooltip.offsetWidth, h = tooltip.offsetHeight;
    let x = ev.clientX + 14, y = ev.clientY + 14;
    if (x + w > innerWidth - 8) x = ev.clientX - w - 14;
    if (y + h > innerHeight - 8) y = ev.clientY - h - 14;
    tooltip.style.left = `${Math.max(8, x)}px`;
    tooltip.style.top = `${Math.max(8, y)}px`;
  }
  const nascondiTooltip = () => { tooltip.hidden = true; };
  const tRiga = (...c) => el('div', { class: 't-riga' }, ...c);

  /* ── grafico dell'andamento (una quota) ──────────────────────────────── */
  function nelZoom(ri) { return !S.zoom || (ri >= S.zoom[0] && ri <= S.zoom[1]); }
  function coloriOp() {
    // al massimo 3 OP colorati (i più recenti); gli altri grigi: oltre tre i colori dei punti si confondono
    const ops = [];
    for (let i = D.report.length - 1; i >= 0 && ops.length < 3; i--) if (vis[i] && !ops.includes(D.report[i][2] || '—')) ops.push(D.report[i][2] || '—');
    const m = new Map(ops.map((o, i) => [o, `var(--aq-c${i + 1})`]));
    return { m, col: op => m.get(op || '—') || 'var(--aq-altro)' };
  }
  function graficoQuota(box, x) {
    const pts = x.pts.filter(p => nelZoom(p.ri));
    const W = Math.max(420, box.clientWidth || 800), H = 340, L = 66, R = 18, T = 14, B = 46;
    const pc = S.scala === 'pct';
    const val = p => pc ? p.u * 100 : p.x;
    const s = statistiche(pts);
    let lo = Infinity, hi = -Infinity;
    const infPc = p => p.uni ? 0 : -100;
    pts.forEach(p => {
      const v = val(p); if (v === null || !isFinite(v)) return;
      lo = Math.min(lo, v, pc ? infPc(p) : p.lsl); hi = Math.max(hi, v, pc ? 100 : p.usl);
    });
    if (S.sigma && s.sd > 0 && !pc) { lo = Math.min(lo, s.media - 3 * s.sd); hi = Math.max(hi, s.media + 3 * s.sd); }
    if (!isFinite(lo)) { lo = -1; hi = 1; }
    if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const n = pts.length;
    const X = i => L + (n > 1 ? i * (W - L - R) / (n - 1) : (W - L - R) / 2);
    const Y = v => T + (hi - v) / (hi - lo) * (H - T - B);
    const svg = sv('svg', { class: 'aq-svg', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Andamento di ${x.q.nome}: ${n} misure, ${s.nFuori || 0} fuori tolleranza` });
    const dec = pc ? 0 : decimali(lo, hi);
    ticks(lo, hi).forEach(t => {
      svg.append(sv('line', { class: 'g-griglia', x1: L, x2: W - R, y1: Y(t), y2: Y(t) }));
      const tx = sv('text', { x: L - 6, y: Y(t), 'text-anchor': 'end', 'dominant-baseline': 'middle' });
      tx.textContent = pc ? `${Math.round(t)}%` : num(t, dec);
      svg.append(tx);
    });
    svg.append(sv('line', { class: 'g-asse', x1: L, x2: W - R, y1: H - B, y2: H - B }));
    if (n) {
      // banda di tolleranza (i limiti possono cambiare fra le revisioni)
      const sup = pts.map((p, i) => `${X(i)},${Y(pc ? 100 : p.usl)}`);
      const inf = pts.map((p, i) => `${X(i)},${Y(pc ? infPc(p) : p.lsl)}`).reverse();
      svg.append(sv('polygon', { class: 'g-banda', points: n > 1 ? [...sup, ...inf].join(' ') : `${L},${Y(pc ? 100 : pts[0].usl)} ${W - R},${Y(pc ? 100 : pts[0].usl)} ${W - R},${Y(pc ? infPc(pts[0]) : pts[0].lsl)} ${L},${Y(pc ? infPc(pts[0]) : pts[0].lsl)}` }));
      const linea = f => n > 1 ? pts.map((p, i) => `${X(i)},${Y(f(p))}`).join(' ') : `${L},${Y(f(pts[0]))} ${W - R},${Y(f(pts[0]))}`;
      svg.append(sv('polyline', { class: 'g-limite', points: linea(p => pc ? 100 : p.usl) }));
      svg.append(sv('polyline', { class: 'g-limite', points: linea(p => pc ? infPc(p) : p.lsl) }));
      const uNom = p => (usata(x.q.nominale, x.q.nominale, p.lsl, p.usl) ?? 0) * 100;
      svg.append(sv('polyline', { class: 'g-nominale', points: linea(p => pc ? uNom(p) : x.q.nominale) }));
      if (S.media && s.n && !pc) svg.append(sv('line', { class: 'g-media', x1: L, x2: W - R, y1: Y(s.media), y2: Y(s.media) }));
      if (S.sigma && s.sd > 0 && !pc) [-3, 3].forEach(k => svg.append(sv('line', { class: 'g-sigma', x1: L, x2: W - R, y1: Y(s.media + k * s.sd), y2: Y(s.media + k * s.sd) })));
      const colori = coloriOp();
      svg.append(sv('polyline', { class: 'g-linea', points: pts.map((p, i) => `${X(i)},${Y(val(p))}`).join(' '), stroke: S.perOp ? 'var(--aq-altro)' : 'var(--aq-serie)', 'stroke-opacity': S.perOp ? 0.6 : 1 }));
      const r = n > 150 ? 2.5 : n > 60 ? 3.2 : 4;
      pts.forEach((p, i) => {
        const rep = D.report[p.ri];
        const c = sv('circle', { class: `g-punto${p.f ? ' is-fuori' : ''}${rep[0] === S.sn ? ' is-scelto' : ''}`, cx: X(i), cy: Y(val(p)), r: rep[0] === S.sn ? r + 2.5 : r,
          fill: p.f ? null : (S.perOp ? colori.col(rep[2]) : 'var(--aq-serie)') });
        svg.append(c);
      });
      // etichette in basso: S/N se pochi, altrimenti alcune date
      const ogni = Math.max(1, Math.ceil(n / Math.floor((W - L - R) / 70)));
      pts.forEach((p, i) => {
        if (i % ogni && i !== n - 1) return;
        const rep = D.report[p.ri];
        const t = sv('text', { x: X(i), y: H - B + 16, 'text-anchor': 'middle' });
        t.textContent = n <= 30 ? (rep[1] || '').slice(0, 11) : dataIt(rep[3]).slice(0, 5);
        svg.append(t);
      });
      // selezionato: etichetta
      const kSel = pts.findIndex(p => D.report[p.ri][0] === S.sn);
      if (kSel >= 0) {
        const t = sv('text', { class: 'g-etichetta', x: Math.min(X(kSel) + 8, W - R - 80), y: Y(val(pts[kSel])) - 10 });
        t.textContent = D.report[pts[kSel].ri][1];
        svg.append(t);
      }
      interattivo(svg, { W, H, L, R, T, B, n, X, pts, valore: val, onHover: (ev, k) => {
        const p = pts[k], rep = D.report[p.ri];
        mostraTooltip(ev, [
          el('b', { text: num(p.x) }), p.f ? el('span', { class: 't-fuori', text: `  fuori di ${segno(p.fd ?? 0)}` }) : null,
          el('div', { text: `${rep[1]} · ${rep[2] || '—'} · ${dataIt(rep[3])}` }),
          el('div', { class: 't-sub', text: `Nominale ${num(x.q.nominale)} · limiti ${num(p.lsl)} ÷ ${num(p.usl)}` }),
          el('div', { class: 't-sub', text: `Tolleranza usata ${p.u === null ? '—' : pct(Math.abs(p.u))}${p.dv ? ' · da verificare' : ''}` }),
          el('div', { class: 't-sub', text: 'Clic: evidenzia il S/N · doppio clic: apri il report' }),
        ]);
      }, onClick: k => { S.sn = D.report[pts[k].ri][0]; disegnaTutto(); },
      onDbl: k => { location.href = urlReport(D.report[pts[k].ri][0]); },
      onZoom: (k0, k1) => { S.zoom = [pts[k0].ri, pts[k1].ri]; disegnaVista(); } });
    } else {
      const t = sv('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle' }); t.textContent = 'Nessuna misura con questi filtri.'; svg.append(t);
    }
    box.replaceChildren(svg);
    return { s, colori: S.perOp ? coloriOp() : null, dominio: n ? { lo, hi, val } : null };
  }

  /* croce che segue il puntatore sul punto più vicino in X; trascina per lo zoom */
  function interattivo(svg, o) {
    const croce = sv('line', { class: 'g-croce', y1: o.T, y2: o.H - o.B, visibility: 'hidden' });
    const sel = sv('rect', { class: 'g-selezione', y: o.T, height: o.H - o.T - o.B, visibility: 'hidden' });
    const area = sv('rect', { x: o.L - 8, y: 0, width: o.W - o.L - o.R + 16, height: o.H, fill: 'transparent', tabindex: 0,
      'aria-label': 'Grafico: frecce per scorrere i punti, Invio per evidenziare' });
    svg.append(croce, sel, area);
    const pt = ev => { const r = svg.getBoundingClientRect(); return (ev.clientX - r.left) * o.W / r.width; };
    const vicino = xx => { let b = 0, d = Infinity; for (let k = 0; k < o.n; k++) { const dd = Math.abs(o.X(k) - xx); if (dd < d) { d = dd; b = k; } } return b; };
    let inizio = null, corrente = 0;
    const segna = (ev, k) => { corrente = k; croce.setAttribute('x1', o.X(k)); croce.setAttribute('x2', o.X(k)); croce.setAttribute('visibility', 'visible'); o.onHover(ev, k); };
    area.addEventListener('pointerdown', ev => { inizio = pt(ev); area.setPointerCapture(ev.pointerId); });
    area.addEventListener('pointermove', ev => {
      const xx = pt(ev);
      if (inizio !== null && Math.abs(xx - inizio) > 8 && o.onZoom) {
        sel.setAttribute('x', Math.min(xx, inizio)); sel.setAttribute('width', Math.abs(xx - inizio)); sel.setAttribute('visibility', 'visible');
        nascondiTooltip();
        return;
      }
      segna(ev, vicino(xx));
    });
    area.addEventListener('pointerup', ev => {
      const xx = pt(ev);
      if (inizio !== null && Math.abs(xx - inizio) > 8 && o.onZoom) {
        const a = vicino(Math.min(xx, inizio)), b = vicino(Math.max(xx, inizio));
        inizio = null; sel.setAttribute('visibility', 'hidden');
        if (b > a) o.onZoom(a, b);
        return;
      }
      inizio = null;
      if (o.onClick) o.onClick(vicino(xx));
    });
    area.addEventListener('dblclick', ev => { if (o.onDbl) o.onDbl(vicino(pt(ev))); });
    area.addEventListener('pointerleave', () => { croce.setAttribute('visibility', 'hidden'); nascondiTooltip(); });
    area.addEventListener('keydown', ev => {
      if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
        ev.preventDefault();
        const k = Math.max(0, Math.min(o.n - 1, corrente + (ev.key === 'ArrowRight' ? 1 : -1)));
        const r = svg.getBoundingClientRect();
        segna({ clientX: r.left + o.X(k) * r.width / o.W, clientY: r.top + 40 }, k);
      } else if (ev.key === 'Enter' && o.onClick) o.onClick(corrente);
    });
    area.addEventListener('blur', () => { croce.setAttribute('visibility', 'hidden'); nascondiTooltip(); });
  }

  /* istogramma dei valori con i limiti */
  function istogramma(box, x, dominio) {
    const pts = x.pts.filter(p => nelZoom(p.ri) && dominio.val(p) !== null && isFinite(dominio.val(p)));
    const W = 230, H = 340, L = 10, R = 10, T = 14, B = 46;
    const pc = S.scala === 'pct';
    const svg = sv('svg', { class: 'aq-svg', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Distribuzione di ${x.q.nome}` });
    if (pts.length < 2) { box.replaceChildren(svg); return; }
    const ult = pts[pts.length - 1];
    const { lo, hi, val } = dominio;       // stessa scala verticale del grafico accanto
    const LSL = pc ? (ult.uni ? 0 : -100) : ult.lsl, USL = pc ? 100 : ult.usl;
    const nb = Math.max(8, Math.min(30, Math.ceil(Math.sqrt(pts.length)) + 4));
    const passo = (hi - lo) / nb;
    const conta = Array(nb).fill(0);
    pts.forEach(p => { conta[Math.max(0, Math.min(nb - 1, Math.floor((val(p) - lo) / passo)))]++; });
    const max = Math.max(...conta);
    // valori in verticale (stessa direzione del grafico accanto), conteggi in orizzontale
    const Y = v => T + (hi - v) / (hi - lo) * (H - T - B);
    const Xc = c => L + c / max * (W - L - R - 24);
    conta.forEach((c, i) => {
      if (!c) return;
      const v0 = lo + i * passo, v1 = v0 + passo, centro = (v0 + v1) / 2;
      const fuori = centro < LSL || centro > USL;
      const y0 = Y(v1) + 1, h = Math.max(1, Y(v0) - Y(v1) - 2);
      const b = sv('rect', { class: `g-barra${fuori ? ' is-fuori' : ''}`, x: L, y: y0, width: Math.max(2, Xc(c) - L), height: h, rx: 2 });
      const fv = v => pc ? `${Math.round(v)}%` : num(v);
      b.addEventListener('pointermove', ev => mostraTooltip(ev, [el('b', { text: `${c}` }), el('span', { text: ` misure fra ${fv(v0)} e ${fv(v1)}` })]));
      b.addEventListener('pointerleave', nascondiTooltip);
      svg.append(b);
    });
    [LSL, USL].forEach(v => svg.append(sv('line', { class: 'g-limite', x1: L, x2: W - R, y1: Y(v), y2: Y(v) })));
    if (!pc) {
      svg.append(sv('line', { class: 'g-nominale', x1: L, x2: W - R, y1: Y(x.q.nominale), y2: Y(x.q.nominale) }));
      const m = statistiche(pts).media;
      svg.append(sv('line', { class: 'g-media', x1: L, x2: W - R, y1: Y(m), y2: Y(m) }));
    }
    const t = sv('text', { x: W / 2, y: H - B + 16, 'text-anchor': 'middle' }); t.textContent = 'Distribuzione'; svg.append(t);
    box.replaceChildren(svg);
  }

  function vistaQuota(pane) {
    const x = info.find(i => i.q.id === S.q) || quoteFiltrate()[0];
    if (!x) { pane.replaceChildren(el('div', { class: 'aq-card' }, el('p', { class: 'aq-vuoto', text: 'Nessuna quota con questi filtri.' }))); return; }
    S.q = x.q.id;
    const card = el('div', { class: 'aq-card' });
    const toggle = (et, chiave, titolo) => el('button', { type: 'button', class: 'aq-toggle', 'aria-pressed': S[chiave] ? 'true' : 'false', title: titolo,
      onclick: () => { S[chiave] = !S[chiave]; disegnaVista(); } }, et);
    const ultimoRep = x.pts.length ? D.report[x.pts[x.pts.length - 1].ri] : null;
    card.append(el('div', { class: 'aq-card-head' },
      el('h2', {}, x.q.nome, el('small', { text: [x.q.sezione, x.q.tipo, `nominale ${num(x.q.nominale)}`].filter(Boolean).join(' · ') })),
      el('div', { class: 'aq-opzioni' },
        el('button', { type: 'button', class: 'aq-toggle', 'aria-pressed': S.scala === 'pct' ? 'true' : 'false', title: 'Mostra quanta tolleranza usa ogni misura: 0 = centro, ±100% = limite',
          onclick: () => { S.scala = S.scala === 'pct' ? 'valore' : 'pct'; disegnaVista(); } }, '% tolleranza'),
        toggle('Media', 'media', 'Linea della media'),
        toggle('±3σ', 'sigma', 'Media ± 3 deviazioni standard'),
        toggle('Colori per OP', 'perOp', 'Colora i punti dei 3 OP più recenti'),
        S.zoom ? el('button', { type: 'button', class: 'aq-toggle', onclick: () => { S.zoom = null; disegnaVista(); } }, 'Reimposta zoom') : null,
        ultimoRep ? el('a', { class: 'aq-link', href: urlReport(ultimoRep[0]) }, 'Ultimo report') : null)));
    const tiles = el('div', { class: 'aq-tiles' });
    const grafici = el('div', { class: 'aq-grafici' });
    const gbox = el('div', {}), hbox = el('div', {});
    grafici.append(gbox, hbox);
    const legenda = el('div', { class: 'aq-legenda' });
    card.append(tiles, grafici, legenda);
    pane.replaceChildren(card);
    const { s, colori, dominio } = graficoQuota(gbox, x);
    if (dominio) istogramma(hbox, x, dominio);
    const st = statoCpk(s.cpk);
    const t = (et, v, sub, cls) => el('div', { class: `aq-tile${cls ? ' ' + cls : ''}` }, el('span', { text: et }), el('b', { text: v }), sub || null);
    tiles.append(
      t('Misure', `${s.n || 0}`, S.zoom ? el('small', { text: 'nello zoom' }) : null),
      t('Fuori', `${s.nFuori || 0}`, el('small', { text: s.n ? pct(s.nFuori / s.n) : '' }), s.nFuori ? 'is-allerta' : ''),
      t('Media', num(s.media), el('small', { text: s.n ? `scarto dal nom. ${segno(s.media - x.q.nominale)}` : '' })),
      t('Dev. std σ', num(s.sd)),
      t('Cp', num(s.cp, 2), el('small', { text: s.cp !== null ? 'larghezza' : (s.n >= 5 && s.ultimo.uni ? 'solo limite superiore' : 'servono 5 misure') })),
      t('Cpk', num(s.cpk, 2), st ? el('span', { class: `aq-stato is-${st.c}`, text: st.t }) : el('small', { text: 'servono 5 misure' })),
      t('Min ÷ max', s.n ? `${num(s.min, 3)} ÷ ${num(s.max, 3)}` : '—'),
      t('Ultima', s.n ? num(s.ultimo.x) : '—', s.n ? el('small', { text: `${D.report[s.ultimo.ri][1]} · tolleranza usata ${s.ultimo.u === null ? '—' : pct(Math.abs(s.ultimo.u))}` }) : null, s.n && s.ultimo.f ? 'is-allerta' : ''),
    );
    legenda.append(el('span', {}, el('i'), 'Rilevato'), el('span', {}, el('i', { class: 'is-punto' }), 'Fuori tolleranza'),
      el('span', {}, el('i', { class: 'is-banda' }), 'Zona di tolleranza'), el('span', {}, el('i', { class: 'is-limite' }), 'Limiti'),
      el('span', {}, el('i', { class: 'is-nominale' }), 'Nominale'));
    if (S.media && S.scala !== 'pct') legenda.append(el('span', {}, el('i', { class: 'is-media' }), 'Media'));
    if (S.sigma && S.scala !== 'pct') legenda.append(el('span', {}, el('i', { class: 'is-sigma' }), '±3σ'));
    if (colori) colori.m.forEach((c, op) => legenda.append(el('span', {}, el('i', { style: `border-top-color:${c};border-top-width:8px;width:8px;border-radius:50%` }), op)));
    legenda.append(el('span', { text: 'Trascina sul grafico per ingrandire.' }));
    // tabella (la stessa informazione senza il grafico)
    const det = el('details', { class: 'aq-tabella' }, el('summary', { text: `Tabella delle ${x.pts.length} misure` }));
    det.addEventListener('toggle', () => {
      if (!det.open || det.querySelector('table')) return;
      const tb = el('tbody');
      x.pts.slice().reverse().forEach(p => {
        const rep = D.report[p.ri];
        tb.append(el('tr', { class: `${p.f ? 'is-fuori' : ''}${rep[0] === S.sn ? ' is-scelto' : ''}`, 'data-r': rep[0], onclick: () => { location.href = urlReport(rep[0]); } },
          el('td', { text: rep[1] }), el('td', { text: rep[2] || '—' }), el('td', { text: dataIt(rep[3]) }),
          el('td', { class: 'n', text: num(p.x) }), el('td', { class: 'n', text: num(p.ts) }), el('td', { class: 'n', text: num(p.ti) }),
          el('td', { class: 'n', text: p.u === null ? '—' : pct(Math.abs(p.u)) }), el('td', { class: 'n f', text: p.f ? segno(p.fd ?? 0) : '—' })));
      });
      det.append(el('table', { class: 'aq-tab' }, el('thead', {}, el('tr', {}, ...['S/N', 'OP', 'Data', 'Rilevato', 'Tol +', 'Tol −', 'Toll. usata', 'Fuori di'].map(h => el('th', { text: h })))), tb));
    });
    card.append(det);
  }

  /* ── mappa: quote × report, colore = tolleranza usata ────────────────── */
  function scalaColori() {
    const mix = (a, b, t) => {
      const h = c => { const m = c.replace('#', ''); return [0, 2, 4].map(i => parseInt(m.slice(i, i + 2), 16)); };
      const A = h(a), Bc = h(b);
      return `rgb(${A.map((v, i) => Math.round(v + (Bc[i] - v) * t)).join(',')})`;
    };
    const mid = css('--aq-mid'), neg = css('--aq-neg'), pos = css('--aq-pos');
    const passi = [0.12, 0.3, 0.5, 0.72, 0.92];
    return { neg: passi.map(t => mix(mid, neg, t)), pos: passi.map(t => mix(mid, pos, t)), crit: css('--aq-crit'), ink: css('--text') || '#111' };
  }
  function vistaMappa(pane) {
    const righe = quoteFiltrate();
    const cols = D.report.map((r, i) => i).filter(i => vis[i]);
    const card = el('div', { class: 'aq-card' });
    const sc = scalaColori();
    card.append(el('div', { class: 'aq-card-head' },
      el('h2', {}, 'Mappa delle quote', el('small', { text: `${righe.length} quote × ${cols.length} report · colore = quanta tolleranza usa la misura, dal centro (grigio) al limite` })),
      el('div', { class: 'aq-scala' }, 'sotto il nominale',
        el('span', { class: 'aq-scala-barra' }, ...sc.neg.slice().reverse().map(c => el('i', { style: `background:${c}` })), ...sc.pos.map(c => el('i', { style: `background:${c}` }))),
        'sopra', el('span', { class: 'is-fuori' }), 'fuori tolleranza')));
    if (!righe.length || !cols.length) { card.append(el('p', { class: 'aq-vuoto', text: 'Nessun dato con questi filtri.' })); pane.replaceChildren(card); return; }
    const wrap = el('div', { class: 'aq-mappa-wrap' });
    card.append(wrap);
    pane.replaceChildren(card);
    const LW = 210, TH = 18;
    const disp = wrap.clientWidth - LW - 4;
    const cw = Math.max(5, Math.min(22, Math.floor(disp / cols.length)));
    const ch = 16;
    const W = LW + cw * cols.length, H = TH + ch * righe.length;
    const dpr = window.devicePixelRatio || 1;
    const cv = el('canvas', { role: 'img', 'aria-label': `Mappa di ${righe.length} quote su ${cols.length} report. I valori sono anche nella vista Quota e nella tabella.` });
    cv.width = W * dpr; cv.height = H * dpr; cv.style.width = `${W}px`; cv.style.height = `${H}px`;
    wrap.append(cv);
    const g = cv.getContext('2d');
    g.scale(dpr, dpr);
    const colIdx = new Map(cols.map((ri, c) => [ri, c]));
    const font = getComputedStyle(root).fontFamily;
    g.font = `600 11px ${font}`;
    g.textBaseline = 'middle';
    const muto = css('--aq-muto'), testo = css('--text') || '#222', grigio = css('--aq-griglia');
    // colonna del S/N evidenziato
    const csel = S.sn ? colIdx.get(D.report.findIndex(r => r[0] === S.sn)) : undefined;
    righe.forEach((x, r) => {
      const y = TH + r * ch;
      g.fillStyle = x.q.id === S.q ? css('--accent') || testo : testo;
      g.fillText(x.q.nome.length > 30 ? x.q.nome.slice(0, 29) + '…' : x.q.nome, 6, y + ch / 2);
      g.fillStyle = grigio; g.fillRect(LW, y + ch - 1, cw * cols.length, 1);
      x.pts.forEach(p => {
        const c = colIdx.get(p.ri); if (c === undefined) return;
        const xx = LW + c * cw;
        if (p.f) {
          g.fillStyle = sc.crit; g.fillRect(xx + 0.5, y + 0.5, cw - 1, ch - 2);
          if (cw >= 9) { g.strokeStyle = sc.ink; g.lineWidth = 1; g.strokeRect(xx + 1.5, y + 1.5, cw - 3, ch - 4); }
        } else if (p.u !== null) {
          const k = Math.min(4, Math.floor(Math.abs(p.u) * 5));
          g.fillStyle = (p.u < 0 ? sc.neg : sc.pos)[k]; g.fillRect(xx + 0.5, y + 0.5, cw - 1, ch - 2);
        }
      });
    });
    if (csel !== undefined) { g.strokeStyle = testo; g.lineWidth = 2; g.strokeRect(LW + csel * cw, TH - 2, cw, H - TH + 1); }
    g.fillStyle = muto;
    g.fillText('Quota', 6, TH / 2);
    const ogni = Math.max(1, Math.ceil(70 / cw));
    cols.forEach((ri, c) => { if (c % ogni === 0) g.fillText(dataIt(D.report[ri][3]).slice(0, 5), LW + c * cw, TH / 2); });
    const cella = ev => {
      const r = cv.getBoundingClientRect();
      const xx = ev.clientX - r.left, yy = ev.clientY - r.top;
      const riga = Math.floor((yy - TH) / ch), col = Math.floor((xx - LW) / cw);
      return { riga: riga >= 0 && riga < righe.length ? riga : -1, col: xx >= LW && col >= 0 && col < cols.length ? col : -1, xx };
    };
    cv.addEventListener('pointermove', ev => {
      const { riga, col } = cella(ev);
      if (riga < 0) { nascondiTooltip(); cv.style.cursor = ''; return; }
      const x = righe[riga];
      cv.style.cursor = 'pointer';
      if (col < 0) { mostraTooltip(ev, [el('b', { text: x.q.nome }), el('div', { class: 't-sub', text: `${x.s.nFuori} fuori su ${x.s.n} · clic per aprirla` })]); return; }
      const ri = cols[col], rep = D.report[ri], p = x.pts.find(pp => pp.ri === ri);
      mostraTooltip(ev, [
        p ? el('b', { text: num(p.x) }) : el('b', { text: 'non misurata' }),
        p && p.f ? el('span', { class: 't-fuori', text: `  fuori di ${segno(p.fd ?? 0)}` }) : null,
        el('div', { text: x.q.nome }),
        el('div', { class: 't-sub', text: `${rep[1]} · ${rep[2] || '—'} · ${dataIt(rep[3])}` }),
        p ? el('div', { class: 't-sub', text: `Tolleranza usata ${p.u === null ? '—' : pct(Math.abs(p.u))} ${p.u > 0 ? 'sopra' : p.u < 0 ? 'sotto' : ''}` }) : null,
      ]);
    });
    cv.addEventListener('pointerleave', nascondiTooltip);
    cv.addEventListener('click', ev => {
      const { riga, col } = cella(ev);
      if (riga < 0) return;
      apriQuota(righe[riga].q.id, col >= 0 ? D.report[cols[col]][0] : null);
    });
  }

  /* ── confronto: più quote sulla stessa scala (% di tolleranza) ───────── */
  function vistaConfronto(pane) {
    const card = el('div', { class: 'aq-card' });
    const scelte = S.cmp.map(id => info.find(x => x.q.id === id)).filter(Boolean);
    const critiche = () => info.filter(x => x.pts.length).sort((a, b) => (b.s.nFuori - a.s.nFuori) || ((a.s.cpk ?? 99) - (b.s.cpk ?? 99))).slice(0, 4);
    card.append(el('div', { class: 'aq-card-head' },
      el('h2', {}, 'Confronto fra quote', el('small', { text: 'Ogni quota in % della sua tolleranza: 0 = centro, ±100% = limite. Spunta fino a 6 quote nell\'elenco.' })),
      el('div', { class: 'aq-opzioni' },
        el('button', { type: 'button', class: 'aq-toggle', onclick: () => { S.cmp = critiche().map(x => x.q.id); disegnaTutto(); } }, 'Le 4 più critiche'),
        S.cmp.length ? el('button', { type: 'button', class: 'aq-toggle', onclick: () => { S.cmp = []; disegnaTutto(); } }, 'Svuota') : null,
        S.zoom ? el('button', { type: 'button', class: 'aq-toggle', onclick: () => { S.zoom = null; disegnaVista(); } }, 'Reimposta zoom') : null)));
    pane.replaceChildren(card);
    if (!scelte.length) { card.append(el('p', { class: 'aq-vuoto', text: 'Nessuna quota scelta: spunta le caselle accanto alle quote, o premi «Le 4 più critiche».' })); return; }
    const ri = D.report.map((r, i) => i).filter(i => vis[i] && nelZoom(i) && scelte.some(x => x.pts.some(p => p.ri === i)));
    const box = el('div', {});
    card.append(box);
    const W = Math.max(420, box.clientWidth || card.clientWidth - 32 || 800), H = 360, L = 52, R = scelte.length <= 4 ? 120 : 18, T = 14, B = 46;
    let lo = -110, hi = 110;
    scelte.forEach(x => x.pts.forEach(p => { if (p.u !== null && nelZoom(p.ri)) { lo = Math.min(lo, p.u * 100); hi = Math.max(hi, p.u * 100); } }));
    lo = Math.max(lo, -250); hi = Math.min(hi, 250);
    const n = ri.length, pos = new Map(ri.map((r, k) => [r, k]));
    const X = k => L + (n > 1 ? k * (W - L - R) / (n - 1) : (W - L - R) / 2);
    const Y = v => T + (hi - Math.max(lo, Math.min(hi, v))) / (hi - lo) * (H - T - B);
    const svg = sv('svg', { class: 'aq-svg', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Confronto di ${scelte.length} quote in percentuale della tolleranza` });
    ticks(lo, hi).forEach(t => {
      svg.append(sv('line', { class: 'g-griglia', x1: L, x2: W - R, y1: Y(t), y2: Y(t) }));
      const tx = sv('text', { x: L - 6, y: Y(t), 'text-anchor': 'end', 'dominant-baseline': 'middle' }); tx.textContent = `${Math.round(t)}%`; svg.append(tx);
    });
    svg.append(sv('rect', { class: 'g-banda', x: L, width: W - L - R, y: Y(100), height: Y(-100) - Y(100) }));
    [100, -100].forEach(v => svg.append(sv('line', { class: 'g-limite', x1: L, x2: W - R, y1: Y(v), y2: Y(v) })));
    svg.append(sv('line', { class: 'g-nominale', x1: L, x2: W - R, y1: Y(0), y2: Y(0) }));
    const serie = scelte.map((x, i) => ({ x, col: `var(--aq-c${i + 1})`, pts: x.pts.filter(p => pos.has(p.ri) && p.u !== null) }));
    serie.forEach(se => {
      if (se.pts.length > 1) svg.append(sv('polyline', { class: 'g-linea', stroke: se.col, points: se.pts.map(p => `${X(pos.get(p.ri))},${Y(p.u * 100)}`).join(' ') }));
      se.pts.forEach(p => { if (p.f || se.pts.length === 1) svg.append(sv('circle', { class: `g-punto${p.f ? ' is-fuori' : ''}`, cx: X(pos.get(p.ri)), cy: Y(p.u * 100), r: 3.5, fill: p.f ? null : se.col })); });
    });
    // etichette dirette in fondo alle linee (fino a 4 quote), spostate perche non si sovrappongano
    if (scelte.length <= 4) {
      const et = serie.filter(se => se.pts.length).map(se => { const ul = se.pts[se.pts.length - 1]; return { se, x: X(pos.get(ul.ri)) + 8, y: Y(ul.u * 100) }; })
        .sort((a, b) => a.y - b.y);
      et.forEach((e, k) => { if (k && e.y - et[k - 1].y < 13) e.y = et[k - 1].y + 13; });
      et.forEach(e => {
        const t = sv('text', { class: 'g-etichetta', x: Math.min(e.x, W - R + 4), y: e.y, 'dominant-baseline': 'middle' });
        t.textContent = e.se.x.q.nome.length > 18 ? e.se.x.q.nome.slice(0, 17) + '…' : e.se.x.q.nome;
        svg.append(t);
      });
    }
    const ogni = Math.max(1, Math.ceil(n / Math.floor((W - L - R) / 70)));
    ri.forEach((r, k) => { if (k % ogni && k !== n - 1) return; const t = sv('text', { x: X(k), y: H - B + 16, 'text-anchor': 'middle' }); t.textContent = n <= 30 ? (D.report[r][1] || '').slice(0, 11) : dataIt(D.report[r][3]).slice(0, 5); svg.append(t); });
    box.append(svg);
    interattivo(svg, { W, H, L, R, T, B, n, X, onHover: (ev, k) => {
      const rep = D.report[ri[k]];
      const righe = [el('div', { text: `${rep[1]} · ${rep[2] || '—'} · ${dataIt(rep[3])}` })];
      serie.forEach(se => {
        const p = se.pts.find(pp => pp.ri === ri[k]);
        righe.push(tRiga(el('i', { style: `color:${se.col}` }), el('b', { text: p ? pct(p.u) : '—' }), el('span', { class: p && p.f ? 't-fuori' : 't-sub', text: se.x.q.nome })));
      });
      mostraTooltip(ev, righe);
    }, onClick: k => { S.sn = D.report[ri[k]][0]; disegnaTutto(); }, onDbl: k => { location.href = urlReport(D.report[ri[k]][0]); },
    onZoom: (k0, k1) => { S.zoom = [ri[k0], ri[k1]]; disegnaVista(); } });
    const leg = el('div', { class: 'aq-legenda' });
    serie.forEach(se => leg.append(el('span', {}, el('i', { style: `border-top-color:${se.col}` }), el('a', { href: '#', text: se.x.q.nome, onclick: e => { e.preventDefault(); apriQuota(se.x.q.id); } }))));
    leg.append(el('span', {}, el('i', { class: 'is-limite' }), 'Limiti ±100%'), el('span', {}, el('i', { class: 'is-punto' }), 'Fuori tolleranza'));
    card.append(leg);
  }

  /* ── pezzo: tutte le quote di un S/N ─────────────────────────────────── */
  function vistaPezzo(pane) {
    const reps = D.report.map((r, i) => i).filter(i => vis[i]).reverse();
    const card = el('div', { class: 'aq-card' });
    pane.replaceChildren(card);
    if (!reps.length) { card.append(el('p', { class: 'aq-vuoto', text: 'Nessun report con questi filtri.' })); return; }
    let i1 = D.report.findIndex(r => r[0] === S.sn);
    if (i1 < 0 || !vis[i1]) i1 = reps[0];
    const i2 = S.pezzo2 !== null ? D.report.findIndex(r => r[0] === S.pezzo2) : -1;
    const sel = (valore, vuoto, cb) => {
      const s = el('select', {}, vuoto ? el('option', { value: '', text: vuoto }) : null,
        ...reps.map(i => el('option', { value: D.report[i][0], selected: D.report[i][0] === valore }, `${D.report[i][1]} · ${D.report[i][2] || '—'} · ${dataIt(D.report[i][3])} · ${D.report[i][5]} fuori`)));
      s.addEventListener('change', () => cb(s.value ? +s.value : null));
      return s;
    };
    const rep = D.report[i1];
    card.append(el('div', { class: 'aq-card-head' },
      el('h2', {}, `Pezzo ${rep[1]}`, el('small', { text: `${rep[2] || '—'} · ${dataIt(rep[3])} · ogni quota in % della sua tolleranza` })),
      el('div', { class: 'aq-opzioni' },
        el('a', { class: 'aq-link', href: urlReport(rep[0]) }, 'Apri il report (PDF, segnalazione anomalia)'))));
    card.append(el('div', { class: 'aq-pezzo-scelta' },
      el('label', { class: 'aq-campo' }, 'S/N', sel(rep[0], null, v => { S.sn = v; disegnaTutto(); })),
      el('label', { class: 'aq-campo' }, 'Confronta con', sel(S.pezzo2, 'nessuno', v => { S.pezzo2 = v; disegnaVista(); }))));
    const righe = quoteFiltrate().map(x => ({ x, p: x.pts.find(p => p.ri === i1), p2: i2 >= 0 ? x.pts.find(p => p.ri === i2) : null })).filter(r => r.p || r.p2);
    if (!righe.length) { card.append(el('p', { class: 'aq-vuoto', text: 'Nessuna quota di questo pezzo con i filtri scelti.' })); return; }
    const box = el('div', {});
    card.append(box);
    const W = Math.max(420, box.clientWidth || 800), rh = 20, T = 22, B = 10, L = 230, R = 70;
    const H = T + B + rh * righe.length;
    const lim = 160;
    const X = v => L + (Math.max(-lim, Math.min(lim, v)) + lim) / (2 * lim) * (W - L - R);
    const svg = sv('svg', { class: 'aq-svg', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': `Quote del pezzo ${rep[1]} in percentuale della tolleranza` });
    svg.append(sv('rect', { class: 'g-banda', x: X(-100), width: X(100) - X(-100), y: T - 4, height: H - T - B + 4 }));
    [-100, 100].forEach(v => svg.append(sv('line', { class: 'g-limite', x1: X(v), x2: X(v), y1: T - 4, y2: H - B })));
    svg.append(sv('line', { class: 'g-nominale', x1: X(0), x2: X(0), y1: T - 4, y2: H - B }));
    [-150, -100, -50, 0, 50, 100, 150].forEach(v => { const t = sv('text', { x: X(v), y: 12, 'text-anchor': 'middle' }); t.textContent = `${v}%`; svg.append(t); });
    righe.forEach((r, k) => {
      const y = T + k * rh;
      const nome = sv('text', { x: L - 8, y: y + rh / 2, 'text-anchor': 'end', 'dominant-baseline': 'middle', class: r.p && r.p.f ? 'g-etichetta' : null });
      nome.textContent = r.x.q.nome.length > 32 ? r.x.q.nome.slice(0, 31) + '…' : r.x.q.nome;
      svg.append(nome);
      if (r.p && r.p.u !== null) {
        const v = r.p.u * 100;
        const x0 = X(0), x1 = X(v);
        svg.append(sv('rect', { class: `g-barra${r.p.f ? ' is-fuori' : ''}`, x: Math.min(x0, x1), y: y + 4, width: Math.max(2, Math.abs(x1 - x0)), height: rh - 8, rx: 3 }));
        if (Math.abs(v) > lim) { const t = sv('text', { class: 'g-etichetta', x: v > 0 ? W - R + 4 : L + 2, y: y + rh / 2, 'dominant-baseline': 'middle' }); t.textContent = `${Math.round(v)}%`; svg.append(t); }
      }
      if (r.p2 && r.p2.u !== null) {
        const cx = X(r.p2.u * 100), cy = y + rh / 2;
        svg.append(sv('path', { d: `M${cx} ${cy - 5}L${cx + 5} ${cy}L${cx} ${cy + 5}L${cx - 5} ${cy}Z`, fill: 'var(--surface)', stroke: 'var(--text)', 'stroke-width': 1.5 }));
      }
      const hit = sv('rect', { x: 0, y, width: W, height: rh, fill: 'transparent', style: 'cursor:pointer' });
      hit.addEventListener('pointermove', ev => mostraTooltip(ev, [
        el('b', { text: r.p ? num(r.p.x) : 'non misurata' }), r.p && r.p.f ? el('span', { class: 't-fuori', text: `  fuori di ${segno(r.p.fd ?? 0)}` }) : null,
        el('div', { text: r.x.q.nome }),
        el('div', { class: 't-sub', text: r.p ? `Limiti ${num(r.p.lsl)} ÷ ${num(r.p.usl)} · tolleranza usata ${pct(Math.abs(r.p.u ?? 0))}` : '' }),
        r.p2 ? el('div', { class: 't-sub', text: `${D.report[i2][1]}: ${num(r.p2.x)}${r.p2.f ? ' (fuori)' : ''}` }) : null,
        el('div', { class: 't-sub', text: 'Clic: andamento di questa quota' }),
      ]));
      hit.addEventListener('pointerleave', nascondiTooltip);
      hit.addEventListener('click', () => apriQuota(r.x.q.id, rep[0]));
      svg.append(hit);
    });
    box.append(svg);
    const leg = el('div', { class: 'aq-legenda' }, el('span', {}, el('i', { class: 'is-banda' }), 'Zona di tolleranza'),
      el('span', {}, el('i', { class: 'is-punto' }), 'Fuori tolleranza'));
    if (i2 >= 0) leg.append(el('span', { text: `◇ ${D.report[i2][1]}` }));
    card.append(leg);
  }

  /* ── CSV (filtri applicati) ──────────────────────────────────────────── */
  $('[data-azione="csv"]').addEventListener('click', () => {
    const quote = S.tab === 'quota' ? info.filter(x => x.q.id === S.q) : quoteFiltrate();
    const righe = [['S/N', 'OP', 'Data', 'Quota', 'Gruppo', 'Nominale', 'Tol +', 'Tol -', 'Rilevato', 'Fuori', 'Fuori di', 'Tolleranza usata %']];
    quote.forEach(x => x.pts.forEach(p => {
      const r = D.report[p.ri];
      righe.push([r[1], r[2], dataIt(r[3]), x.q.nome, x.q.sezione, num(x.q.nominale), num(p.ts), num(p.ti), num(p.x), p.f ? 'sì' : 'no', p.f ? num(p.fd ?? 0) : '', p.u === null ? '' : Math.round(p.u * 100)]);
    }));
    const testo = righe.map(r => r.map(c => `"${String(c ?? '').replace(/"/g, '""')}"`).join(';')).join('\r\n');
    const a = el('a', { href: URL.createObjectURL(new Blob(['﻿' + testo], { type: 'text/csv;charset=utf-8' })), download: `quote_${root.dataset.pn}_${S.prog}.csv` });
    document.body.append(a); a.click(); a.remove();
  });

  /* ── disegno ─────────────────────────────────────────────────────────── */
  function disegnaVista() {
    $$('[data-tab]').forEach(b => { b.classList.toggle('is-on', b.dataset.tab === S.tab); b.setAttribute('aria-selected', b.dataset.tab === S.tab ? 'true' : 'false'); });
    $$('[data-pane]').forEach(p => { p.hidden = p.dataset.pane !== S.tab; });
    $('[data-corpo]').classList.toggle('is-largo', S.tab === 'mappa');
    $('[data-conta-cmp]').textContent = S.cmp.length || '';
    nascondiTooltip();
    const pane = $(`[data-pane="${S.tab}"]`);
    ({ quota: vistaQuota, mappa: vistaMappa, confronto: vistaConfronto, pezzo: vistaPezzo })[S.tab](pane);
    salvaUrl();
  }
  function disegnaTutto() {
    if (!D) return;
    disegnaFiltri();
    disegnaKpi();
    if (S.tab === 'quota' && !info.some(x => x.q.id === S.q && x.pts.length)) { const f = quoteFiltrate()[0]; S.q = f ? f.q.id : ''; }
    disegnaLista();
    disegnaVista();
  }
  let attesa = null;
  let larghezza = 0;
  new ResizeObserver(voci => {
    const w = Math.round(voci[0].contentRect.width);
    if (w === larghezza) return;   // solo la larghezza: l'altezza cambia a ogni disegno
    larghezza = w;
    clearTimeout(attesa); attesa = setTimeout(() => { if (D) disegnaVista(); }, 150);
  }).observe($('.aq-main'));

  carica();
})();
