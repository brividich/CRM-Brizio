(function () {
  "use strict";
  var form = document.querySelector("[data-fai-form]");
  if (!form) return;

  var regola = form.querySelector("[data-fai-regola]");
  var motivo = form.querySelector("[data-fai-motivo]");
  var piano = form.querySelector("[data-fai-piano]");
  var modulo = form.querySelector("[data-fai-modulo]");
  var numero = form.querySelector("[data-fai-numero]");
  var pn = form.querySelector('[name="part_number"]');

  function scelto(nome) {
    return form.querySelector('[name="' + nome + '"]:checked');
  }

  function aggiornaTipo() {
    var causale = scelto("causale");
    var tipo = scelto("tipo");
    if (!causale) {
      regola.textContent = "Scegli il motivo e il portale propone il tipo.";
      motivo.hidden = true;
      return;
    }
    var proposto = causale.dataset.tipo;
    var diverso = Boolean(tipo) && proposto === "COMPLETO" && tipo.value === "DELTA";
    motivo.hidden = !diverso;
    if (proposto === "DELTA") {
      regola.textContent = "La MT CN 15 ammette il Delta FAI: copre solo la parte di processo cambiata.";
    } else if (diverso) {
      regola.textContent = "La MT CN 15 qui chiede il FAI completo: puoi discostarti scrivendo il motivo.";
    } else {
      regola.textContent = "La MT CN 15 qui chiede il FAI completo.";
    }
  }

  function aggiornaPiano() {
    var interno = piano.value === "INTERNO";
    modulo.textContent = (interno ? "Si compila il MOD.134. " : "Si compila il MOD.129. ") +
      "Stato dell'OP nel gestionale: " + (interno ? "INT." : "FAI.");
    numero.placeholder = interno
      ? "Vuoto: PFCN_" + (pn.value.trim() || "P/N") + "_…_A in automatico"
      : "Numero del piano del cliente";
  }

  form.querySelectorAll('[name="causale"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      // Cambiando motivo si riparte dalla proposta: il tipo diverso resta una scelta esplicita.
      var proposta = form.querySelector('[name="tipo"][value="' + radio.dataset.tipo + '"]');
      if (proposta) proposta.checked = true;
      aggiornaTipo();
    });
  });
  form.querySelectorAll('[name="tipo"]').forEach(function (radio) {
    radio.addEventListener("change", aggiornaTipo);
  });
  piano.addEventListener("change", aggiornaPiano);

  var invio = form.querySelector("[data-fai-invio]");
  function aggiornaInvio() {
    var stato = scelto("stato");
    invio.hidden = Boolean(stato) && stato.value === "DA_ESEGUIRE" && !invio.querySelector("input").value;
  }
  form.querySelectorAll('[name="stato"]').forEach(function (radio) {
    radio.addEventListener("change", aggiornaInvio);
  });
  aggiornaInvio();
  pn.addEventListener("input", aggiornaPiano);

  aggiornaTipo();
  aggiornaPiano();
})();
