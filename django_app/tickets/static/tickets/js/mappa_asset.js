/* Minimappa degli asset nei ticket di manutenzione.
 *
 * TicketMappa.monta(radice, opzioni) disegna le planimetrie attive (dati da
 * assets.services.mappa_ticket.mappe) e restituisce un oggetto con:
 *   mostraAsset(id, {conferma})  apre la pianta dell'asset e lo evidenzia
 *   mostraPunto(layoutId, x, y)  mette il segnaposto su un punto libero
 *   apriPreferita(codiceCategoria)  apre la pianta scelta per la categoria ticket
 *   haAsset(id)                  l'asset è su qualche pianta?
 * Opzioni: mappe, preferite, selezionabile, permettiPunto, onAsset(marker),
 * onPunto({layout, x, y}), linkMappa (URL della mappa officina, «?asset=» in coda).
 */
(function () {
  "use strict";

  var ZOOM = [1, 1.5, 2, 3];

  function el(tag, cls, testo) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (testo !== undefined && testo !== null) n.textContent = testo;
    return n;
  }

  function descrivi(m) {
    return [m.nome, m.categoria, m.reparto ? "Reparto " + m.reparto : ""].filter(Boolean).join(" · ");
  }

  function monta(radice, opzioni) {
    var o = opzioni || {};
    var mappe = o.mappe || [];
    var preferite = o.preferite || {};
    var stato = { mappa: null, zoom: 0, soloMie: false, selezionato: null, punto: null };

    radice.classList.add("tmap");
    radice.innerHTML = "";
    if (!mappe.length) {
      radice.appendChild(el("div", "tmap-vuota", "Nessuna planimetria con asset collocati."));
      return { mostraAsset: function () { return false; }, mostraPunto: function () {}, apriPreferita: function () {}, haAsset: function () { return false; } };
    }

    var testa = el("div", "tmap-testa");
    var schede = el("div", "tmap-schede");
    var strumenti = el("div", "tmap-strumenti");
    var soloMieLbl = el("label", "tmap-solomie");
    var soloMie = el("input");
    soloMie.type = "checkbox";
    soloMieLbl.appendChild(soloMie);
    soloMieLbl.appendChild(document.createTextNode(" Solo il mio reparto"));
    var meno = el("button", "tmap-zoom", "−");
    var piu = el("button", "tmap-zoom", "+");
    meno.type = piu.type = "button";
    meno.setAttribute("aria-label", "Riduci");
    piu.setAttribute("aria-label", "Ingrandisci");
    strumenti.appendChild(soloMieLbl);
    strumenti.appendChild(meno);
    strumenti.appendChild(piu);
    testa.appendChild(schede);
    testa.appendChild(strumenti);

    var avviso = el("div", "tmap-avviso");
    avviso.hidden = true;
    var finestra = el("div", "tmap-finestra");
    var tela = el("div", "tmap-tela");
    var immagine = el("img", "tmap-img");
    immagine.alt = "";
    var livello = el("div", "tmap-livello");
    tela.appendChild(immagine);
    tela.appendChild(livello);
    finestra.appendChild(tela);
    var info = el("div", "tmap-info");
    var legenda = el("div", "tmap-legenda");
    legenda.appendChild(el("span", "tmap-leg tmap-leg-mio", "Del tuo reparto"));
    legenda.appendChild(el("span", "tmap-leg tmap-leg-altro", "Altri reparti"));
    if (o.permettiPunto) legenda.appendChild(el("span", "tmap-leg-nota", "Non lo trovi? Tocca il punto sulla pianta."));
    var link = null;
    if (o.linkMappa) {
      link = el("a", "tmap-link", "Apri la mappa completa");
      link.target = "_blank";
      link.rel = "noopener";
      link.hidden = true;
      legenda.appendChild(link);
    }

    radice.appendChild(testa);
    radice.appendChild(avviso);
    radice.appendChild(finestra);
    radice.appendChild(info);
    radice.appendChild(legenda);

    mappe.forEach(function (m) {
      var b = el("button", "tmap-scheda");
      b.type = "button";
      b.dataset.id = m.id;
      b.appendChild(document.createTextNode(m.categoria));
      if (m.mie) b.appendChild(el("span", "tmap-conta", String(m.mie)));
      b.addEventListener("click", function () { apri(m); });
      schede.appendChild(b);
    });

    function aggiornaInfo(testo) {
      info.textContent = testo || (o.selezionabile ? "Tocca un punto per scegliere l'asset." : "");
    }

    function disegna() {
      var m = stato.mappa;
      livello.innerHTML = "";
      tela.style.width = (ZOOM[stato.zoom] * 100) + "%";
      (m.aree || []).forEach(function (a) {
        if (a.punti && a.punti.length >= 3) {
          // reparto a forma libera: poligono in SVG sulla pianta intera
          var ns = "http://www.w3.org/2000/svg";
          var svg = document.createElementNS(ns, "svg");
          svg.setAttribute("class", "tmap-area-svg");
          svg.setAttribute("viewBox", "0 0 100 100");
          svg.setAttribute("preserveAspectRatio", "none");
          var poly = document.createElementNS(ns, "polygon");
          poly.setAttribute("points", a.punti.map(function (p) { return p[0] + "," + p[1]; }).join(" "));
          poly.setAttribute("class", a.mia ? "tmap-area-mia" : "");
          poly.style.stroke = a.colore;
          var t = document.createElementNS(ns, "title");
          t.textContent = a.nome;
          poly.appendChild(t);
          svg.appendChild(poly);
          livello.appendChild(svg);
          return;
        }
        var r = el("div", "tmap-area" + (a.mia ? " tmap-area-mia" : ""));
        r.style.left = a.x + "%";
        r.style.top = a.y + "%";
        r.style.width = a.w + "%";
        r.style.height = a.h + "%";
        r.style.borderColor = a.colore;
        r.title = a.nome;
        livello.appendChild(r);
      });
      m.markers.forEach(function (mk) {
        if (stato.soloMie && !mk.mio && mk.asset_id !== stato.selezionato) return;
        var p = el("button", "tmap-pin " + (mk.mio ? "tmap-mio" : "tmap-altro"));
        p.type = "button";
        p.style.left = mk.x + "%";
        p.style.top = mk.y + "%";
        p.setAttribute("aria-label", descrivi(mk));
        p.title = descrivi(mk);
        if (mk.asset_id === stato.selezionato) p.classList.add("tmap-sel");
        if (!o.selezionabile) p.tabIndex = -1;
        p.addEventListener("mouseenter", function () { aggiornaInfo(descrivi(mk)); });
        p.addEventListener("focus", function () { aggiornaInfo(descrivi(mk)); });
        p.addEventListener("click", function (ev) {
          ev.stopPropagation();
          aggiornaInfo(descrivi(mk));
          if (!o.selezionabile) return;
          stato.selezionato = mk.asset_id;
          stato.punto = null;
          avviso.hidden = true;
          disegna();
          if (o.onAsset) o.onAsset(mk);
        });
        livello.appendChild(p);
      });
      if (stato.punto && stato.punto.layout === m.id) {
        var s = el("span", "tmap-punto");
        s.style.left = stato.punto.x + "%";
        s.style.top = stato.punto.y + "%";
        s.title = "Punto indicato";
        livello.appendChild(s);
      }
    }

    function apri(m) {
      stato.mappa = m;
      Array.prototype.forEach.call(schede.children, function (b) {
        b.classList.toggle("attiva", String(b.dataset.id) === String(m.id));
      });
      if (immagine.getAttribute("src") !== m.immagine) immagine.src = m.immagine;
      immagine.alt = m.nome;
      disegna();
    }

    function centra(x, y) {
      // porta il punto al centro della finestra, a immagine caricata e ridisegno fatto
      function vai() {
        window.requestAnimationFrame(function () {
          window.requestAnimationFrame(function () {
            finestra.scrollLeft = Math.max(0, tela.offsetWidth * x / 100 - finestra.clientWidth / 2);
            finestra.scrollTop = Math.max(0, tela.offsetHeight * y / 100 - finestra.clientHeight / 2);
          });
        });
      }
      if (immagine.complete && immagine.naturalWidth) vai();
      else immagine.addEventListener("load", vai, { once: true });
    }

    function trova(id) {
      for (var i = 0; i < mappe.length; i += 1) {
        for (var j = 0; j < mappe[i].markers.length; j += 1) {
          if (mappe[i].markers[j].asset_id === id) return { mappa: mappe[i], marker: mappe[i].markers[j] };
        }
      }
      return null;
    }

    soloMie.addEventListener("change", function () { stato.soloMie = soloMie.checked; disegna(); });
    meno.addEventListener("click", function () { if (stato.zoom > 0) { stato.zoom -= 1; disegna(); } });
    piu.addEventListener("click", function () { if (stato.zoom < ZOOM.length - 1) { stato.zoom += 1; disegna(); } });

    if (o.permettiPunto) {
      livello.classList.add("tmap-puntabile");
      livello.addEventListener("click", function (ev) {
        var r = livello.getBoundingClientRect();
        if (!r.width || !r.height) return;
        var x = Math.round(((ev.clientX - r.left) / r.width) * 10000) / 100;
        var y = Math.round(((ev.clientY - r.top) / r.height) * 10000) / 100;
        stato.punto = { layout: stato.mappa.id, x: x, y: y, nome: stato.mappa.nome };
        stato.selezionato = null;
        avviso.hidden = false;
        avviso.textContent = "Punto indicato sulla " + stato.mappa.nome + ": chi gestisce il ticket collegherà l'asset giusto.";
        disegna();
        if (o.onPunto) o.onPunto(stato.punto);
      });
    }

    var iniziale = mappe.slice().sort(function (a, b) { return b.mie - a.mie; })[0];
    apri(iniziale);
    aggiornaInfo("");

    return {
      haAsset: function (id) { return !!trova(Number(id)); },
      mostraAsset: function (id, opz) {
        var t = trova(Number(id));
        stato.selezionato = t ? t.marker.asset_id : null;
        stato.punto = null;
        if (link) {
          link.hidden = !t;
          if (t) link.href = o.linkMappa + "?asset=" + t.marker.asset_id;
        }
        if (!t) { avviso.hidden = true; disegna(); return false; }
        if (stato.zoom < 1) stato.zoom = 1;
        apri(t.mappa);
        aggiornaInfo(descrivi(t.marker));
        if (opz && opz.conferma) {
          avviso.hidden = false;
          avviso.textContent = "È questo? Controlla sulla pianta che sia l'asset giusto: " + descrivi(t.marker) + ".";
        } else {
          avviso.hidden = true;
        }
        centra(t.marker.x, t.marker.y);
        return true;
      },
      mostraPunto: function (layoutId, x, y) {
        var m = mappe.filter(function (k) { return String(k.id) === String(layoutId); })[0];
        if (!m) return false;
        stato.punto = { layout: m.id, x: Number(x), y: Number(y), nome: m.nome };
        if (stato.zoom < 1) stato.zoom = 1;
        apri(m);
        centra(Number(x), Number(y));
        return true;
      },
      apriPreferita: function (codice) {
        var nome = preferite[codice];
        if (!nome || stato.selezionato) return;
        var m = mappe.filter(function (k) { return k.categoria.toLowerCase() === nome.toLowerCase(); })[0];
        if (m) apri(m);
      },
    };
  }

  window.TicketMappa = { monta: monta };
})();
