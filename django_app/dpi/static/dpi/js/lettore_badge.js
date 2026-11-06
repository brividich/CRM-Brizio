/* Banco consegne DPI · lettore di badge seriale (Web Serial: Chrome o Edge in https).
 * Il lettore invia da solo a ogni passaggio, a 19200 baud:
 *   STX (02) + cifre ASCII + ETX (03) + XOR dei byte da STX a ETX + CR (0D).
 * Il messaggio va al server, che lo verifica e dice di chi e' il badge: alla pagina il numero non serve.
 */
(function () {
  "use strict";

  var VELOCITA = 19200;
  var SILICON_LABS = 0x10C4;
  var STX = 0x02, ETX = 0x03, CR = 0x0D;
  var MAX_MESSAGGIO = 64;
  var PAUSA_STESSO_BADGE_MS = 2000;

  // Restituisce i messaggi completi e validi, {codice, messaggio}: quelli rovinati si scartano.
  function creaAnalizzatore() {
    var buf = [];

    function cifre(messaggio) {
      var finale = messaggio.length - 3;
      if (finale < 2 || messaggio[finale] !== ETX) return null;
      var controllo = 0;
      for (var i = 0; i <= finale; i++) controllo ^= messaggio[i];
      if (controllo !== messaggio[finale + 1]) return null;
      var codice = "";
      for (var j = 1; j < finale; j++) {
        if (messaggio[j] < 0x30 || messaggio[j] > 0x39) return null;
        codice += String.fromCharCode(messaggio[j]);
      }
      return codice;
    }

    return function (byte) {
      var letti = [];
      for (var i = 0; i < byte.length; i++) {
        var b = byte[i];
        if (!buf.length && b !== STX) continue;
        buf.push(b);
        if (buf.length > MAX_MESSAGGIO) { buf = []; continue; }
        // CR puo' essere anche il byte di controllo: conta solo dopo ETX e controllo.
        if (b === CR && buf.length >= 3 && buf[buf.length - 3] === ETX) {
          var codice = cifre(buf);
          var messaggio = buf.map(function (x) { return (x < 16 ? "0" : "") + x.toString(16); }).join("");
          buf = [];
          if (codice) letti.push({codice: codice, messaggio: messaggio});
        }
      }
      return letti;
    };
  }

  function avvia(opzioni) {
    var bottone = opzioni.bottone, stato = opzioni.stato;
    var porta = null, lettore = null, chiudendo = false;
    var ultimo = "", ultimoQuando = 0;

    function mostra(testo, conErrore) {
      stato.textContent = testo;
      stato.classList.toggle("errore", !!conErrore);
    }

    function aspetto(collegato) {
      bottone.textContent = collegato ? "Scollega lettore" : "Collega lettore badge";
      if (opzioni.suStato) opzioni.suStato(collegato);
    }

    function consegna(letto) {
      var codice = letto.codice;
      var ora = Date.now();
      // Il badge lasciato sul lettore si ripete: vale una lettura sola.
      if (codice === ultimo && ora - ultimoQuando < PAUSA_STESSO_BADGE_MS) { ultimoQuando = ora; return; }
      ultimo = codice;
      ultimoQuando = ora;
      opzioni.suLettura(letto.messaggio);
    }

    function leggi() {
      var analizza = creaAnalizzatore();
      lettore = porta.readable.getReader();
      function giro() {
        return lettore.read().then(function (r) {
          if (r.done) return;
          analizza(r.value).forEach(consegna);
          return giro();
        });
      }
      return giro();
    }

    function chiudi() {
      var p = porta, l = lettore;
      porta = null;
      lettore = null;
      var fatto = l ? l.cancel().catch(function () {}).then(function () { l.releaseLock(); }) : Promise.resolve();
      return fatto.then(function () { return p ? p.close() : null; }).catch(function () {});
    }

    function apri(scelta) {
      return scelta.open({baudRate: VELOCITA}).then(function () {
        porta = scelta;
        aspetto(true);
        mostra("Lettore pronto: passa il badge.");
        leggi().catch(function () {
          if (!chiudendo) mostra("Collegamento con il lettore interrotto.", true);
        }).then(function () {
          if (chiudendo) return;
          chiudi();
          aspetto(false);
        });
      }).catch(function (e) {
        aspetto(false);
        if (e && e.name === "InvalidStateError") {
          mostra("Lettore già aperto in questa pagina.", true);
        } else {
          mostra("Lettore occupato: chiudi le altre schede o i programmi che lo usano, poi riprova.", true);
        }
      });
    }

    bottone.addEventListener("click", function () {
      if (porta) {
        chiudendo = true;
        chiudi().then(function () {
          chiudendo = false;
          aspetto(false);
          mostra("Lettore scollegato.");
        });
        return;
      }
      navigator.serial.requestPort({filters: [{usbVendorId: SILICON_LABS}]}).then(apri).catch(function (e) {
        // Finestra chiusa senza scegliere: nessun errore da segnalare.
        if (!e || e.name !== "NotFoundError") mostra("Non riesco a collegare il lettore.", true);
      });
    });

    // Lettore gia' autorizzato: si ricollega da solo, anche quando si rimette il cavo.
    function ricollega() {
      if (porta) return;
      navigator.serial.getPorts().then(function (porte) {
        var nostre = porte.filter(function (p) { return p.getInfo().usbVendorId === SILICON_LABS; });
        if (nostre.length === 1) apri(nostre[0]);
      }).catch(function () {});
    }

    navigator.serial.addEventListener("connect", ricollega);
    navigator.serial.addEventListener("disconnect", function (e) {
      if (porta && e.target === porta) {
        chiudi();
        aspetto(false);
        mostra("Lettore scollegato: controlla il cavo.", true);
      }
    });

    aspetto(false);
    ricollega();
  }

  window.LettoreBadge = {
    disponibile: function () { return !!navigator.serial; },
    creaAnalizzatore: creaAnalizzatore,
    avvia: avvia,
  };
})();
