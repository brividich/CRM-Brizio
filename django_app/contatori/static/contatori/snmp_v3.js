// Mostra i campi SNMPv3 solo con versione v3 (e nasconde la community classica).
// Marcatori impostati da CredenzialiV3Form: data-snmp-versione, data-snmp-v3, data-snmp-non-v3;
// data-snmp-v3-gruppo e' il riquadro di _form_sezioni.html.
(function () {
  function contenitore(el) {
    return el.closest(".form-field") || el.parentElement;
  }
  function collega(versione) {
    var form = versione.form;
    if (!form) return;
    var v3 = form.querySelectorAll("[data-snmp-v3]");
    var nonV3 = form.querySelectorAll("[data-snmp-non-v3]");
    var gruppi = form.querySelectorAll("[data-snmp-v3-gruppo]");
    function aggiorna() {
      var attivo = versione.value === "v3";
      v3.forEach(function (el) { contenitore(el).style.display = attivo ? "" : "none"; });
      nonV3.forEach(function (el) { contenitore(el).style.display = attivo ? "none" : ""; });
      gruppi.forEach(function (el) { el.style.display = attivo ? "" : "none"; });
    }
    versione.addEventListener("change", aggiorna);
    aggiorna();
  }
  function avvia() {
    document.querySelectorAll("select[data-snmp-versione]").forEach(collega);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", avvia);
  } else {
    avvia();
  }
})();
