/* Player e-learning: heartbeat verso il server (prompt 05).
 *
 * Il tempo di fruizione lo misura il SERVER con il proprio orologio: qui si
 * mandano solo segnali (slide corrente, pagina visibile, millisecondi
 * dall'ultima interazione). Un battito ogni ~31 s; il server rifiuta quelli
 * più ravvicinati di 30 s. Quando il server dichiara la slide completata, si
 * abilita «Avanti». Nessun dato del browser decide il completamento.
 */
(function () {
  "use strict";
  var player = document.querySelector(".fm-player[data-beat-url]");
  if (!player) return;
  var url = player.getAttribute("data-beat-url");
  var intervallo = (parseInt(player.getAttribute("data-beat-intervallo"), 10) || 30) * 1000 + 1000;
  var ultimaInterazione = Date.now();

  function segnaInterazione() { ultimaInterazione = Date.now(); }
  ["click", "keydown", "scroll", "touchstart", "mousemove"].forEach(function (ev) {
    document.addEventListener(ev, segnaInterazione, { passive: true });
  });
  // Un video in riproduzione è attività anche senza mouse o tastiera.
  document.addEventListener("timeupdate", function (e) {
    if (e.target && e.target.tagName === "VIDEO" && !e.target.paused) segnaInterazione();
  }, true);

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function slideCorrente() {
    return player.querySelector(".fm-slide[data-slide-id]");
  }

  function abilitaAvanti(slide) {
    if (!slide) return;
    var btn = slide.querySelector(".js-avanti");
    if (btn) btn.disabled = false;
    var attesa = slide.querySelector(".fm-slide-attesa");
    if (attesa) attesa.remove();
  }

  // Conto alla rovescia solo estetico: lo sblocco reale arriva dal server.
  setInterval(function () {
    var slide = slideCorrente();
    var el = slide && slide.querySelector(".js-secondi");
    if (!el || document.visibilityState !== "visible") return;
    var n = Math.max(parseInt(el.textContent, 10) - 1, 0);
    el.textContent = n;
  }, 1000);

  function battito() {
    var slide = slideCorrente();
    var corpo = {
      slide_id: slide ? parseInt(slide.getAttribute("data-slide-id"), 10) : null,
      visibile: document.visibilityState === "visible",
      inattivo_ms: Date.now() - ultimaInterazione
    };
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), "Accept": "application/json" },
      body: JSON.stringify(corpo)
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (dati) {
        if (dati && dati.slide_completata) abilitaAvanti(slide);
        var minuti = document.querySelector(".js-minuti");
        if (minuti && dati && typeof dati.minuti_fatti === "number") minuti.textContent = dati.minuti_fatti;
      }).catch(function () { /* rete assente: il prossimo battito riprova */ });
  }

  setInterval(battito, intervallo);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") segnaInterazione();
  });
})();
