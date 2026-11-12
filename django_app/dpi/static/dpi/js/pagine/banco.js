/* NOVICROM HUB — da dpi/pages/banco.html (blocco 1), spostato dall'inline il 12/11/2026: stesso punto, ora in cache. */
(function () {
  var radice = document.getElementById('dpi-root');
  var catalogo = JSON.parse(document.getElementById('banco-catalogo').textContent);
  var ATTESA_SECONDI = 6;
  var sospesa = null, coda = Promise.resolve();
  var lavoro = document.getElementById('banco-lavoro');
  var cerca = document.getElementById('banco-cerca');
  var scelta = null, filtro = '', attiva = null, occupato = false, lettoreAttivo = false;
  // lettura: esito dell'ultimo badge passato, {chiave, testo, diretta}. attesa: scheda che aspetta il badge.
  var lettura = null, attesa = null;
  var SECONDI_ATTESA_BADGE = 60;

  function norm(s) { return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }
  function righe() { return Array.prototype.slice.call(lavoro.querySelectorAll('.banco-persona')); }
  function visibili() { return righe().filter(function (r) { return !r.hidden; }); }

  function consegnaBtn(card) { return card && card.querySelector('[data-consegna]'); }

  // Il pulsante dice cosa succede: quanti DPI, a chi.
  function sincronizza(card) {
    var spunte = Array.prototype.slice.call(card.querySelectorAll('input[name=ids]'));
    var scelte = spunte.filter(function (c) { return c.checked; });
    var btn = consegnaBtn(card);
    var conFirma = !!card.querySelector('input[name=firmato_ricevuta]:checked') || !!(card.querySelector('[data-firma]') || {})._ink;
    btn.disabled = !scelte.length;
    btn.textContent = !scelte.length ? 'Spunta almeno un DPI' : (conFirma ? 'Consegna con la firma' : 'Consegna con mail');
    var inAttesa = attesa && attesa.card === card;
    var btnBadge = card.querySelector('[data-conferma-badge]');
    var haBadge = !!card.getAttribute('data-ha-badge');
    btnBadge.disabled = !scelte.length || !haBadge || !lettoreAttivo;
    btnBadge.textContent = inAttesa ? 'Annulla attesa badge' : 'Consegna con badge';
    var pronto = card.querySelector('[data-pronto]');
    if (pronto) pronto.disabled = !scelte.some(function (c) { return !c.getAttribute('data-pronta'); });
    var manca = scelte.some(function (c) { return c.getAttribute('data-manca'); });
    card.querySelector('[data-avviso-giacenza]').hidden = !manca && !card._serveMotivo;
    card.querySelector('[data-motivo]').hidden = !manca && !card._serveMotivo;
    card.querySelectorAll('[data-cambia]').forEach(function (b) {
      var modelli = catalogo[b.getAttribute('data-categoria')] || [];
      b.hidden = !modelli.length || (modelli.length === 1 && String(modelli[0].id) === b.getAttribute('data-modello') && modelli[0].taglie.length < 2);
    });
    var invito = card.querySelector('[data-badge-invito]');
    invito.hidden = !inAttesa && (!scelte.length || (haBadge && lettoreAttivo));
    invito.classList.toggle('attesa', !!inAttesa);
    invito.textContent = inAttesa
      ? 'Passa ora il badge di ' + card.getAttribute('data-nome') + ' per ' + scelte.length + ' DPI.'
      : (!haBadge ? 'Nessun badge in Anagrafica per questa persona: usa la conferma con mail.' : 'Per confermare con il badge collega il lettore.');
  }

  function fermaAttesa() {
    if (!attesa) return;
    var card = attesa.card;
    clearTimeout(attesa.timer);
    attesa = null;
    sincronizza(card);
  }

  function seleziona(chiave, opzioni) {
    scelta = chiave || null;
    if (attesa && attesa.card.id !== scelta) fermaAttesa();
    var trovata = null;
    lavoro.querySelectorAll('.dpi-persona').forEach(function (card) {
      var si = card.id === scelta;
      card.hidden = !si;
      if (si) trovata = card;
    });
    if (!trovata) scelta = null;
    righe().forEach(function (r) {
      var si = r.getAttribute('data-chiave') === scelta;
      r.classList.toggle('scelta', si);
      r.setAttribute('aria-selected', si ? 'true' : 'false');
    });
    var invito = document.getElementById('banco-invito');
    if (invito) invito.hidden = !!trovata;
    if (trovata) {
      sincronizza(trovata);
      if (opzioni && opzioni.scorri && window.matchMedia('(max-width:900px)').matches) {
        trovata.scrollIntoView({behavior: 'smooth', block: 'start'});
      }
      if (opzioni && opzioni.fuoco) consegnaBtn(trovata).focus();
    }
    return trovata;
  }

  function evidenzia(riga) {
    if (attiva) attiva.classList.remove('attiva');
    attiva = riga || null;
    if (attiva) { attiva.classList.add('attiva'); attiva.scrollIntoView({block: 'nearest'}); }
  }

  function applica() {
    var q = norm(cerca.value.trim());
    var parole = q ? q.split(/\s+/) : [];
    var quante = 0, ultima = null;
    righe().forEach(function (r) {
      var testo = norm(r.getAttribute('data-cerca'));
      var ok = (lettura ? r.getAttribute('data-chiave') === lettura.chiave : parole.every(function (p) { return testo.indexOf(p) !== -1; }))
        && (!filtro || Number(r.getAttribute('data-' + filtro)) > 0);
      r.hidden = !ok;
      if (ok) { quante++; ultima = r; }
    });
    var nessuno = document.getElementById('banco-nessuno');
    if (nessuno) nessuno.hidden = quante > 0;
    var testoNessuno = document.getElementById('banco-nessuno-testo');
    if (testoNessuno) testoNessuno.textContent = lettura ? lettura.testo : 'Nessuna persona trovata.';
    var bottoneDiretta = nessuno && nessuno.querySelector('[data-apri-diretta]');
    if (bottoneDiretta) bottoneDiretta.setAttribute('data-apri-diretta', lettura ? lettura.diretta : '');
    lavoro.querySelectorAll('[data-filtro]').forEach(function (b) {
      b.classList.toggle('attivo', b.getAttribute('data-filtro') === filtro);
    });
    var cercando = q || lettura;
    evidenzia(cercando ? visibili()[0] : null);
    // Una sola persona trovata: la scheda e' gia' aperta.
    if (cercando && quante === 1) seleziona(ultima.getAttribute('data-chiave'));
    else if (cercando && scelta && !visibili().some(function (r) { return r.getAttribute('data-chiave') === scelta; })) seleziona(null);
  }

  // Firma: si prepara quando si apre il riquadro.
  function preparaFirma(canvas) {
    var ctx = canvas.getContext('2d');
    var drawing = false;
    canvas._ink = false;
    var rect = canvas.getBoundingClientRect();
    var scale = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * scale));
    canvas.height = Math.max(1, Math.floor(rect.height * scale));
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.lineWidth = 2; ctx.strokeStyle = '#0f172a';
    function pt(e) {
      var r = canvas.getBoundingClientRect();
      var t = e.touches && e.touches[0] ? e.touches[0] : e;
      return {x: t.clientX - r.left, y: t.clientY - r.top};
    }
    function start(e) { e.preventDefault(); drawing = true; var p = pt(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); }
    function move(e) { if (!drawing) return; e.preventDefault(); var p = pt(e); ctx.lineTo(p.x, p.y); ctx.stroke(); canvas._ink = true; }
    function end() {
      if (drawing && canvas.closest('.dpi-persona')) sincronizza(canvas.closest('.dpi-persona'));
      drawing = false;
    }
    canvas.addEventListener('mousedown', start);
    canvas.addEventListener('mousemove', move);
    canvas.addEventListener('mouseup', end);
    canvas.addEventListener('mouseleave', end);
    canvas.addEventListener('touchstart', start, {passive: false});
    canvas.addEventListener('touchmove', move, {passive: false});
    canvas.addEventListener('touchend', end);
    canvas._clear = function () { ctx.clearRect(0, 0, canvas.width, canvas.height); canvas._ink = false; sincronizza(canvas.closest('.dpi-persona')); };
  }

  function errore(testo) {
    if (window.hubFlash) window.hubFlash.show([{level: 'error', text: testo, count: 1}]);
  }

  // «tieni»: la scheda aperta resta com'e' (spunte, note, firma), cambia solo il resto.
  function aggiorna(html, apri, tieni) {
    var tenuta = tieni && scelta ? document.getElementById(scelta) : null;
    var eraScelta = scelta;
    lavoro.innerHTML = html;
    if (tenuta) {
      var nuova = document.getElementById(tenuta.id);
      if (nuova) nuova.replaceWith(tenuta);
    }
    applica();
    if (tieni) seleziona(eraScelta);
    else seleziona(apri, {scorri: !!apri});
  }

  function inCoda(lavoroDaFare) {
    coda = coda.then(lavoroDaFare, lavoroDaFare);
    return coda;
  }

  // La consegna e' gia' sul server: qui aspettano solo mail e PDF, per poter annullare.
  // Se il browser sparisce, gli avvisi rimasti li manda il server.
  function mostraAttesa() {
    var barra = document.getElementById('banco-annulla');
    barra.hidden = !sospesa;
    if (sospesa) document.getElementById('banco-annulla-testo').textContent =
      sospesa.n + ' DPI a ' + sospesa.nome + (sospesa.conBadge ? ' confermati con il badge' : ' registrati') + ': avvisi tra ' + sospesa.resto + ' s';
  }

  function avviaConto() {
    sospesa.conto = setInterval(function () {
      sospesa.resto -= 1;
      if (sospesa.resto <= 0) inviaAvvisi();
      else mostraAttesa();
    }, 1000);
    mostraAttesa();
  }

  function chiudiAttesa() {
    clearInterval(sospesa.conto);
    var s = sospesa;
    sospesa = null;
    mostraAttesa();
    return s;
  }

  function datiSospesa(s, azione) {
    var dati = new FormData();
    dati.set('csrfmiddlewaretoken', s.csrf);
    dati.set('azione', azione);
    dati.set('tutte', s.tutte);
    s.ids.forEach(function (id) { dati.append('ids', id); });
    return dati;
  }

  function indirizzo() { return window.location.pathname + window.location.search; }

  function inviaAvvisi() {
    if (!sospesa || sospesa.annullo) return;
    var s = chiudiAttesa();
    inCoda(function () {
      return chiedi(indirizzo(), {method: 'POST', body: datiSospesa(s, 'avvisi')}).then(function (r) {
        aggiorna(r.html, '', true);
      }).catch(function () {});  // la consegna e' salva: gli avvisi li recupera il server
    });
  }

  function annullaConsegna() {
    if (!sospesa || sospesa.annullo) return;
    var s = sospesa;
    s.annullo = true;
    clearInterval(s.conto);
    inCoda(function () {
      return chiedi(indirizzo(), {method: 'POST', body: datiSospesa(s, 'annulla')}).then(function (r) {
        chiudiAttesa();
        if (!r.annullate.length) { aggiorna(r.html, '', true); return; }
        cerca.value = '';
        lettura = null;
        aggiorna(r.html, '');
        // Torna la scheda di prima, con spunte, note e firma.
        var nuova = document.getElementById(s.chiave);
        if (nuova) nuova.replaceWith(s.card);
        applica();
        seleziona(s.chiave, {scorri: true, fuoco: true});
      }).catch(function (e) {
        if (e.message === 'ricarica') return;
        s.annullo = false;
        avviaConto();
        errore('Connessione assente: la consegna resta registrata. Riprova ad annullare.');
      });
    });
  }

  function manca_motivo(card) {
    var motivo = card.querySelector('[data-motivo]');
    var campoMotivo = motivo.querySelector('input');
    if (motivo.hidden || campoMotivo.value.trim()) return false;
    errore('Scrivi il motivo della consegna senza giacenza.');
    campoMotivo.focus();
    return true;
  }

  function avviaConsegna(form, bottone, prova) {
    if (occupato) return;
    var card = form.closest('.dpi-persona');
    var campoMotivo = card.querySelector('[data-motivo] input');
    if (manca_motivo(card)) return;
    inviaAvvisi();
    var canvas = card.querySelector('[data-firma]');
    card.querySelector('input[name=firma_immagine]').value = canvas._ink ? canvas.toDataURL('image/png') : '';
    var dati = new FormData(form);
    dati.set('azione', 'consegna');
    dati.set('differisci', '1');
    if (prova) dati.set('prova_badge', prova);
    var nome = card.getAttribute('data-nome');
    occupato = true;
    bottone.disabled = true;
    bottone.textContent = 'Un momento…';
    inCoda(function () { return chiedi(indirizzo(), {method: 'POST', body: dati}); }).then(function (r) {
      if (!r.registrate.length) {  // rifiutata dal server: il motivo del rifiuto e' nel messaggio
        card._serveMotivo = card._serveMotivo || r.motivo;
        aggiorna(r.html, '', true);
        sincronizza(card);
        if (r.motivo) campoMotivo.focus();
        return;
      }
      sospesa = {
        ids: r.registrate, n: r.registrate.length, chiave: card.id, card: card, nome: nome, resto: ATTESA_SECONDI, conBadge: !!prova,
        csrf: dati.get('csrfmiddlewaretoken'), tutte: dati.get('tutte') || '',
      };
      cerca.value = '';
      lettura = null;
      aggiorna(r.html, '');
      avviaConto();
      cerca.focus();
    }).catch(function (e) {
      if (e.message === 'ricarica') return;
      sincronizza(card);
      errore('Connessione assente: la consegna a ' + nome + ' non è stata registrata. Riprova.');
    }).then(function () { occupato = false; });
  }

  // Si esce dalla pagina durante l'attesa: gli avvisi partono subito.
  window.addEventListener('pagehide', function () {
    if (!sospesa || sospesa.annullo) return;
    var s = chiudiAttesa();
    navigator.sendBeacon(indirizzo(), datiSospesa(s, 'avvisi'));
  });

  function apriCambio(b) {
    var riga = b.closest('li');
    var aperto = riga.querySelector('.banco-cambio');
    if (aperto) { aperto.remove(); return; }
    var modelli = catalogo[b.getAttribute('data-categoria')] || [];
    var box = document.createElement('div');
    box.className = 'banco-cambio';
    var hid = document.createElement('input');
    hid.type = 'hidden'; hid.name = 'cambia_richiesta'; hid.value = b.getAttribute('data-richiesta');
    var sm = document.createElement('select');
    sm.name = 'cambia_modello';
    sm.setAttribute('aria-label', 'Modello');
    modelli.forEach(function (m) {
      var o = document.createElement('option');
      o.value = m.id;
      o.textContent = m.nome + ' · in magazzino ' + m.giacenza;
      sm.appendChild(o);
    });
    if (b.getAttribute('data-modello')) sm.value = b.getAttribute('data-modello');
    var st = document.createElement('select');
    st.name = 'cambia_taglia';
    st.setAttribute('aria-label', 'Taglia');
    function taglie() {
      var m = modelli.filter(function (x) { return String(x.id) === sm.value; })[0];
      st.textContent = '';
      var vuota = document.createElement('option');
      vuota.value = ''; vuota.textContent = 'Taglia non indicata';
      st.appendChild(vuota);
      (m ? m.taglie : []).forEach(function (t) {
        var o = document.createElement('option');
        o.value = t.id; o.textContent = t.valore;
        st.appendChild(o);
      });
      st.hidden = !m || !m.taglie.length;
    }
    sm.addEventListener('change', taglie);
    taglie();
    if (b.getAttribute('data-taglia')) st.value = b.getAttribute('data-taglia');
    var ok = document.createElement('button');
    ok.type = 'submit'; ok.name = 'azione'; ok.value = 'cambia'; ok.formNoValidate = true;
    ok.className = 'dpi-btn dpi-btn-blue'; ok.textContent = 'Salva';
    var no = document.createElement('button');
    no.type = 'button'; no.className = 'dpi-btn dpi-btn-gray'; no.textContent = 'Lascia così';
    no.addEventListener('click', function () { box.remove(); });
    [hid, sm, st, ok, no].forEach(function (el) { box.appendChild(el); });
    riga.appendChild(box);
    sm.focus();
  }

  function chiedi(url, opzioni) {
    opzioni = opzioni || {};
    opzioni.credentials = 'same-origin';
    opzioni.headers = {'X-Requested-With': 'XMLHttpRequest'};
    return fetch(url, opzioni).then(function (res) {
      var html = (res.headers.get('Content-Type') || '').indexOf('text/html') !== -1;
      // Sessione scaduta o permesso tolto: si ricarica la pagina, ci pensa il portale.
      if (!res.ok || res.redirected || !html) { window.location.reload(); throw new Error('ricarica'); }
      return res.text().then(function (testo) {
        return {
          html: testo, apri: res.headers.get('X-Banco-Apri') || '', motivo: !!res.headers.get('X-Banco-Motivo'),
          registrate: (res.headers.get('X-Banco-Registrate') || '').split(',').filter(Boolean),
          annullate: (res.headers.get('X-Banco-Annullate') || '').split(',').filter(Boolean),
        };
      });
    });
  }

  function invia(form, bottone) {
    if (bottone && bottone.value === 'consegna') { avviaConsegna(form, bottone); return; }
    if (occupato) return;
    inviaAvvisi();
    var card = form.closest('.dpi-persona');
    var canvas = card && card.querySelector('[data-firma]');
    if (canvas) card.querySelector('input[name=firma_immagine]').value = canvas._ink ? canvas.toDataURL('image/png') : '';
    var dati = new FormData(form);
    if (bottone && bottone.value === 'pronta') dati.delete('cambia_richiesta');
    if (bottone && bottone.hasAttribute('data-approva')) dati.set('approva_richiesta', bottone.getAttribute('data-richiesta'));
    if (bottone && bottone.name) dati.set(bottone.name, bottone.value);
    var azione = dati.get('azione');
    occupato = true;
    var etichetta = bottone ? bottone.textContent : '';
    if (bottone) { bottone.disabled = true; bottone.textContent = 'Un momento…'; }
    inCoda(function () { return chiedi(window.location.pathname + window.location.search, {method: 'POST', body: dati}); }).then(function (r) {
      var conBadge = azione === 'diretta' && bottone && bottone.hasAttribute('data-diretta-badge');
      if (azione === 'diretta') {
        form.reset();
        var dip = document.getElementById('diretta-dip');
        if (dip && dip.tomselect) dip.tomselect.clear(true);
        document.getElementById('diretta').open = false;
        if (bottone) { bottone.disabled = false; bottone.textContent = etichetta; }
      }
      aggiorna(r.html, r.apri);
      // «Aggiungi e consegna con badge»: la scheda e' aperta col DPI spuntato, si aspetta subito il badge.
      if (conBadge && r.apri) {
        var apertaCard = document.getElementById(r.apri);
        var btnBadge = apertaCard && apertaCard.querySelector('[data-conferma-badge]');
        if (btnBadge && !btnBadge.disabled) btnBadge.click();
      }
    }).catch(function (e) {
      if (e.message === 'ricarica') return;
      if (bottone) { bottone.disabled = false; bottone.textContent = etichetta; }
      errore('Connessione assente: operazione non registrata. Riprova.');
    }).then(function () { occupato = false; });
  }

  radice.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form.closest('.dpi-persona') && !form.closest('#diretta')) return;
    e.preventDefault();
    invia(form, e.submitter);
  });

  radice.addEventListener('click', function (e) {
    var el;
    if ((el = e.target.closest('.banco-persona'))) { seleziona(el.getAttribute('data-chiave'), {scorri: true}); return; }
    if ((el = e.target.closest('[data-cambia]'))) { e.preventDefault(); apriCambio(el); return; }
    if ((el = e.target.closest('[data-conferma-badge]'))) {
      var perBadge = el.closest('.dpi-persona');
      if (attesa && attesa.card === perBadge) { fermaAttesa(); return; }
      fermaAttesa();
      if (manca_motivo(perBadge)) return;
      attesa = {card: perBadge, timer: setTimeout(function () {
        fermaAttesa();
        errore('Tempo scaduto: clicca di nuovo «Consegna con badge» o usa la mail.');
      }, SECONDI_ATTESA_BADGE * 1000)};
      sincronizza(perBadge);
      return;
    }
    if ((el = e.target.closest('[data-filtro]'))) {
      var f = el.getAttribute('data-filtro');
      filtro = filtro === f ? '' : f;
      applica();
      return;
    }
    if ((el = e.target.closest('[data-spunta]'))) {
      var card = el.closest('.dpi-persona');
      card.querySelectorAll('input[name=ids]').forEach(function (c) { c.checked = el.getAttribute('data-spunta') === '1'; });
      sincronizza(card);
      return;
    }
    if ((el = e.target.closest('[data-cancella-firma]'))) {
      var canvas = el.closest('.dpi-persona').querySelector('[data-firma]');
      if (canvas._clear) canvas._clear();
      return;
    }
    if ((el = e.target.closest('[data-apri-diretta]'))) {
      var box = document.getElementById('diretta');
      if (!box) return;
      box.open = true;
      var dip = document.getElementById('diretta-dip');
      var persona = el.getAttribute('data-apri-diretta');
      if (persona && dip) { if (dip.tomselect) dip.tomselect.setValue(persona); else dip.value = persona; }
      else if (dip && dip.tomselect && cerca.value.trim()) { dip.tomselect.clear(true); dip.tomselect.open(); dip.tomselect.setTextboxValue(cerca.value.trim()); dip.tomselect.refreshOptions(false); }
      box.scrollIntoView({behavior: 'smooth', block: 'center'});
      var mod = document.getElementById('diretta-mod');
      if (mod) mod.focus();
    }
  });

  radice.addEventListener('change', function (e) {
    if (e.target.name === 'ids' || e.target.name === 'firmato_ricevuta') {
      var cardCambiata = e.target.closest('.dpi-persona');
      if (attesa && attesa.card === cardCambiata) fermaAttesa();
      sincronizza(cardCambiata);
    }
  });

  // «toggle» non risale: si ascolta in cattura.
  radice.addEventListener('toggle', function (e) {
    if (e.target.classList && e.target.classList.contains('dpi-firma-box') && e.target.open) {
      var canvas = e.target.querySelector('[data-firma]');
      if (!canvas._clear) preparaFirma(canvas);
    }
  }, true);

  // Invio su spunte e note non registra la consegna: serve il pulsante.
  lavoro.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault();
    if (e.key === 'Escape') { cerca.focus(); cerca.select(); }
  });

  // Badge passato sul lettore: il server verifica subito di chi e', il numero non torna qui.
  function mostraLettura(chiave, testo, diretta) {
    lettura = {chiave: chiave, testo: testo, diretta: diretta || ''};
    cerca.value = '';
    filtro = '';
    applica();
    if (!document.getElementById('banco-nessuno')) errore(testo);
  }

  function suLettura(messaggio) {
    var dati = new FormData();
    dati.set('csrfmiddlewaretoken', document.querySelector('#banco-lettore [name=csrfmiddlewaretoken]').value);
    dati.set('azione', 'verifica_badge');
    dati.set('messaggio', messaggio);
    fetch(indirizzo(), {method: 'POST', body: dati, credentials: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'}}).then(function (res) {
      var json = (res.headers.get('Content-Type') || '').indexOf('application/json') !== -1;
      if (res.redirected || !json) { window.location.reload(); throw new Error('ricarica'); }
      return res.json();
    }).then(function (r) {
      if (r.esito === 'bloccato') {
        fermaAttesa();
        errore('Troppi badge non riconosciuti: lettura sospesa per qualche minuto.');
        return;
      }
      var card = r.esito === 'ok' ? document.getElementById(r.chiave) : null;
      if (attesa) {
        if (card === attesa.card) {
          var persona = attesa.card;
          lettoreStato.textContent = 'Badge verificato: ' + persona.getAttribute('data-nome') + '.';
          clearTimeout(attesa.timer);
          attesa = null;
          sincronizza(persona);
          var bottone = persona.querySelector('[data-conferma-badge]');
          avviaConsegna(bottone.form, bottone, r.prova);
        } else {
          errore(r.esito === 'ok' ? 'Badge di un\'altra persona: DPI non consegnati. Passa il badge giusto o usa la mail.' : 'Badge non riconosciuto: DPI non consegnati. Passa il badge giusto o usa la mail.');
        }
        return;
      }
      if (r.esito !== 'ok') { mostraLettura('-', 'Badge non riconosciuto: cerca la persona per nome.'); return; }
      lettoreStato.textContent = 'Badge verificato: ' + (r.nome || 'persona trovata') + '.';
      if (!card) { mostraLettura('-', (r.nome || 'Questa persona') + ' non ha DPI da ritirare.', r.id); return; }
      mostraLettura(r.chiave, '');
      seleziona(r.chiave, {scorri: true});
    }).catch(function (e) {
      if (e.message !== 'ricarica') errore('Connessione assente: lettura del badge non verificata. Ripassalo.');
    });
  }

  var lettoreBtn = document.getElementById('lettore-collega');
  var lettoreStato = document.getElementById('lettore-stato');
  if (window.LettoreBadge && window.LettoreBadge.disponibile()) {
    lettoreBtn.hidden = false;
    window.LettoreBadge.avvia({bottone: lettoreBtn, stato: lettoreStato, suLettura: suLettura, suStato: function (collegato) {
      lettoreAttivo = collegato;
      if (!collegato) fermaAttesa();
      var aperta = scelta ? document.getElementById(scelta) : null;
      if (aperta) sincronizza(aperta);
    }});
  } else {
    lettoreStato.textContent = 'Per il lettore di badge serve Chrome o Edge.';
    lettoreStato.classList.add('errore');
  }

  document.getElementById('banco-annulla-si').addEventListener('click', annullaConsegna);
  document.getElementById('banco-annulla-ora').addEventListener('click', inviaAvvisi);
  cerca.addEventListener('input', function () { lettura = null; applica(); });
  cerca.addEventListener('keydown', function (e) {
    var lista = visibili();
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!lista.length) return;
      var i = lista.indexOf(attiva);
      i = e.key === 'ArrowDown' ? (i + 1) % lista.length : (i <= 0 ? lista.length - 1 : i - 1);
      evidenzia(lista[i]);
      seleziona(lista[i].getAttribute('data-chiave'));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      var riga = attiva || (lista.length === 1 ? lista[0] : null);
      if (riga) seleziona(riga.getAttribute('data-chiave'), {scorri: true, fuoco: true});
    } else if (e.key === 'Escape') {
      if (sospesa) { annullaConsegna(); return; }
      cerca.value = '';
      filtro = '';
      lettura = null;
      seleziona(null);
      applica();
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable) return;
    if (e.key === '/') e.preventDefault();
    // Tasti con il fuoco su un pulsante: si scrive nella ricerca, cosi' l'Invio non conferma la consegna aperta.
    else if (e.key.length !== 1 || e.key === ' ') return;
    cerca.focus();
    cerca.select();
  });

  // Taglie del DPI scelto nella consegna diretta.
  var mod = document.getElementById('diretta-mod');
  var taglia = document.getElementById('diretta-taglia');
  if (mod && taglia) {
    mod.addEventListener('change', function () {
      Array.prototype.forEach.call(taglia.options, function (o) {
        if (o.value) o.hidden = o.getAttribute('data-modello') !== mod.value;
      });
      taglia.value = '';
    });
  }

  // Nuove richieste approvate: si aggiorna da solo, ma mai mentre si sta lavorando.
  setInterval(function () {
    if (document.hidden || occupato || sospesa || scelta || lettura || cerca.value.trim()) return;
    if (radice.querySelector('details[open]#diretta')) return;
    occupato = true;
    chiedi(window.location.pathname + window.location.search).then(function (r) {
      if (!scelta && !cerca.value.trim()) aggiorna(r.html, '');
    }).catch(function () {}).then(function () { occupato = false; });
  }, 60000);

  window.addEventListener('hashchange', function () {
    var h = window.location.hash.slice(1);
    if (h && h !== 'diretta' && h !== 'conferme') seleziona(h.replace(/^apri-/, ''), {scorri: true});
  });

  // Arrivo: ?cerca= dalla home, #apri-<persona> o #<persona> da mail e home, #diretta, #conferme.
  applica();
  var hash = window.location.hash.slice(1);
  if (hash === 'diretta' || hash === 'conferme') {
    var dettagli = document.getElementById(hash);
    if (dettagli) { dettagli.open = true; dettagli.scrollIntoView({block: 'center'}); }
  } else if (hash) {
    seleziona(hash.replace(/^apri-/, ''), {scorri: true});
  }
  if (!scelta && window.matchMedia('(pointer:fine)').matches && hash !== 'diretta' && hash !== 'conferme') cerca.focus();
})();
