/* «Attività e incontro»: il terzo passo del kickoff in una pagina.

   - Attività a righe; ogni riga può avere una nota (finisce nella mail) e può
     essere collegata a un'altra («viene dopo»): si trascina l'anello sulla riga
     che viene prima, oppure si clicca l'anello e poi la riga.
   - L'incontro è facoltativo. L'ordine del giorno prende da solo le attività
     segnate «All'ODG»; gli altri punti si aggiungono e si ordinano trascinando.
   - Secondo tempo: quando avvisare (subito o con la minuta) e «chi riceve cosa».

   I dati veri sono i campi del form: al salvataggio decide il server
   (views/pianifica.py). Senza questo file la pagina mostra tutto in fila e si
   invia lo stesso. */
(function () {
  'use strict';

  var form = document.getElementById('ka-form');
  if (!form) return;

  var dati = {};
  try { dati = JSON.parse(document.getElementById('ka-dati').textContent || '{}'); } catch (e) { dati = {}; }
  var persone = {};
  (dati.persone || []).forEach(function (p) { persone[String(p.id)] = p; });
  var proposti = dati.proposti || [];
  var ordine = (dati.ordine || []).slice();

  function q(sel, root) { return (root || form).querySelector(sel); }
  function qa(sel, root) { return Array.prototype.slice.call((root || form).querySelectorAll(sel)); }
  function el(tag, attrs, figli) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] === true) e.setAttribute(k, '');
      else if (attrs[k] !== false && attrs[k] != null) e.setAttribute(k, attrs[k]);
    });
    (figli || []).forEach(function (f) { if (f) e.appendChild(typeof f === 'string' ? document.createTextNode(f) : f); });
    return e;
  }
  function dataIt(iso) {
    if (!iso) return '';
    var d = new Date(iso + 'T00:00:00');
    return isNaN(d) ? iso : d.toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'short' });
  }

  var righeBox = q('[data-ka-rows]');
  var campoIncontro = q('[data-ka-incontro]');
  var campoOrdine = q('[data-ka-ordine]');
  var stato = q('[data-ka-stato]');
  var contatore = 0;

  function conIncontro() { return campoIncontro.value === '1'; }
  function righe() { return qa('[data-ka-row]', righeBox); }
  function campo(riga, nome) { return riga.querySelector('[name="' + nome + '"]'); }
  function leggi(riga) {
    return {
      riga: riga,
      chiave: campo(riga, 'att_chiave').value,
      titolo: campo(riga, 'att_titolo').value.trim(),
      resp: campo(riga, 'att_resp').value,
      scadenza: campo(riga, 'att_scadenza').value,
      nota: campo(riga, 'att_note').value.trim(),
      odg: campo(riga, 'att_odg').value === '1',
      dopo: campo(riga, 'att_dopo').value
    };
  }
  function valide() { return righe().map(leggi).filter(function (a) { return a.titolo; }); }
  function perChiave(chiave) {
    return righe().filter(function (r) { return campo(r, 'att_chiave').value === chiave; })[0] || null;
  }

  /* ── Collegamento fra attività ─────────────────────────────────────── */
  var origine = null; // la riga che «viene dopo», in attesa della riga che viene prima

  function chiudeIlGiro(successiva, precedente) {
    // Risale da «precedente»: se arriva a «successiva», il legame chiuderebbe un giro.
    var visto = {}, cursore = precedente;
    while (cursore) {
      if (cursore === successiva) return true;
      var chiave = campo(cursore, 'att_chiave').value;
      if (visto[chiave]) return false;
      visto[chiave] = true;
      cursore = perChiave(campo(cursore, 'att_dopo').value);
    }
    return false;
  }
  function collega(successiva, precedente) {
    if (!successiva || !precedente || successiva === precedente) return;
    if (chiudeIlGiro(successiva, precedente)) {
      avviso('Non posso collegarle: le due attività si aspetterebbero a vicenda.');
      return;
    }
    campo(successiva, 'att_dopo').value = campo(precedente, 'att_chiave').value;
    segnaModifica();
    aggiorna();
  }
  function fineScelta() {
    origine = null;
    righeBox.classList.remove('is-scelta');
    righe().forEach(function (r) { r.classList.remove('is-origine', 'is-bersaglio', 'is-trascinata'); });
    q('[data-ka-scegli]').hidden = true;
  }
  function inizioScelta(riga) {
    if (origine === riga) { fineScelta(); return; }
    fineScelta();
    origine = riga;
    riga.classList.add('is-origine');
    righeBox.classList.add('is-scelta');
    q('[data-ka-scegli]').hidden = false;
  }
  function disegnaCollegamento(riga) {
    var chip = riga.querySelector('[data-ka-dopo]');
    var prima = perChiave(campo(riga, 'att_dopo').value);
    if (!prima) { campo(riga, 'att_dopo').value = ''; chip.hidden = true; return; }
    var titolo = campo(prima, 'att_titolo').value.trim();
    chip.querySelector('[data-ka-dopo-testo]').textContent = '↳ dopo ' + (titolo ? '«' + titolo + '»' : 'un\'attività ancora senza titolo');
    chip.hidden = false;
  }

  /* ── Righe ─────────────────────────────────────────────────────────── */
  function segnaModifica() {
    // L'avviso «modifiche non salvate» conta i campi con name: i pulsanti no.
    campoOrdine.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function lega(riga) {
    var titolo = campo(riga, 'att_titolo');
    titolo.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      campo(aggiungi(), 'att_titolo').focus();
    });
    riga.querySelector('[data-ka-odg]').addEventListener('click', function () {
      var c = campo(riga, 'att_odg');
      c.value = c.value === '1' ? '0' : '1';
      segnaModifica();
      aggiorna();
    });
    var notaBtn = riga.querySelector('[data-ka-nota-btn]');
    notaBtn.addEventListener('click', function () {
      var nota = campo(riga, 'att_note');
      // Una nota scritta non si nasconde: per toglierla la si svuota.
      nota.hidden = nota.hidden ? false : !nota.value.trim();
      if (!nota.hidden) nota.focus();
      aggiorna();
    });
    riga.querySelector('[data-ka-x]').addEventListener('click', function () {
      if (origine) fineScelta();
      if (righe().length > 1) riga.remove();
      else {
        qa('input[type="text"], input[type="date"], textarea', riga).forEach(function (i) { i.value = ''; });
        imposta(campo(riga, 'att_resp'), '');
        campo(riga, 'att_dopo').value = '';
        campo(riga, 'att_note').hidden = true;
      }
      segnaModifica();
      aggiorna();
    });
    riga.querySelector('[data-ka-scollega]').addEventListener('click', function () {
      campo(riga, 'att_dopo').value = '';
      segnaModifica();
      aggiorna();
    });

    var anello = riga.querySelector('[data-ka-link]');
    anello.addEventListener('click', function (e) { e.stopPropagation(); inizioScelta(riga); });
    anello.addEventListener('dragstart', function (e) {
      fineScelta();
      origine = riga;
      riga.classList.add('is-trascinata');
      righeBox.classList.add('is-scelta');
      e.dataTransfer.effectAllowed = 'link';
      try { e.dataTransfer.setData('text/plain', campo(riga, 'att_chiave').value); } catch (err) { /* vecchi browser */ }
    });
    anello.addEventListener('dragend', fineScelta);
    riga.addEventListener('dragover', function (e) {
      if (!origine || origine === riga) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'link';
      riga.classList.add('is-bersaglio');
    });
    riga.addEventListener('dragleave', function () { riga.classList.remove('is-bersaglio'); });
    riga.addEventListener('drop', function (e) {
      if (!origine || origine === riga) return;
      e.preventDefault();
      var successiva = origine;
      fineScelta();
      collega(successiva, riga);
    });
    // Modalità «scegli»: un clic sulla riga la indica come quella che viene prima.
    riga.addEventListener('click', function (e) {
      if (!origine || origine === riga || !righeBox.classList.contains('is-scelta')) return;
      if (riga.classList.contains('is-trascinata')) return;
      e.preventDefault();
      var successiva = origine;
      fineScelta();
      collega(successiva, riga);
    }, true);
  }
  /* Le tendine lunghe sono rese ricercabili da Tom Select (tomselect-init.js):
     il valore si legge dal <select>, ma per cambiarlo da codice va detto a lui. */
  function imposta(select, valore) {
    if (select.tomselect) select.tomselect.setValue(valore, true);
    else select.value = valore;
  }
  function aggiungi() {
    var tutte = righe();
    var ultima = tutte[tutte.length - 1];
    var nuova = q('[data-ka-riga-modello]').content.firstElementChild.cloneNode(true);
    campo(nuova, 'att_chiave').value = 'k' + Date.now().toString(36) + (++contatore);
    campo(nuova, 'att_odg').value = conIncontro() ? '1' : '0';
    // Il responsabile della riga sopra resta proposto: spesso è lo stesso.
    if (ultima) campo(nuova, 'att_resp').value = campo(ultima, 'att_resp').value;
    nuova.setAttribute('data-chiave', campo(nuova, 'att_chiave').value);
    righeBox.appendChild(nuova);
    // Stesso segnale di un frammento HTMX: la tendina nuova diventa ricercabile.
    nuova.dispatchEvent(new CustomEvent('htmx:afterSettle', { bubbles: true, detail: { elt: nuova } }));
    lega(nuova);
    aggiorna();
    return nuova;
  }

  /* ── Partecipanti ──────────────────────────────────────────────────── */
  var partBox = q('[data-ka-part]');
  function convocati() { return qa('input[name="inc_part"]', partBox).map(function (i) { return i.value; }); }
  function chip(id) {
    var p = persone[String(id)];
    if (!p) return null;
    return el('span', { class: 'ka-chip', 'data-ka-chip': id }, [
      el('input', { type: 'hidden', name: 'inc_part', value: id }), p.nome,
      p.team ? el('small', { text: ' team' }) : null,
      el('button', { type: 'button', 'data-ka-chip-x': true, title: 'Togli', 'aria-label': 'Togli ' + p.nome, text: '×' })
    ]);
  }
  function disegnaPartecipanti() {
    qa('.ka-chip.is-auto', partBox).forEach(function (c) { c.remove(); });
    var gia = convocati();
    var visti = {};
    valide().forEach(function (a) {
      if (!a.resp || gia.indexOf(a.resp) !== -1 || visti[a.resp] || !persone[a.resp]) return;
      visti[a.resp] = true;
      partBox.appendChild(el('span', { class: 'ka-chip is-auto', title: 'Convocato perché ha un\'attività' }, [
        persone[a.resp].nome, el('small', { text: ' ha un\'attività' })
      ]));
    });
  }
  partBox.addEventListener('click', function (e) {
    var x = e.target.closest('[data-ka-chip-x]');
    if (!x) return;
    x.closest('.ka-chip').remove();
    segnaModifica();
    aggiorna();
  });
  var partAdd = q('[data-ka-part-add]');
  partAdd.addEventListener('change', function () {
    var id = partAdd.value;
    imposta(partAdd, '');
    if (!id || convocati().indexOf(id) !== -1) return;
    var c = chip(id);
    if (c) partBox.appendChild(c);
    segnaModifica();
    aggiorna();
  });

  /* ── Ordine del giorno ─────────────────────────────────────────────── */
  var lista = q('[data-ka-odg-lista]');
  var trascinato = -1;

  function allineaOrdine() {
    var inOdg = {};
    valide().forEach(function (a) { if (a.odg) inOdg[a.chiave] = a; });
    ordine = ordine.filter(function (v) {
      if ('att' in v) return !!inOdg[v.att];
      if ('pre' in v) return proposti[v.pre] !== undefined;
      return !!String(v.punto || '').trim();
    });
    var presenti = {};
    ordine.forEach(function (v) { if ('att' in v) presenti[v.att] = true; });
    Object.keys(inOdg).forEach(function (k) { if (!presenti[k]) ordine.push({ att: k }); });
    campoOrdine.value = JSON.stringify(ordine);
    return inOdg;
  }
  function sposta(da, a) {
    if (da === a || da < 0 || a < 0 || da >= ordine.length || a >= ordine.length) return;
    ordine.splice(a, 0, ordine.splice(da, 1)[0]);
    segnaModifica();
    aggiorna();
  }
  function disegnaOdg() {
    var inOdg = allineaOrdine();
    lista.replaceChildren();
    if (!ordine.length) {
      lista.appendChild(el('li', { class: 'is-vuoto', text: 'Ancora nessun punto. Segna un\'attività «All\'ODG», aggiungi un punto o carica un modello.' }));
      return;
    }
    ordine.forEach(function (v, i) {
      var titolo, sotto;
      if ('att' in v) {
        var a = inOdg[v.att];
        titolo = a.titolo;
        sotto = [el('span', { class: 'ka-badge', text: 'Attività' }),
          (a.resp && persone[a.resp] ? persone[a.resp].nome : 'Responsabile da decidere') + (a.scadenza ? ' · entro ' + dataIt(a.scadenza) : '') + ' · da confermare'];
      } else if ('pre' in v) {
        titolo = proposti[v.pre];
        sotto = ['Tappa del Percorso della commessa'];
      } else {
        titolo = v.punto;
        sotto = ['Punto di discussione'];
      }
      var li = el('li', { draggable: 'true' }, [
        el('span', { class: 'ka-odg-n', text: String(i + 1) }),
        el('div', { class: 'ka-odg-t' }, [el('strong', { text: titolo }), el('div', {}, sotto)]),
        el('div', { class: 'ka-odg-mv' }, [
          el('button', { type: 'button', class: 'ka-icona', 'aria-label': 'Sposta su', text: '↑', disabled: i === 0, onclick: function () { sposta(i, i - 1); } }),
          el('button', { type: 'button', class: 'ka-icona', 'aria-label': 'Sposta giù', text: '↓', disabled: i === ordine.length - 1, onclick: function () { sposta(i, i + 1); } }),
          el('button', { type: 'button', class: 'ka-icona ka-x', 'aria-label': 'att' in v ? 'Togli dall\'ordine del giorno' : 'Elimina il punto', text: '×',
            onclick: function () {
              if ('att' in v) campo(inOdg[v.att].riga, 'att_odg').value = '0';
              else ordine.splice(i, 1);
              segnaModifica();
              aggiorna();
            } })
        ])
      ]);
      li.addEventListener('dragstart', function (e) {
        trascinato = i;
        li.classList.add('is-trascinata');
        e.dataTransfer.effectAllowed = 'move';
        try { e.dataTransfer.setData('text/plain', String(i)); } catch (err) { /* vecchi browser */ }
      });
      li.addEventListener('dragend', function () {
        trascinato = -1;
        qa('li', lista).forEach(function (x) { x.classList.remove('is-trascinata', 'is-bersaglio'); });
      });
      li.addEventListener('dragover', function (e) {
        if (trascinato < 0 || trascinato === i) return;
        e.preventDefault();
        li.classList.add('is-bersaglio');
      });
      li.addEventListener('dragleave', function () { li.classList.remove('is-bersaglio'); });
      li.addEventListener('drop', function (e) {
        if (trascinato < 0) return;
        e.preventDefault();
        var da = trascinato;
        trascinato = -1;
        sposta(da, i);
      });
      lista.appendChild(li);
    });
  }
  function aggiungiPunto(titolo) {
    titolo = String(titolo || '').trim().slice(0, 200);
    if (!titolo) return false;
    var gia = ordine.some(function (v) {
      var t = 'pre' in v ? proposti[v.pre] : v.punto;
      return t && t.toLowerCase() === titolo.toLowerCase();
    });
    if (gia) return false;
    ordine.push({ punto: titolo });
    return true;
  }
  var nuovoPunto = q('[data-ka-odg-nuovo]');
  function daCampoNuovo() {
    if (aggiungiPunto(nuovoPunto.value)) { nuovoPunto.value = ''; segnaModifica(); aggiorna(); }
    nuovoPunto.focus();
  }
  q('[data-ka-odg-add]').addEventListener('click', daCampoNuovo);
  nuovoPunto.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); daCampoNuovo(); } });
  /* Tappe del Percorso ancora da assegnare: facoltative, si aggiungono con un clic. */
  var tappe = q('[data-ka-tappe]');
  function tappeMancanti() {
    var presenti = {};
    ordine.forEach(function (v) { if ('pre' in v) presenti[v.pre] = true; });
    return proposti.map(function (_t, i) { return i; }).filter(function (i) { return !presenti[i]; });
  }
  function disegnaTappe() {
    var n = tappeMancanti().length;
    tappe.hidden = n === 0;
    tappe.textContent = '+ Tappe del Percorso (' + n + ')';
    tappe.title = 'Aggiungi all\'ordine del giorno le tappe del Percorso non ancora presenti';
  }
  tappe.addEventListener('click', function () {
    tappeMancanti().forEach(function (i) { ordine.push({ pre: i }); });
    segnaModifica();
    aggiorna();
  });
  var modello = q('[data-ka-modello]');
  (dati.modelli || []).forEach(function (m, i) {
    if (m.punti && m.punti.length) modello.appendChild(el('option', { value: i, text: m.nome + ' (' + m.punti.length + ' punti)' }));
  });
  modello.hidden = modello.options.length < 2;
  modello.addEventListener('change', function () {
    var m = (dati.modelli || [])[modello.value];
    imposta(modello, '');
    if (!m) return;
    m.punti.forEach(aggiungiPunto);
    segnaModifica();
    aggiorna();
  });

  /* ── Riepilogo, barra, «chi riceve cosa» ───────────────────────────── */
  var fase = 'compila';

  function avviso(testo) {
    stato.textContent = testo;
    stato.classList.add('is-ko');
  }
  function carichi() {
    var c = {};
    valide().forEach(function (a) { if (a.resp) c[a.resp] = (c[a.resp] || 0) + 1; });
    return c;
  }
  function coinvolti() {
    var ids = conIncontro() ? convocati() : [];
    Object.keys(carichi()).forEach(function (id) { if (ids.indexOf(id) === -1) ids.push(id); });
    return ids.filter(function (id) { return persone[id]; });
  }
  function invio() {
    var scelto = q('input[name="invio"]:checked');
    return conIncontro() && scelto && scelto.value === 'minuta' ? 'minuta' : 'subito';
  }
  function disegnaRiepilogo() {
    var att = valide();
    var senzaResp = att.filter(function (a) { return !a.resp; }).length;
    var collegate = att.filter(function (a) { return a.dopo; }).length;
    var r = q('[data-ka-riepilogo]');
    r.replaceChildren();
    function riga(k, v, warn) { r.append(el('dt', { text: k }), el('dd', { text: v, class: warn ? 'is-warn' : '' })); }
    riga('Attività', String(att.length));
    riga('Senza responsabile', String(senzaResp), senzaResp > 0);
    riga('Collegate', collegate ? String(collegate) : 'nessuna');
    riga('Con una nota', String(att.filter(function (a) { return a.nota; }).length));
    if (conIncontro()) {
      var data = q('#ka-data').value, ora = q('#ka-ora').value, sala = q('#ka-sala');
      riga('Incontro', data ? dataIt(data) + (ora ? ' · ' + ora : '') : 'data da scegliere', !data);
      riga('Sala', sala.value ? sala.options[sala.selectedIndex].text : 'nessuna');
      riga('Ordine del giorno', ordine.length + (ordine.length === 1 ? ' punto' : ' punti'));
    } else {
      riga('Incontro', 'nessuno');
    }

    var c = carichi(), box = q('[data-ka-persone]');
    box.replaceChildren();
    var ids = coinvolti();
    if (!ids.length) box.appendChild(el('li', { class: 'is-vuoto', text: 'Ancora nessuno.' }));
    ids.forEach(function (id) {
      box.appendChild(el('li', {}, [persone[id].nome, el('span', { text: c[id] ? c[id] + ' attività' : 'solo incontro' })]));
    });

    var niente = !att.length && !conIncontro();
    var senzaData = conIncontro() && !q('#ka-data').value;
    var testo;
    if (niente) testo = 'Scrivi almeno un\'attività, oppure convoca un incontro.';
    else if (senzaData) testo = 'Manca la data dell\'incontro.';
    else if (fase === 'invio') {
      testo = invio() === 'minuta' ? 'Nessun avviso sulle attività fino alla minuta dell\'incontro.'
        : 'Gli avvisi partono alla conferma.' + (senzaResp ? ' ' + senzaResp + ' attività senza responsabile non avvisano nessuno.' : '');
    } else if (senzaResp) {
      testo = senzaResp + ' attività senza responsabile' + (conIncontro() ? ': si decide in riunione.' : ': nessuno riceverà l\'avviso.');
    } else testo = 'Niente viene inviato prima della conferma. Manca solo decidere quando avvisare.';
    stato.textContent = testo;
    stato.classList.toggle('is-ko', niente || senzaData || (fase === 'compila' && senzaResp > 0));
    q('[data-ka-avanti]').disabled = niente || senzaData;
    return { niente: niente, senzaData: senzaData };
  }
  function disegnaChi() {
    var c = carichi(), part = conIncontro() ? convocati() : [], corpo = q('[data-ka-chi]');
    var convocazione = conIncontro() && q('input[name="invia_convocazione"]').checked;
    valide().forEach(function (a) { if (a.resp && part.indexOf(a.resp) === -1 && conIncontro()) part.push(a.resp); });
    corpo.replaceChildren();
    coinvolti().forEach(function (id) {
      var ora = [], dopo = [], invitato = part.indexOf(id) !== -1;
      if (invitato && convocazione) ora.push('Convocazione con ordine del giorno');
      if (c[id] && invio() === 'subito' && String(dati.io) !== id) ora.push('Avviso e mail: ' + c[id] + ' attività, con le note');
      if (c[id] && invio() === 'subito' && String(dati.io) === id) ora.push('Niente avviso: le hai assegnate tu');
      if (invitato) dopo.push('Minuta' + (c[id] ? ' con le sue ' + c[id] + ' attività' : ' con le attività assegnate'));
      corpo.appendChild(el('tr', {}, [
        el('td', {}, [el('strong', { text: persone[id].nome })]),
        el('td', { class: ora.length ? '' : 'is-niente', text: ora.join(' + ') || 'Niente' }),
        el('td', { class: dopo.length ? '' : 'is-niente', text: dopo.join(' + ') || 'Niente' })
      ]));
    });
    q('[data-ka-chi-card]').hidden = !coinvolti().length;
    var minuta = q('[data-ka-scelta-minuta] input');
    minuta.disabled = !conIncontro();
    if (!conIncontro() && minuta.checked) q('input[name="invio"][value="subito"]').checked = true;
    q('[data-ka-minuta-nota]').textContent = conIncontro() ? '' : 'Disponibile solo con un incontro.';
    q('[data-ka-conv]').hidden = !conIncontro();
  }
  function aggiorna() {
    var si = conIncontro();
    righe().forEach(function (r) {
      var btn = r.querySelector('[data-ka-odg]'), c = campo(r, 'att_odg');
      btn.disabled = !si;
      btn.setAttribute('aria-pressed', String(si && c.value === '1'));
      var nota = campo(r, 'att_note'), notaBtn = r.querySelector('[data-ka-nota-btn]');
      notaBtn.classList.toggle('is-on', !nota.hidden || !!nota.value.trim());
      notaBtn.setAttribute('aria-expanded', String(!nota.hidden));
      disegnaCollegamento(r);
    });
    qa('[data-ka-seg]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.getAttribute('data-ka-seg') === campoIncontro.value)); });
    q('[data-ka-incontro-si]').hidden = !si;
    q('[data-ka-incontro-no]').hidden = si;
    q('[data-ka-odg-card]').hidden = !si;
    disegnaPartecipanti();
    disegnaOdg();
    disegnaTappe();
    disegnaChi();
    return disegnaRiepilogo();
  }
  function mostraFase(nuova, senzaScorrere) {
    fase = nuova;
    qa('[data-ka-fase]').forEach(function (f) { f.hidden = f.getAttribute('data-ka-fase') !== nuova; });
    q('[data-ka-avanti]').hidden = nuova !== 'compila';
    q('[data-ka-torna]').hidden = nuova !== 'invio';
    q('[data-ka-conferma]').hidden = nuova !== 'invio';
    q('[data-ka-annulla]').hidden = nuova !== 'compila';
    aggiorna();
    if (!senzaScorrere) form.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }

  /* ── Eventi di pagina ──────────────────────────────────────────────── */
  righe().forEach(lega);
  q('[data-ka-add]').addEventListener('click', function () { campo(aggiungi(), 'att_titolo').focus(); });
  q('[data-ka-scegli-annulla]').addEventListener('click', fineScelta);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && origine) fineScelta(); });
  qa('[data-ka-seg]').forEach(function (b) {
    b.addEventListener('click', function () {
      campoIncontro.value = b.getAttribute('data-ka-seg');
      segnaModifica();
      aggiorna();
    });
  });
  q('[data-ka-avanti]').addEventListener('click', function () {
    var esito = aggiorna();
    if (esito.niente || esito.senzaData) return;
    mostraFase('invio');
  });
  q('[data-ka-torna]').addEventListener('click', function () { mostraFase('compila'); });
  form.addEventListener('input', aggiorna);
  form.addEventListener('change', function (e) { if (e.target !== campoOrdine) aggiorna(); });
  form.addEventListener('submit', function () { allineaOrdine(); });

  mostraFase('compila', true);
})();
