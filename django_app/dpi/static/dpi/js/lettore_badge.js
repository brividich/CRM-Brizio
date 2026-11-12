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
    var inApertura = false, scollegatoAMano = false, ceduta = false;
    var tentativi = 0, timerRiprova = null, chiusura = Promise.resolve();
    // Il lettore lo apre una scheda alla volta: va a quella in uso, le altre lo cedono.
    var canale = window.BroadcastChannel ? new BroadcastChannel("dpi-lettore-badge") : null;

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
      chiusura = chiusura.then(function () { return fatto; }).then(function () { return p ? p.close() : null; }).catch(function () {});
      return chiusura;
    }

    function rilascia(testo) {
      if (!porta) return Promise.resolve();
      chiudendo = true;
      return chiudi().then(function () {
        chiudendo = false;
        aspetto(false);
        if (testo) mostra(testo);
      });
    }

    function fermaRiprova() {
      clearTimeout(timerRiprova);
      timerRiprova = null;
    }

    function riprova() {
      fermaRiprova();
      if (scollegatoAMano) return;
      // Subito dopo il cambio scheda la porta si libera in un attimo; poi si controlla con calma.
      timerRiprova = setTimeout(ricollega, tentativi < 5 ? 600 : 3000);
      tentativi++;
    }

    function apri(scelta) {
      if (porta || inApertura) return Promise.resolve();
      inApertura = true;
      return chiusura.then(function () { return scelta.open({baudRate: VELOCITA}); }).then(function () {
        inApertura = false;
        porta = scelta;
        tentativi = 0;
        fermaRiprova();
        aspetto(true);
        mostra("Lettore pronto: passa il badge.");
        leggi().catch(function () {
          if (!chiudendo && porta === scelta) mostra("Collegamento con il lettore interrotto.", true);
        }).then(function () {
          if (chiudendo || porta !== scelta) return;
          chiudi();
          aspetto(false);
          riprova();
        });
        if (document.hidden) rilascia();
      }).catch(function () {
        inApertura = false;
        aspetto(false);
        mostra("Lettore in uso in un'altra scheda o in un altro programma: riprovo da solo.");
        riprova();
      });
    }

    // Lettore gia' autorizzato su questo indirizzo: si collega da solo, senza chiedere.
    function ricollega() {
      fermaRiprova();
      if (porta || inApertura || scollegatoAMano || document.hidden || (ceduta && !document.hasFocus())) return;
      navigator.serial.getPorts().then(function (porte) {
        var nostre = porte.filter(function (p) { return p.getInfo().usbVendorId === SILICON_LABS; });
        if (nostre.length === 1) { apri(nostre[0]); return; }
        aspetto(false);
        mostra(nostre.length
          ? "Più lettori collegati: clicca «Collega lettore badge» e scegli quale usare."
          : "Lettore non collegato o non ancora autorizzato su questo indirizzo: clicca «Collega lettore badge».");
      }).catch(function () {});
    }

    function chiediLaPorta() {
      if (canale && document.hasFocus()) canale.postMessage("cedi");
    }

    // Questa scheda torna in uso.
    function attiva() {
      if (document.hidden) return;
      ceduta = false;
      tentativi = 0;
      if (porta || scollegatoAMano) return;
      chiediLaPorta();
      ricollega();
    }

    if (canale) {
      canale.addEventListener("message", function () {
        if (!porta || document.hasFocus()) return;
        ceduta = true;
        rilascia("Lettore in uso in un'altra scheda: torna qui per usarlo.");
      });
    }

    bottone.addEventListener("click", function () {
      if (porta) {
        scollegatoAMano = true;
        fermaRiprova();
        rilascia("Lettore scollegato.");
        return;
      }
      scollegatoAMano = false;
      ceduta = false;
      tentativi = 0;
      chiediLaPorta();
      navigator.serial.requestPort({filters: [{usbVendorId: SILICON_LABS}]}).then(apri).catch(function (e) {
        // Finestra chiusa senza scegliere: nessun errore da segnalare.
        if (!e || e.name !== "NotFoundError") mostra("Non riesco a collegare il lettore.", true);
      });
    });

    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        fermaRiprova();
        rilascia("Lettore in pausa: questa scheda non è in uso.");
      } else {
        attiva();
      }
    });
    window.addEventListener("focus", attiva);
    window.addEventListener("pagehide", function () { if (porta) rilascia(); });
    window.addEventListener("pageshow", function (e) { if (e.persisted) attiva(); });

    navigator.serial.addEventListener("connect", attiva);
    navigator.serial.addEventListener("disconnect", function (e) {
      if (porta && e.target === porta) {
        chiudi();
        aspetto(false);
        mostra("Lettore scollegato: controlla il cavo.", true);
      }
    });

    aspetto(false);
    attiva();
  }

  window.LettoreBadge = {
    disponibile: function () { return !!navigator.serial; },
    creaAnalizzatore: creaAnalizzatore,
    avvia: avvia,
  };
})();
