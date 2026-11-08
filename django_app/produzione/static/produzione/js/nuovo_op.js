/* Pannello laterale «Nuovo OP».
 * Pulsanti: data-nuovo-op; data-pn="..." precompila il P/N; data-vai="1" apre la scheda dell'OP creato.
 * A OP creato manda l'evento «op:creato» sul documento, con l'OP in detail. */
(function () {
  "use strict";
  var pannello = document.querySelector("[data-nop]");
  var velo = document.querySelector("[data-nop-velo]");
  if (!pannello || !velo) return;
  var form = pannello.querySelector("[data-nop-form]");
  var errore = pannello.querySelector("[data-nop-errore]");
  var crea = pannello.querySelector("[data-nop-crea]");
  var anteprima = pannello.querySelector("[data-nop-titolo]");
  var origine = null;

  function campo(nome) { return form.elements[nome]; }

  function titolo() {
    var parti = [(campo("causale_doc").value.trim() || "OP").toUpperCase(), campo("anno").value.trim(), campo("numero").value.trim()];
    anteprima.textContent = parti[1] && parti[2] ? parti.join("/") : "—";
  }

  function pulisci() {
    errore.hidden = true;
    errore.textContent = "";
    pannello.querySelectorAll("[data-nop-err]").forEach(function (el) {
      el.textContent = "";
      el.closest(".nop-campo").classList.remove("is-errore");
    });
  }

  function apri(pulsante) {
    origine = pulsante;
    pulisci();
    if (pulsante.dataset.pn) campo("pn").value = pulsante.dataset.pn;
    titolo();
    velo.hidden = false;
    pannello.hidden = false;
    (campo("pn").value ? campo("numero") : campo("pn")).focus();
  }

  function chiudi() {
    pannello.hidden = true;
    velo.hidden = true;
    if (origine) origine.focus();
  }

  document.addEventListener("click", function (e) {
    var pulsante = e.target.closest("[data-nuovo-op]");
    if (pulsante) {
      e.preventDefault();
      apri(pulsante);
    }
  });
  pannello.querySelectorAll("[data-nop-chiudi]").forEach(function (b) { b.addEventListener("click", chiudi); });
  velo.addEventListener("click", chiudi);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !pannello.hidden) chiudi();
  });
  ["causale_doc", "anno", "numero"].forEach(function (n) { campo(n).addEventListener("input", titolo); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    pulisci();
    crea.disabled = true;
    fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, error: "Risposta non valida (" + r.status + ")." }; });
    }).then(function (dati) {
      crea.disabled = false;
      if (!dati.ok) {
        var errori = dati.errori || {};
        Object.keys(errori).forEach(function (nome) {
          var el = pannello.querySelector('[data-nop-err="' + nome + '"]');
          if (el) {
            el.textContent = errori[nome];
            el.closest(".nop-campo").classList.add("is-errore");
          }
        });
        var generale = dati.error || (!Object.keys(errori).length ? "OP non creato." : "");
        if (generale) { errore.textContent = generale; errore.hidden = false; }
        return;
      }
      document.dispatchEvent(new CustomEvent("op:creato", { detail: dati.op }));
      if (origine && origine.dataset.vai === "1") {
        window.location.href = dati.op.url;
        return;
      }
      form.reset();
      chiudi();
      if (window.hubFlash) window.hubFlash.show([{ level: "success", text: "OP " + dati.op.op + " creato." }]);
    }).catch(function () {
      crea.disabled = false;
      errore.textContent = "Connessione non riuscita: riprova.";
      errore.hidden = false;
    });
  });
})();
