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
})();
