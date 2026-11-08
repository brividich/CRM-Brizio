(function () {
  "use strict";
  var form = document.querySelector("[data-fai-form]");
  if (!form) return;

  var causale = form.querySelector("[data-fai-causale]");
  var regola = form.querySelector("[data-fai-regola]");
  var motivo = form.querySelector("[data-fai-motivo]");
  var piano = form.querySelector("[data-fai-piano]");
  var modulo = form.querySelector("[data-fai-modulo]");
  var numero = form.querySelector("[data-fai-numero]");
  var pn = form.querySelector('[name="part_number"]');

  function opzione(select) {
    return select.options[select.selectedIndex] || null;
  }

  function nomeTipo(valore) {
    return valore === "DELTA" ? "Delta FAI" : "FAI completo";
  }

  function aggiornaTipo() {
    var scelta = opzione(causale);
    var tipo = form.querySelector('[name="tipo"]:checked');
    if (!scelta || !scelta.value) {
      regola.textContent = "";
      motivo.hidden = true;
      return;
    }
    var diverso = Boolean(tipo) && tipo.value === "DELTA" && scelta.dataset.motivo === "1";
    motivo.hidden = !diverso;
    var testo = scelta.dataset.descrizione ? scelta.dataset.descrizione + ". " : "";
    regola.textContent = testo + (diverso
      ? "Qui la procedura prevede il FAI completo: puoi discostarti scrivendo il motivo."
      : "Proposto: " + nomeTipo(scelta.dataset.tipo) + ".");
  }

  function aggiornaPiano() {
    var scelta = opzione(piano);
    if (!scelta) return;
    var parti = [];
    if (scelta.dataset.modulo) parti.push("Si compila il " + scelta.dataset.modulo + ".");
    if (scelta.dataset.op) parti.push("Stato dell'OP nel gestionale: " + scelta.dataset.op + ".");
    modulo.textContent = parti.join(" ");
    numero.placeholder = scelta.dataset.auto === "1"
      ? "Vuoto: PFCN_" + (pn.value.trim() || "P/N") + "_…_A in automatico"
      : "Numero del piano";
  }

  causale.addEventListener("change", function () {
    // Cambiando motivo si riparte dalla proposta: il tipo diverso resta una scelta esplicita.
    var scelta = opzione(causale);
    var proposta = scelta && form.querySelector('[name="tipo"][value="' + scelta.dataset.tipo + '"]');
    if (proposta) proposta.checked = true;
    aggiornaTipo();
  });
  form.querySelectorAll('[name="tipo"]').forEach(function (radio) {
    radio.addEventListener("change", aggiornaTipo);
  });
  piano.addEventListener("change", aggiornaPiano);
  pn.addEventListener("input", aggiornaPiano);

  aggiornaTipo();
  aggiornaPiano();

  // OP: suggerimenti dall'elenco unico degli OP e riquadro dell'OP scelto.
  var op = form.querySelector("[data-fai-op]");
  var elenco = document.getElementById("fai-op-elenco");
  var scheda = form.querySelector("[data-fai-op-scheda]");
  if (!op || !elenco || !scheda) return;
  var attesa = null;
  var ultimo = op.value.trim();

  function chiedi(parametri) {
    return fetch(op.dataset.url + "?" + new URLSearchParams(parametri).toString(), {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }

  function el(tag, testo, classe) {
    var nodo = document.createElement(tag);
    if (testo) nodo.textContent = testo;
    if (classe) nodo.className = classe;
    return nodo;
  }

  function voce(etichetta, valore) {
    var span = el("span", etichetta + " ");
    span.appendChild(el("strong", valore));
    return span;
  }

  function plurale(n, singolare, plurale) {
    return n + " " + (n === 1 ? singolare : plurale);
  }

  function mostra(dati, titolo) {
    scheda.replaceChildren();
    if (!titolo || !dati || dati.disponibile === false) return;
    if (!dati.op) {
      scheda.appendChild(el("p", titolo + " non è nell'elenco OP di Gestione anomalie. Si salva lo stesso; per collegarlo, crealo con «+ Nuovo OP».", "fai-nota"));
      return;
    }
    var o = dati.op;
    var riga = el("p", "", "fai-op-riga");
    var nome = el(o.url_scheda ? "a" : "span", o.op, "fai-op-nome");
    if (o.url_scheda) { nome.href = o.url_scheda; nome.title = "Scheda dell'OP in Ordini di produzione"; }
    riga.appendChild(nome);
    if (o.pn) riga.appendChild(voce("P/N", o.pn));
    if (o.capocommessa) riga.appendChild(voce("Capocommessa", o.capocommessa));
    if (o.car) riga.appendChild(voce("CAR", o.car));
    if (o.stato) riga.appendChild(el("span", o.stato, "ts-chip soft"));
    var a = o.anomalie || { totale: 0, aperte: 0 };
    var link = el("a", (a.totale
      ? plurale(a.totale, "anomalia", "anomalie") + (a.aperte ? ", " + plurale(a.aperte, "aperta", "aperte") : "")
      : "Nessuna anomalia") + " in Gestione anomalie");
    link.href = o.url_anomalie;
    riga.appendChild(link);
    scheda.appendChild(riga);
    if (o.pn_diverso) {
      scheda.appendChild(el("p", "L'OP è del P/N " + o.pn + ", diverso da quello del FAI.", "fai-nota fai-op-avviso"));
    }
  }

  function controlla() {
    var titolo = op.value.trim();
    if (titolo === ultimo) return;
    ultimo = titolo;
    if (!titolo) { mostra(null, ""); return; }
    chiedi({ op: titolo, pn: pn.value.trim() }).then(function (dati) {
      if (op.value.trim() === titolo) mostra(dati, titolo);
    });
  }

  op.addEventListener("input", function () {
    clearTimeout(attesa);
    var testo = op.value.trim();
    // Scelto un suggerimento: il valore coincide con una voce dell'elenco.
    if (Array.prototype.some.call(elenco.options, function (o) { return o.value === testo; })) {
      controlla();
      return;
    }
    if (testo.length < 2) return;
    attesa = setTimeout(function () {
      chiedi({ q: testo }).then(function (dati) {
        if (!dati || op.value.trim() !== testo) return;
        elenco.replaceChildren();
        (dati.risultati || []).forEach(function (r) {
          var opzione = document.createElement("option");
          opzione.value = r.op;
          opzione.label = [r.pn, r.stato].filter(Boolean).join(" · ");
          elenco.appendChild(opzione);
        });
      });
    }, 250);
  });
  op.addEventListener("change", controlla);
  // «+ Nuovo OP» dal pannello laterale: l'OP creato va nel campo, col P/N del FAI.
  var apriNuovo = form.querySelector("[data-fai-nuovo-op]");
  if (apriNuovo) {
    apriNuovo.addEventListener("click", function () { apriNuovo.dataset.pn = pn.value.trim(); }, true);
  }
  document.addEventListener("op:creato", function (e) {
    op.value = e.detail.op;
    ultimo = null;
    controlla();
  });
  pn.addEventListener("change", function () { ultimo = null; controlla(); });
})();
