/* NOVICROM HUB — da assets/pages/plant_layout_editor.html (blocco 1), spostato dall'inline il 12/11/2026: stesso punto, ora in cache. */
(function () {
  "use strict";
  var dataNode = document.getElementById("plant-layout-editor-data");
  if (!dataNode) return;
  var payload = JSON.parse(dataNode.textContent || "{}");
  var form = document.getElementById("plant-layout-form");
  var view = document.getElementById("plx-view");
  var stage = document.getElementById("plx-stage");
  var overlay = document.getElementById("plx-overlay");
  var image = document.getElementById("plx-image");
  var statusBox = document.getElementById("plx-status");
  var statusText = document.getElementById("plx-status-text");
  var statusActions = document.getElementById("plx-status-actions");
  var dirtyNode = document.getElementById("plx-dirty");
  var selectionNode = document.getElementById("plx-selection");
  var machineList = document.getElementById("plx-machine-list");
  var areaList = document.getElementById("plx-area-list");
  var searchNode = document.getElementById("plx-machine-search");
  var areasInput = document.getElementById("id_areas_payload");
  var markersInput = document.getElementById("id_markers_payload");
  var toolInput = document.getElementById("plx-image-tool");
  var hasImage = !!(stage && image);

  /* ---------- utilità ---------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null && text !== "") n.textContent = text;
    return n;
  }
  function num(v, f) { var n = Number(v); return Number.isFinite(n) ? n : f; }
  function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
  function r2(v) { return Math.round(v * 100) / 100; }
  function rgba(hex, a) {
    var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || "");
    if (!m) return "rgba(37,99,235," + a + ")";
    return "rgba(" + parseInt(m[1], 16) + "," + parseInt(m[2], 16) + "," + parseInt(m[3], 16) + "," + a + ")";
  }
  function norm(s) { return String(s || "").trim().toLowerCase(); }
  var seq = 0;
  function cid(prefix, row) { seq += 1; return row && row.id ? prefix + row.id : prefix + "new-" + seq; }

  /* ---------- stato ---------- */
  var machines = Array.isArray(payload.machines) ? payload.machines : [];
  var machineById = {};
  machines.forEach(function (m) { machineById[m.id] = m; });
  var state = {
    mode: "select",
    filter: "todo",
    selected: null,          // {kind:"marker"|"area", id}
    placing: null,           // asset id in collocazione
    crop: null,              // {x,y,w,h}
    dirty: false,
    areas: (payload.areas || []).map(function (r, i) {
      return { cid: cid("a", r), id: r.id || null, name: r.name || ("Reparto " + (i + 1)), reparto_code: r.reparto_code || "",
        color: r.color || "#2563EB", notes: r.notes || "", x: num(r.x_percent, 0), y: num(r.y_percent, 0),
        w: num(r.width_percent, 10), h: num(r.height_percent, 10), sort_order: num(r.sort_order, (i + 1) * 10),
        pts: Array.isArray(r.punti) && r.punti.length >= 3 ? r.punti.map(function (q) { return [num(q[0], 0), num(q[1], 0)]; }) : null };
    }),
    poly: [],                // vertici del reparto a punti in disegno
    selVertex: null,         // vertice selezionato del reparto a forma libera
    markers: (payload.markers || []).map(function (r, i) {
      return { cid: cid("m", r), id: r.id || null, asset_id: num(r.asset_id, 0), label: r.label || "",
        x: num(r.x_percent, 50), y: num(r.y_percent, 50), unplaced: !!r.unplaced, sort_order: num(r.sort_order, (i + 1) * 10) };
    })
  };
  function markerFor(assetId) { return state.markers.find(function (m) { return Number(m.asset_id) === Number(assetId); }) || null; }
  var SVGNS = "http://www.w3.org/2000/svg";
  function byCid(list, id) { return list.find(function (r) { return r.cid === id; }) || null; }
  function selectedObj() {
    if (!state.selected) return null;
    return byCid(state.selected.kind === "area" ? state.areas : state.markers, state.selected.id);
  }
  function markerTitle(m) {
    var machine = machineById[m.asset_id];
    return m.label || (machine && (machine.asset_tag || machine.name)) || "Macchina";
  }
  /* forma libera: vertici in % della pianta, il riquadro x/y/w/h li contiene */
  function inPoly(pts, x, y) {
    var inside = false;
    for (var i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      var xi = pts[i][0], yi = pts[i][1], xj = pts[j][0], yj = pts[j][1];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function areaContains(a, x, y) {
    if (a.pts) return inPoly(a.pts, x, y);
    return x >= a.x && x <= a.x + a.w && y >= a.y && y <= a.y + a.h;
  }
  function areaSurface(a) {
    if (!a.pts) return a.w * a.h;
    var s2 = 0;
    for (var i = 0, j = a.pts.length - 1; i < a.pts.length; j = i++) s2 += a.pts[j][0] * a.pts[i][1] - a.pts[i][0] * a.pts[j][1];
    return Math.abs(s2) / 2;
  }
  function bboxFromPts(a) {
    var xs = a.pts.map(function (q) { return q[0]; }), ys = a.pts.map(function (q) { return q[1]; });
    a.x = r2(Math.min.apply(null, xs)); a.y = r2(Math.min.apply(null, ys));
    a.w = r2(Math.max(.5, Math.max.apply(null, xs) - a.x)); a.h = r2(Math.max(.5, Math.max.apply(null, ys) - a.y));
  }
  function relPoint(a, q) { return [(q[0] - a.x) / a.w * 100, (q[1] - a.y) / a.h * 100]; }
  function interiorPoint(a) {
    var cx = 0, cy = 0;
    a.pts.forEach(function (q) { cx += q[0]; cy += q[1]; });
    cx /= a.pts.length; cy /= a.pts.length;
    if (inPoly(a.pts, cx, cy)) return [cx, cy];
    for (var i = 1; i < 20; i++) for (var j = 1; j < 20; j++) {
      var px = a.x + a.w * i / 20, py = a.y + a.h * j / 20;
      if (inPoly(a.pts, px, py)) return [px, py];
    }
    return a.pts[0];
  }
  function areaAt(x, y) {
    var hits = state.areas.filter(function (a) { return areaContains(a, x, y); });
    hits.sort(function (a, b) { return areaSurface(a) - areaSurface(b); });
    return hits[0] || null;
  }

  function sync() {
    areasInput.value = JSON.stringify(state.areas.map(function (a, i) {
      return { id: a.id, name: a.name, reparto_code: a.reparto_code, color: a.color, notes: a.notes,
        x_percent: r2(a.x), y_percent: r2(a.y), width_percent: r2(a.w), height_percent: r2(a.h), sort_order: a.sort_order || (i + 1) * 10,
        punti: a.pts ? a.pts.map(function (q) { return [r2(q[0]), r2(q[1])]; }) : [] };
    }));
    markersInput.value = JSON.stringify(state.markers.map(function (m, i) {
      return { id: m.id, asset_id: m.asset_id, label: m.label, x_percent: r2(m.unplaced ? 50 : m.x), y_percent: r2(m.unplaced ? 50 : m.y),
        sort_order: m.sort_order || (i + 1) * 10 };
    }));
  }
  function touch() {
    state.dirty = true;
    dirtyNode.textContent = "Modifiche non salvate.";
    dirtyNode.classList.add("is-dirty");
    sync();
  }

  /* ---------- zoom e trascinamento ---------- */
  var base = { w: 0, h: 0 }, z = 1, tx = 0, ty = 0, MAXZ = 12;
  function layoutBase() {
    if (!hasImage || !image.naturalWidth) return;
    var vw = view.clientWidth, vh = view.clientHeight, ar = image.naturalWidth / image.naturalHeight;
    base.w = Math.min(vw, vh * ar); base.h = base.w / ar;
    stage.style.width = base.w + "px"; stage.style.height = base.h + "px";
  }
  function apply() {
    if (!hasImage) return;
    var vw = view.clientWidth, vh = view.clientHeight, sw = base.w * z, sh = base.h * z;
    tx = sw <= vw ? (vw - sw) / 2 : clamp(tx, vw - sw, 0);
    ty = sh <= vh ? (vh - sh) / 2 : clamp(ty, vh - sh, 0);
    stage.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + z + ")";
    stage.style.setProperty("--z", z);
  }
  function zoomAt(f, cx, cy) {
    var nz = clamp(z * f, 1, MAXZ);
    tx = cx - (cx - tx) * (nz / z); ty = cy - (cy - ty) * (nz / z); z = nz; apply();
  }
  function fit() { z = 1; tx = 0; ty = 0; apply(); }
  function centerOn(x, y, minZ) {
    if (!hasImage) return;
    if (z < minZ) z = minZ;
    tx = view.clientWidth / 2 - x / 100 * base.w * z;
    ty = view.clientHeight / 2 - y / 100 * base.h * z;
    apply();
  }
  function toPct(e) {
    var r = overlay.getBoundingClientRect();
    return { x: r2(clamp((e.clientX - r.left) / r.width * 100, 0, 100)), y: r2(clamp((e.clientY - r.top) / r.height * 100, 0, 100)) };
  }

  /* ---------- modalità ---------- */
  function setStatus(text, actions, busy) {
    statusText.textContent = text;
    statusActions.innerHTML = "";
    (actions || []).forEach(function (a) {
      var b = el("button", "plx-tool", a.label); b.type = "button";
      if (a.primary) b.setAttribute("aria-pressed", "true");
      b.addEventListener("click", a.run); statusActions.appendChild(b);
    });
    statusBox.classList.toggle("is-busy", !!busy);
  }
  function setMode(mode, opts) {
    state.mode = mode;
    state.placing = mode === "place" ? opts.assetId : null;
    if (mode !== "crop") state.crop = null;
    document.querySelectorAll("[data-mode]").forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-mode") === mode)); });
    view.classList.toggle("is-draw", mode === "draw");
    view.classList.toggle("is-poly", mode === "poly");
    if (mode !== "poly") state.poly = [];
    view.classList.toggle("is-place", mode === "place");
    view.classList.toggle("is-crop", mode === "crop");
    if (mode === "draw") setStatus("Trascina sulla pianta il rettangolo del reparto.", [{ label: "Annulla", run: function () { setMode("select"); } }], true);
    else if (mode === "poly") polyStatus();
    else if (mode === "place") {
      var m = machineById[state.placing];
      var also = m && (m.elsewhere || []).length ? " È già su " + m.elsewhere.join(", ") + ": comparirà anche su questa pianta." : "";
      setStatus("Clicca sulla pianta dove si trova " + (m ? (m.asset_tag || m.name) : "la macchina") + "." + also, [{ label: "Annulla", run: function () { setMode("select"); } }], true);
    } else if (mode === "crop") {
      setStatus("Trascina il riquadro da tenere: il resto della pianta verrà tagliato.", cropActions(), true);
    } else setStatus("Seleziona una macchina nell'elenco per collocarla, oppure trascina quelle già sulla pianta.", [], false);
    renderOverlay(); renderMachines();
  }
  function polyStatus() {
    var n = state.poly.length;
    var acts = [{ label: "Annulla", run: function () { setMode("select"); } }];
    if (n) acts.unshift({ label: "Togli ultimo punto", run: function () { state.poly.pop(); renderOverlay(); polyStatus(); } });
    if (n >= 3) acts.unshift({ label: "Chiudi reparto", primary: true, run: closePoly });
    setStatus(n ? (n + " punti. Continua a cliccare i vertici; per chiudere clicca il primo punto (verde), premi Invio o «Chiudi reparto».")
      : "Clicca sulla pianta i vertici del reparto, uno dopo l'altro (per una «L» bastano 6 punti).", acts, true);
  }
  function closePoly() {
    if (state.poly.length < 3) return;
    var a = { cid: cid("a", null), id: null, name: "Nuovo reparto", reparto_code: "", color: "#2563EB", notes: "",
      x: 0, y: 0, w: 1, h: 1, pts: state.poly.map(function (q) { return [r2(q[0]), r2(q[1])]; }), sort_order: (state.areas.length + 1) * 10 };
    bboxFromPts(a);
    state.areas.push(a); touch();
    state.selected = { kind: "area", id: a.cid }; state.selVertex = null;
    setMode("select"); renderAll();
    var first = selectionNode.querySelector("input"); if (first) { first.focus(); first.select(); }
  }
  function cropActions() {
    var acts = [{ label: "Annulla", run: function () { setMode("select"); } }];
    if (state.crop) acts.unshift({ label: "Applica ritaglio", primary: true, run: applyCrop });
    return acts;
  }

  /* ---------- disegno ---------- */
  function renderOverlay() {
    if (!hasImage) return;
    overlay.innerHTML = "";
    var sel = state.selected;
    state.areas.forEach(function (a) {
      var isSel = sel && sel.kind === "area" && sel.id === a.cid;
      var b = el("button", "plx-area" + (isSel ? " is-selected" : "") + (a.pts ? " is-poly" : ""));
      b.type = "button";
      b.style.cssText = "left:" + a.x + "%;top:" + a.y + "%;width:" + a.w + "%;height:" + a.h + "%;--area-color:" + a.color +
        ";--area-bg:" + rgba(a.color, .16) + ";--area-bg-active:" + rgba(a.color, .3);
      b.setAttribute("aria-label", "Reparto " + a.name);
      b.dataset.area = a.cid;
      var label = el("span", "plx-area-label", a.name || "Reparto");
      if (a.pts) {
        var rel = a.pts.map(function (q) { return relPoint(a, q); });
        b.style.clipPath = "polygon(" + rel.map(function (q) { return q[0].toFixed(2) + "% " + q[1].toFixed(2) + "%"; }).join(", ") + ")";
        var svg = document.createElementNS(SVGNS, "svg");
        svg.setAttribute("class", "plx-area-shape"); svg.setAttribute("viewBox", "0 0 100 100"); svg.setAttribute("preserveAspectRatio", "none");
        var pg = document.createElementNS(SVGNS, "polygon");
        pg.setAttribute("points", rel.map(function (q) { return q[0].toFixed(2) + "," + q[1].toFixed(2); }).join(" "));
        svg.appendChild(pg); b.appendChild(svg);
        var ip = interiorPoint(a);
        label.className = "plx-area-label is-free";
        label.style.left = ip[0] + "%"; label.style.top = ip[1] + "%";
      } else {
        b.appendChild(label);
      }
      if (isSel && !a.pts) {
        var h = el("span", "plx-handle"); h.dataset.handle = a.cid; b.appendChild(h);
      }
      overlay.appendChild(b);
      if (a.pts) overlay.appendChild(label);
      if (isSel && a.pts) {
        // maniglie fuori dal pulsante (che è ritagliato): vertici trascinabili e «+» a metà lato per aggiungerne
        a.pts.forEach(function (q, i) {
          var nx = a.pts[(i + 1) % a.pts.length];
          var mid = el("button", "plx-mid"); mid.type = "button";
          mid.style.left = (q[0] + nx[0]) / 2 + "%"; mid.style.top = (q[1] + nx[1]) / 2 + "%";
          mid.dataset.mid = a.cid + "|" + i; mid.title = "Trascina per aggiungere un punto";
          mid.setAttribute("aria-label", "Aggiungi un punto");
          overlay.appendChild(mid);
        });
        a.pts.forEach(function (q, i) {
          var v = el("button", "plx-vertex" + (state.selVertex === i ? " is-selected" : "")); v.type = "button";
          v.style.left = q[0] + "%"; v.style.top = q[1] + "%"; v.style.setProperty("--area-color", a.color);
          v.dataset.vertex = a.cid + "|" + i; v.title = "Trascina per spostare; selezionato, Canc lo toglie";
          v.setAttribute("aria-label", "Punto " + (i + 1));
          overlay.appendChild(v);
        });
      }
    });
    if (state.mode === "poly" && state.poly.length) {
      var dsvg = document.createElementNS(SVGNS, "svg");
      dsvg.setAttribute("class", "plx-poly-draft"); dsvg.setAttribute("viewBox", "0 0 100 100"); dsvg.setAttribute("preserveAspectRatio", "none");
      var pl = document.createElementNS(SVGNS, "polyline");
      pl.setAttribute("points", state.poly.map(function (q) { return q[0] + "," + q[1]; }).join(" "));
      dsvg.appendChild(pl); overlay.appendChild(dsvg);
      state.poly.forEach(function (q, i) {
        var v = el("span", "plx-vertex" + (i === 0 && state.poly.length >= 3 ? " is-first" : ""));
        v.style.left = q[0] + "%"; v.style.top = q[1] + "%";
        if (i === 0) v.dataset.polyFirst = "1";
        overlay.appendChild(v);
      });
    }
    state.markers.forEach(function (m) {
      if (m.unplaced) return;
      var p = el("button", "plx-pin" + (sel && sel.kind === "marker" && sel.id === m.cid ? " is-selected" : "") +
        (state.placing && Number(state.placing) !== Number(m.asset_id) ? " is-dim" : ""));
      p.type = "button";
      p.style.left = m.x + "%"; p.style.top = m.y + "%";
      p.dataset.marker = m.cid;
      p.setAttribute("aria-label", markerTitle(m));
      p.appendChild(el("span", "plx-pin-label", markerTitle(m)));
      overlay.appendChild(p);
    });
    if (state.mode === "crop" && state.crop) {
      var c = el("div", "plx-crop");
      c.style.cssText = "left:" + state.crop.x + "%;top:" + state.crop.y + "%;width:" + state.crop.w + "%;height:" + state.crop.h + "%";
      overlay.appendChild(c);
    }
    ghost = el("div", "plx-ghost"); overlay.appendChild(ghost);
  }
  var ghost = null;

  function machineMatches(m, q) {
    if (!q) return true;
    return norm([m.asset_tag, m.internal_number, m.name, m.reparto, m.model, m.manufacturer].join(" ")).indexOf(q) !== -1;
  }
  function renderMachines() {
    var q = norm(searchNode.value), counts = { todo: 0, on: 0, away: 0, all: machines.length };
    machineList.innerHTML = "";
    var rows = [];
    machines.forEach(function (m) {
      var mk = markerFor(m.id), on = !!(mk && !mk.unplaced), away = !on && (m.elsewhere || []).length > 0;
      if (on) counts.on += 1; else if (away) counts.away += 1; else counts.todo += 1;
      if (state.filter === "on" && !on) return;
      if (state.filter === "away" && !away) return;
      if (state.filter === "todo" && (on || away)) return;
      if (!machineMatches(m, q)) return;
      rows.push({ m: m, mk: mk, on: on, away: away });
    });
    renderCleanup();
    ["todo", "on", "away", "all"].forEach(function (k) { document.getElementById("plx-count-" + k).textContent = counts[k]; });
    rows.slice(0, 300).forEach(function (row) {
      var li = el("li"), b = el("button"); b.type = "button";
      var isSel = (state.placing && Number(state.placing) === Number(row.m.id)) ||
        (row.mk && state.selected && state.selected.kind === "marker" && state.selected.id === row.mk.cid);
      if (isSel) b.className = "is-selected";
      var name = el("span", "plx-list-name", row.m.asset_tag || row.m.name);
      name.appendChild(el("small", "", [row.m.name, row.m.internal_number ? "n. " + row.m.internal_number : "", row.m.reparto || "senza reparto"].filter(Boolean).join(" · ")));
      b.appendChild(name);
      var tag = row.on ? ["is-on", "sulla pianta"] : row.away ? ["is-away", "su " + row.m.elsewhere.join(", ")] : row.mk ? ["is-todo", "da collocare"] : ["is-off", "non presente"];
      var tagNode = el("span", "plx-tag " + tag[0], tag[1]);
      if (row.away) tagNode.title = "Già posizionata su: " + row.m.elsewhere.join(", ");
      b.appendChild(tagNode);
      b.addEventListener("click", function () { pickMachine(row.m.id); });
      li.appendChild(b); machineList.appendChild(li);
    });
    if (!rows.length) machineList.appendChild(el("li", "plx-empty-note", state.filter === "todo" && !q ? "Nessuna macchina da posizionare: sono tutte su una pianta." : "Nessuna macchina trovata."));
    else if (rows.length > 300) machineList.appendChild(el("li", "plx-empty-note", "Altre " + (rows.length - 300) + ": affina la ricerca."));
  }
  /* Segnaposti mai collocati (50/50, creati in automatico): si tolgono in
     blocco; restano nell'elenco e si possono collocare quando serve. */
  var cleanupBox = document.getElementById("plx-cleanup");
  function renderCleanup() {
    if (!cleanupBox) return;
    var todo = state.markers.filter(function (m) { return m.unplaced; });
    cleanupBox.hidden = !todo.length;
    var away = todo.filter(function (m) { var mm = machineById[m.asset_id]; return mm && (mm.elsewhere || []).length; }).length;
    document.getElementById("plx-cleanup-text").textContent = todo.length + (todo.length === 1 ? " segnaposto mai collocato" : " segnaposti mai collocati") +
      " su questa pianta" + (away ? " (" + away + " di macchine già su altre piante)" : "") + ".";
  }
  if (cleanupBox) document.getElementById("plx-cleanup-run").addEventListener("click", function () {
    var before = state.markers.length;
    state.markers = state.markers.filter(function (m) { return !m.unplaced; });
    if (state.selected && state.selected.kind === "marker" && !byCid(state.markers, state.selected.id)) state.selected = null;
    touch(); renderAll();
    setStatus("Tolti " + (before - state.markers.length) + " segnaposti: premi «Salva» per confermare.", [], false);
  });
  /* ---------- reparti proposti dalle macchine collocate ---------- */
  var PALETTE = ["#2563EB", "#16A34A", "#D97706", "#9333EA", "#DC2626", "#0891B2", "#65A30D", "#DB2777", "#4F46E5", "#0D9488"];
  function suggestedAreas() {
    var have = {};
    state.areas.forEach(function (a) { if (a.reparto_code) have[norm(a.reparto_code)] = true; });
    var groups = {};
    state.markers.forEach(function (m) {
      if (m.unplaced) return;
      var mm = machineById[m.asset_id], rep = mm && String(mm.reparto || "").trim();
      if (!rep || have[norm(rep)] || mm.status_code === "RETIRED") return;
      (groups[rep] = groups[rep] || []).push(m);
    });
    var PAD = 2.5, MIN = 6;
    return Object.keys(groups).sort().map(function (rep, i) {
      var pts = groups[rep];
      var x0 = Math.min.apply(null, pts.map(function (p) { return p.x; })) - PAD;
      var y0 = Math.min.apply(null, pts.map(function (p) { return p.y; })) - PAD;
      var x1 = Math.max.apply(null, pts.map(function (p) { return p.x; })) + PAD;
      var y1 = Math.max.apply(null, pts.map(function (p) { return p.y; })) + PAD;
      if (x1 - x0 < MIN) { var cx = (x0 + x1) / 2; x0 = cx - MIN / 2; x1 = cx + MIN / 2; }
      if (y1 - y0 < MIN) { var cy = (y0 + y1) / 2; y0 = cy - MIN / 2; y1 = cy + MIN / 2; }
      x0 = clamp(x0, 0, 100); y0 = clamp(y0, 0, 100);
      return { rep: rep, n: pts.length, x: r2(x0), y: r2(y0), w: r2(clamp(x1, 0, 100) - x0), h: r2(clamp(y1, 0, 100) - y0),
        color: PALETTE[(state.areas.length + i) % PALETTE.length] };
    });
  }
  var suggestBox = document.getElementById("plx-suggest");
  function renderSuggest() {
    if (!suggestBox) return;
    var rows = suggestedAreas();
    suggestBox.hidden = !rows.length;
    if (!rows.length) return;
    document.getElementById("plx-suggest-text").textContent = rows.length === 1
      ? "1 reparto con macchine collocate non ha ancora il suo riquadro."
      : rows.length + " reparti con macchine collocate non hanno ancora il loro riquadro.";
  }
  if (suggestBox) document.getElementById("plx-suggest-run").addEventListener("click", function () {
    var rows = suggestedAreas();
    rows.forEach(function (r) {
      state.areas.push({ cid: cid("a", null), id: null, name: r.rep, reparto_code: r.rep, color: r.color, notes: "",
        x: r.x, y: r.y, w: r.w, h: r.h, sort_order: (state.areas.length + 1) * 10 });
    });
    touch(); renderAll();
    setStatus("Aggiunti " + rows.length + " reparti attorno alle loro macchine: controlla i riquadri (si spostano e ridimensionano) e premi «Salva».", [], false);
  });

  function renderAreas() {
    renderSuggest();
    areaList.innerHTML = "";
    if (!state.areas.length) { areaList.appendChild(el("li", "plx-empty-note", "Nessun reparto disegnato.")); return; }
    state.areas.forEach(function (a) {
      var li = el("li"), b = el("button"); b.type = "button";
      if (state.selected && state.selected.kind === "area" && state.selected.id === a.cid) b.className = "is-selected";
      var name = el("span", "plx-list-name");
      var sw = el("span", "plx-swatch"); sw.style.background = a.color; name.appendChild(sw);
      name.appendChild(document.createTextNode(a.name || "Reparto"));
      var n = machines.filter(function (m) { return a.reparto_code && norm(m.reparto) === norm(a.reparto_code); }).length;
      name.appendChild(el("small", "", (a.reparto_code ? "codice " + a.reparto_code + " · " + n + " macchin" + (n === 1 ? "a" : "e") : "nessun codice reparto")));
      b.appendChild(name);
      b.addEventListener("click", function () { select("area", a.cid, true); });
      li.appendChild(b); areaList.appendChild(li);
    });
  }
  function field(label, input) { var f = el("div", "field"), l = el("label", "", label); f.appendChild(l); f.appendChild(input); return f; }
  function input(type, value, onInput, attrs) {
    var i = el("input", "input"); i.type = type; i.value = value;
    Object.keys(attrs || {}).forEach(function (k) { i.setAttribute(k, attrs[k]); });
    i.addEventListener("input", function () { onInput(i.value); });
    return i;
  }
  function renderSelection() {
    selectionNode.innerHTML = "";
    var obj = selectedObj();
    if (!obj) {
      selectionNode.appendChild(el("p", "plx-empty-note", hasImage ? "Clicca una macchina o un reparto sulla pianta, o scegli dall'elenco." : "Carica prima l'immagine della planimetria."));
      return;
    }
    var wrap = el("div", "plx-fields");
    if (state.selected.kind === "marker") {
      var machine = machineById[obj.asset_id] || {};
      wrap.appendChild(el("p", "plx-sel-title", markerTitle(obj)));
      var a = obj.unplaced ? null : areaAt(obj.x, obj.y);
      wrap.appendChild(el("p", "plx-sel-sub", [machine.name, machine.reparto ? "reparto " + machine.reparto : "", obj.unplaced ? "da collocare" : (a ? "nel reparto disegnato «" + a.name + "»" : "fuori dai reparti disegnati")].filter(Boolean).join(" · ")));
      if (a && machine.reparto && a.reparto_code && norm(a.reparto_code) !== norm(machine.reparto)) {
        wrap.appendChild(el("p", "plx-errors", "Attenzione: la macchina è del reparto " + machine.reparto + " ma si trova nel riquadro " + a.name + " (" + a.reparto_code + ")."));
      }
      wrap.appendChild(field("Etichetta sulla pianta", input("text", obj.label, function (v) { obj.label = v.slice(0, 120); touch(); renderOverlay(); }, { maxlength: "120", placeholder: machine.asset_tag || "" })));
      var acts = el("div", "plx-actions");
      var place = el("button", "plx-tool", obj.unplaced ? "Colloca sulla pianta" : "Ricolloca"); place.type = "button";
      place.addEventListener("click", function () { setMode("place", { assetId: obj.asset_id }); });
      var rm = el("button", "plx-tool", "Togli dalla pianta"); rm.type = "button";
      rm.addEventListener("click", removeSelected);
      acts.appendChild(place); acts.appendChild(rm);
      if (machine.detail_url) { var open = el("a", "plx-tool", "Scheda"); open.href = machine.detail_url; acts.appendChild(open); }
      wrap.appendChild(acts);
    } else {
      wrap.appendChild(el("p", "plx-sel-title", "Reparto"));
      var two = el("div", "plx-two");
      two.appendChild(field("Nome", input("text", obj.name, function (v) { obj.name = v.slice(0, 120); touch(); renderOverlay(); renderAreas(); }, { maxlength: "120" })));
      two.appendChild(field("Codice reparto", input("text", obj.reparto_code, function (v) { obj.reparto_code = v.slice(0, 120); touch(); renderAreas(); }, { maxlength: "120", placeholder: "es. CN5" })));
      wrap.appendChild(two);
      wrap.appendChild(field("Colore", input("color", obj.color, function (v) { obj.color = v.toUpperCase(); touch(); renderOverlay(); renderAreas(); })));
      wrap.appendChild(field("Note", input("text", obj.notes, function (v) { obj.notes = v.slice(0, 255); touch(); }, { maxlength: "255" })));
      var acts2 = el("div", "plx-actions");
      if (obj.pts) {
        wrap.appendChild(el("p", "plx-sel-sub", "Forma libera, " + obj.pts.length + " punti. Trascina i punti bianchi per spostarli, il quadratino a metà lato per aggiungerne uno; un punto selezionato si toglie con Canc."));
        var toRect = el("button", "plx-tool", "Torna rettangolo"); toRect.type = "button";
        toRect.addEventListener("click", function () { obj.pts = null; state.selVertex = null; fixArea(obj); touch(); renderAll(); });
        acts2.appendChild(toRect);
        if (state.selVertex !== null && obj.pts.length > 3) {
          var rmV = el("button", "plx-tool", "Togli il punto selezionato"); rmV.type = "button";
          rmV.addEventListener("click", removeSelectedVertex);
          acts2.appendChild(rmV);
        }
      } else {
        var four = el("div", "plx-four");
        [["x", "X %"], ["y", "Y %"], ["w", "Largh. %"], ["h", "Alt. %"]].forEach(function (k) {
          four.appendChild(field(k[1], input("number", r2(obj[k[0]]), function (v) { obj[k[0]] = num(v, obj[k[0]]); fixArea(obj); touch(); renderOverlay(); }, { step: "0.1", min: "0", max: "100" })));
        });
        wrap.appendChild(four);
        var toPoly = el("button", "plx-tool", "Forma libera"); toPoly.type = "button";
        toPoly.title = "Trasforma il rettangolo in punti modificabili (es. per fare una «L»)";
        toPoly.addEventListener("click", function () {
          obj.pts = [[obj.x, obj.y], [obj.x + obj.w, obj.y], [obj.x + obj.w, obj.y + obj.h], [obj.x, obj.y + obj.h]];
          bboxFromPts(obj); touch(); renderAll();
        });
        acts2.appendChild(toPoly);
      }
      var del = el("button", "plx-tool", "Elimina reparto"); del.type = "button"; del.addEventListener("click", removeSelected);
      acts2.appendChild(del); wrap.appendChild(acts2);
    }
    selectionNode.appendChild(wrap);
  }
  function fixArea(a) {
    if (a.pts) {
      a.pts = a.pts.map(function (q) { return [clamp(r2(q[0]), 0, 100), clamp(r2(q[1]), 0, 100)]; });
      bboxFromPts(a); return;
    }
    a.x = clamp(r2(a.x), 0, 99.5); a.y = clamp(r2(a.y), 0, 99.5);
    a.w = clamp(r2(a.w), .5, 100 - a.x); a.h = clamp(r2(a.h), .5, 100 - a.y);
  }
  function renderAll() { renderOverlay(); renderMachines(); renderAreas(); renderSelection(); }

  /* ---------- azioni ---------- */
  function select(kind, id, center) {
    if (!state.selected || state.selected.id !== id) state.selVertex = null;
    state.selected = id ? { kind: kind, id: id } : null;
    if (state.mode !== "select") setMode("select");
    renderAll();
    var obj = selectedObj();
    if (center && obj) {
      if (kind === "marker" && !obj.unplaced) centerOn(obj.x, obj.y, 3);
      if (kind === "area") centerOn(obj.x + obj.w / 2, obj.y + obj.h / 2, Math.min(4, Math.max(1, 40 / Math.max(obj.w, obj.h))));
    }
  }
  function pickMachine(assetId) {
    if (!hasImage) return;
    var mk = markerFor(assetId);
    if (mk && !mk.unplaced) { select("marker", mk.cid, true); return; }
    state.selected = mk ? { kind: "marker", id: mk.cid } : null;
    renderSelection();
    setMode("place", { assetId: assetId });
  }
  function placeAt(assetId, p) {
    var mk = markerFor(assetId);
    if (!mk) {
      var machine = machineById[assetId] || {};
      mk = { cid: cid("m", null), id: null, asset_id: assetId, label: machine.asset_tag || "", x: p.x, y: p.y, unplaced: false, sort_order: (state.markers.length + 1) * 10 };
      state.markers.push(mk);
    }
    mk.x = p.x; mk.y = p.y; mk.unplaced = false;
    touch();
    state.selected = { kind: "marker", id: mk.cid };
    setMode("select");
    renderAll();
  }
  function removeSelectedVertex() {
    var a = selectedObj();
    if (!a || !a.pts || state.selVertex === null || a.pts.length <= 3) return;
    a.pts.splice(state.selVertex, 1); state.selVertex = null; bboxFromPts(a); touch(); renderAll();
  }
  function removeSelected() {
    if (!state.selected) return;
    if (state.selected.kind === "area") state.areas = state.areas.filter(function (a) { return a.cid !== state.selected.id; });
    else state.markers = state.markers.filter(function (m) { return m.cid !== state.selected.id; });
    state.selected = null; touch(); renderAll();
  }
  function submitTool(tool, extra) {
    toolInput.value = tool;
    Object.keys(extra || {}).forEach(function (k) { document.getElementById("plx-crop-" + k).value = extra[k]; });
    submitting = true; sync(); form.requestSubmit ? form.requestSubmit() : form.submit();
  }
  function applyCrop() {
    if (!state.crop) return;
    submitTool("crop", { x: r2(state.crop.x), y: r2(state.crop.y), w: r2(state.crop.w), h: r2(state.crop.h) });
  }
  function autoCrop() {
    if (!hasImage || !image.naturalWidth) return;
    var scale = Math.min(1, 900 / Math.max(image.naturalWidth, image.naturalHeight));
    var w = Math.max(1, Math.round(image.naturalWidth * scale)), h = Math.max(1, Math.round(image.naturalHeight * scale));
    var canvas = document.createElement("canvas"); canvas.width = w; canvas.height = h;
    var ctx = canvas.getContext("2d"); ctx.drawImage(image, 0, 0, w, h);
    var px; try { px = ctx.getImageData(0, 0, w, h).data; } catch (err) { setStatus("Margini non calcolabili su questa immagine: usa «Ritaglia».", [], false); return; }
    var cols = new Array(w).fill(0), rows = new Array(h).fill(0);
    for (var yy = 0; yy < h; yy++) for (var xx = 0; xx < w; xx++) {
      var i = (yy * w + xx) * 4;
      if ((px[i] + px[i + 1] + px[i + 2]) / 3 < 235) { cols[xx]++; rows[yy]++; }
    }
    // Raggruppa righe/colonne con abbastanza nero in blocchi; un blocco sottile
    // vicino al bordo è la cornice del foglio e non conta come disegno.
    function span(counts, other) {
      var n = counts.length, lim = Math.max(3, other * 0.015), gap = Math.max(2, n * 0.01), runs = [], cur = null;
      counts.forEach(function (c, k) {
        if (c < lim) return;
        if (cur && k - cur[1] <= gap) cur[1] = k; else { cur = [k, k]; runs.push(cur); }
      });
      runs = runs.filter(function (r) {
        var thin = r[1] - r[0] < n * 0.01, nearEdge = r[0] < n * 0.06 || r[1] > n * 0.94;
        return !(thin && nearEdge);
      });
      return runs.length ? [runs[0][0], runs[runs.length - 1][1]] : null;
    }
    var xs = span(cols, h), ys = span(rows, w);
    if (!xs || !ys) { setStatus("Nessun disegno riconosciuto: usa «Ritaglia».", [], false); return; }
    var pad = 1;
    var x0 = clamp(xs[0] / w * 100 - pad, 0, 100), x1 = clamp((xs[1] + 1) / w * 100 + pad, 0, 100);
    var y0 = clamp(ys[0] / h * 100 - pad, 0, 100), y1 = clamp((ys[1] + 1) / h * 100 + pad, 0, 100);
    setMode("crop");
    if (x1 - x0 > 97 && y1 - y0 > 97) { setStatus("La pianta non ha margini da togliere. Trascina a mano il riquadro, se serve.", cropActions(), true); return; }
    state.crop = { x: r2(x0), y: r2(y0), w: r2(x1 - x0), h: r2(y1 - y0) };
    fit(); renderOverlay();
    setStatus("Proposta di ritaglio dei margini bianchi: correggila trascinando un nuovo riquadro, poi applica.", cropActions(), true);
  }

  /* ---------- puntatore ---------- */
  var drag = null, submitting = false;
  if (hasImage) {
    view.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 && e.button !== 1) return;
      var t = e.target, p = toPct(e);
      drag = { sx: e.clientX, sy: e.clientY, tx: tx, ty: ty, start: p, moved: false, kind: "pan", target: t };
      if (e.button === 0 && state.mode === "poly") {
        drag.kind = "poly-click";
      } else if (e.button === 0 && state.mode === "select" && t.dataset && (t.dataset.vertex || t.dataset.mid)) {
        var parts = (t.dataset.vertex || t.dataset.mid).split("|"), av = byCid(state.areas, parts[0]), vi = Number(parts[1]);
        if (t.dataset.mid) { av.pts.splice(vi + 1, 0, [p.x, p.y]); vi += 1; }
        drag.kind = "vertex"; drag.obj = av; drag.vi = vi; drag.inserted = !!t.dataset.mid;
      } else if (e.button === 0 && (state.mode === "draw" || state.mode === "crop")) {
        drag.kind = state.mode; drag.box = el("div", state.mode === "crop" ? "plx-crop" : "plx-draft"); overlay.appendChild(drag.box);
      } else if (e.button === 0 && state.mode === "select" && t.dataset && t.dataset.handle) {
        var ar = byCid(state.areas, t.dataset.handle); drag.kind = "resize"; drag.obj = ar; drag.orig = { w: ar.w, h: ar.h };
      } else if (e.button === 0 && state.mode === "select" && t.dataset && t.dataset.marker) {
        drag.kind = "marker"; drag.obj = byCid(state.markers, t.dataset.marker);
      } else if (e.button === 0 && state.mode === "select" && t.dataset && t.dataset.area && state.selected && state.selected.id === t.dataset.area) {
        var a2 = byCid(state.areas, t.dataset.area); drag.kind = "move-area"; drag.obj = a2; drag.orig = { x: a2.x, y: a2.y, pts: a2.pts ? a2.pts.map(function (q) { return q.slice(); }) : null };
      } else if (e.button === 0 && state.mode === "select" && t.dataset && t.dataset.area) {
        drag.kind = "area-click"; drag.obj = byCid(state.areas, t.dataset.area);
      }
      view.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    view.addEventListener("pointermove", function (e) {
      if (state.mode === "place" && ghost) {
        var g = toPct(e); ghost.style.display = "block"; ghost.style.left = g.x + "%"; ghost.style.top = g.y + "%";
      }
      if (!drag) return;
      if (!drag.moved && Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) > 4) drag.moved = true;
      if (!drag.moved) return;
      var p = toPct(e);
      if (drag.kind === "vertex") {
        drag.obj.pts[drag.vi] = [p.x, p.y]; bboxFromPts(drag.obj); renderOverlay(); return;
      }
      if (drag.kind === "pan" || drag.kind === "area-click" || drag.kind === "poly-click") {
        drag.kind = "pan"; view.classList.add("is-panning");
        tx = drag.tx + (e.clientX - drag.sx); ty = drag.ty + (e.clientY - drag.sy); apply();
      } else if (drag.kind === "draw" || drag.kind === "crop") {
        var bx = Math.min(drag.start.x, p.x), by = Math.min(drag.start.y, p.y);
        drag.rect = { x: bx, y: by, w: Math.abs(p.x - drag.start.x), h: Math.abs(p.y - drag.start.y) };
        drag.box.style.cssText = "left:" + bx + "%;top:" + by + "%;width:" + drag.rect.w + "%;height:" + drag.rect.h + "%";
      } else if (drag.kind === "marker") {
        drag.obj.x = p.x; drag.obj.y = p.y;
        var pin = overlay.querySelector('[data-marker="' + drag.obj.cid + '"]');
        if (pin) { pin.style.left = p.x + "%"; pin.style.top = p.y + "%"; }
      } else if (drag.kind === "move-area") {
        var nx0 = clamp(drag.orig.x + p.x - drag.start.x, 0, 100 - drag.obj.w);
        var ny0 = clamp(drag.orig.y + p.y - drag.start.y, 0, 100 - drag.obj.h);
        if (drag.orig.pts) {
          var dx = nx0 - drag.orig.x, dy = ny0 - drag.orig.y;
          drag.obj.pts = drag.orig.pts.map(function (q) { return [q[0] + dx, q[1] + dy]; });
        }
        drag.obj.x = nx0; drag.obj.y = ny0;
        renderOverlay();
      } else if (drag.kind === "resize") {
        drag.obj.w = clamp(drag.orig.w + p.x - drag.start.x, .5, 100 - drag.obj.x);
        drag.obj.h = clamp(drag.orig.h + p.y - drag.start.y, .5, 100 - drag.obj.y);
        renderOverlay();
      }
    });
    function endDrag(e) {
      if (!drag) return;
      var d = drag; drag = null; view.classList.remove("is-panning");
      var t = d.target;
      if (d.kind === "poly-click") {
        if (d.moved) return;
        var q = toPct(e);
        // chiude cliccando il primo punto, anche se sotto c'è una macchina o un altro reparto
        var f0 = state.poly[0], vicino = f0 && Math.abs(q.x - f0[0]) < 1.2 / z && Math.abs(q.y - f0[1]) < 1.2 / z;
        if (state.poly.length >= 3 && ((t && t.dataset && t.dataset.polyFirst) || vicino)) { closePoly(); return; }
        state.poly.push([q.x, q.y]); renderOverlay(); polyStatus();
        return;
      }
      if (d.kind === "vertex") {
        if (d.moved || d.inserted) { fixArea(d.obj); touch(); }
        state.selVertex = d.vi; renderAll(); return;
      }
      if (d.kind === "draw") {
        if (d.box && d.box.parentNode) d.box.parentNode.removeChild(d.box);
        if (d.rect && d.rect.w >= .5 && d.rect.h >= .5) {
          var a = { cid: cid("a", null), id: null, name: "Nuovo reparto", reparto_code: "", color: "#2563EB", notes: "",
            x: r2(d.rect.x), y: r2(d.rect.y), w: r2(d.rect.w), h: r2(d.rect.h), sort_order: (state.areas.length + 1) * 10 };
          fixArea(a); state.areas.push(a); touch();
          state.selected = { kind: "area", id: a.cid }; setMode("select"); renderAll();
          var first = selectionNode.querySelector("input"); if (first) { first.focus(); first.select(); }
        }
        return;
      }
      if (d.kind === "crop") {
        if (d.rect && d.rect.w >= 5 && d.rect.h >= 5) state.crop = { x: r2(d.rect.x), y: r2(d.rect.y), w: r2(d.rect.w), h: r2(d.rect.h) };
        renderOverlay(); setStatus(state.crop ? "Riquadro pronto: applica il ritaglio o trascinane un altro." : "Trascina il riquadro da tenere.", cropActions(), true);
        return;
      }
      if (d.kind === "marker") {
        if (d.moved) { d.obj.x = r2(d.obj.x); d.obj.y = r2(d.obj.y); touch(); }
        select("marker", d.obj.cid, false); return;
      }
      if (d.kind === "move-area" || d.kind === "resize") { if (d.moved) { fixArea(d.obj); touch(); } renderAll(); return; }
      if (d.kind === "area-click" && !d.moved) { select("area", d.obj.cid, false); return; }
      if (!d.moved) {
        if (state.mode === "place" && state.placing) { placeAt(state.placing, toPct(e)); return; }
        if (state.mode === "select" && (t === overlay || t === view)) { state.selected = null; renderAll(); }
      }
    }
    view.addEventListener("pointerup", endDrag);
    view.addEventListener("pointercancel", function () { drag = null; view.classList.remove("is-panning"); renderOverlay(); });
    view.addEventListener("pointerleave", function () { if (ghost) ghost.style.display = "none"; });
    view.addEventListener("wheel", function (e) {
      e.preventDefault();
      var r = view.getBoundingClientRect();
      zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    window.addEventListener("resize", function () { layoutBase(); apply(); });
    var ready = function () { layoutBase(); fit(); focusFromUrl(); };
    if (image.complete && image.naturalWidth) ready(); else image.addEventListener("load", ready);
  }

  /* ---------- pulsanti ---------- */
  document.querySelectorAll("[data-mode]").forEach(function (b) {
    b.addEventListener("click", function () { if (!hasImage) return; setMode(b.getAttribute("data-mode"), {}); });
  });
  document.querySelectorAll("[data-zoom]").forEach(function (b) {
    b.addEventListener("click", function () {
      var k = b.getAttribute("data-zoom");
      if (k === "fit") fit(); else zoomAt(k === "in" ? 1.5 : 1 / 1.5, view.clientWidth / 2, view.clientHeight / 2);
    });
  });
  document.querySelectorAll("[data-toggle]").forEach(function (b) {
    b.addEventListener("click", function () {
      var on = b.getAttribute("aria-pressed") !== "true";
      b.setAttribute("aria-pressed", String(on));
      view.classList.toggle("hide-" + b.getAttribute("data-toggle"), !on);
    });
  });
  document.querySelectorAll("[data-image-tool]").forEach(function (b) {
    b.disabled = !hasImage;
    b.addEventListener("click", function () { submitTool(b.getAttribute("data-image-tool")); });
  });
  var autoBtn = document.querySelector("[data-auto-crop]");
  if (autoBtn) { autoBtn.disabled = !hasImage; autoBtn.addEventListener("click", autoCrop); }
  document.querySelectorAll("[data-mode='draw'],[data-mode='poly'],[data-mode='crop']").forEach(function (b) { b.disabled = !hasImage; });
  document.querySelectorAll("[data-tab]").forEach(function (b) {
    b.addEventListener("click", function () {
      var tab = b.getAttribute("data-tab");
      document.querySelectorAll("[data-tab]").forEach(function (x) { var on = x === b; x.classList.toggle("is-active", on); x.setAttribute("aria-selected", String(on)); });
      document.querySelectorAll("[data-panel]").forEach(function (p) { p.hidden = p.getAttribute("data-panel") !== tab; });
    });
  });
  document.querySelectorAll("[data-filter]").forEach(function (b) {
    b.addEventListener("click", function () {
      state.filter = b.getAttribute("data-filter");
      document.querySelectorAll("[data-filter]").forEach(function (x) { x.classList.toggle("is-active", x === b); });
      renderMachines();
    });
  });
  searchNode.addEventListener("input", renderMachines);
  document.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "");
    if (state.mode === "poly" && !typing) {
      if (e.key === "Enter") { e.preventDefault(); closePoly(); return; }
      if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); state.poly.pop(); renderOverlay(); polyStatus(); return; }
    }
    if (e.key === "Escape") { if (state.mode !== "select") setMode("select"); else if (!typing) { state.selected = null; state.selVertex = null; renderAll(); } }
    if ((e.key === "Delete" || e.key === "Backspace") && !typing && state.selected) {
      e.preventDefault();
      var so = selectedObj();
      if (state.selected.kind === "area" && so && so.pts && state.selVertex !== null) removeSelectedVertex();
      else removeSelected();
    }
  });
  form.addEventListener("submit", function () { submitting = true; sync(); });
  window.addEventListener("beforeunload", function (e) { if (state.dirty && !submitting) { e.preventDefault(); e.returnValue = ""; } });

  function focusFromUrl() {
    var id = Number(payload.focus_asset_id || 0);
    if (!id || !machineById[id]) return;
    var m = machineById[id];
    searchNode.value = m.asset_tag || m.name || "";
    state.filter = "all";
    document.querySelectorAll("[data-filter]").forEach(function (x) { x.classList.toggle("is-active", x.getAttribute("data-filter") === "all"); });
    pickMachine(id);
  }

  sync();
  renderAll();
  if (!hasImage) setStatus("Carica l'immagine della planimetria per iniziare.", [], false);
})();
