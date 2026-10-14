// Mostra i campi SNMPv3 solo con versione v3 (e nasconde la community classica).
// Marcatori impostati da CredenzialiV3Form: data-snmp-versione, data-snmp-v3, data-snmp-non-v3;
// data-snmp-v3-gruppo e' il riquadro di _form_sezioni.html.
// Wizard «Nuovo apparato»: data-tipo-apparato sul tipo, data-solo-mfc / data-solo-altri sui campi.
// Si riaggancia dopo ogni passo caricato da HTMX (il wizard sostituisce il proprio contenuto).
(function () {
  function contenitore(el) {
    return el.closest(".form-field") || el.parentElement;
  }
  function mostra(elementi, visibile) {
    elementi.forEach(function (el) { contenitore(el).style.display = visibile ? "" : "none"; });
  }
  function collegaVersione(versione) {
    var form = versione.form;
    if (!form || versione.dataset.snmpCollegato) return;
    versione.dataset.snmpCollegato = "1";
    function aggiorna() {
      var attivo = versione.value === "v3";
      mostra(form.querySelectorAll("[data-snmp-v3]"), attivo);
      mostra(form.querySelectorAll("[data-snmp-non-v3]"), !attivo);
      form.querySelectorAll("[data-snmp-v3-gruppo]").forEach(function (el) {
        el.style.display = attivo ? "" : "none";
      });
    }
    versione.addEventListener("change", aggiorna);
    aggiorna();
  }
  function collegaTipo(tipo) {
    var form = tipo.form;
    if (!form || tipo.dataset.snmpCollegato) return;
    tipo.dataset.snmpCollegato = "1";
    function aggiorna() {
      var mfc = tipo.value === "MFC";
      mostra(form.querySelectorAll("[data-solo-mfc]"), mfc);
      mostra(form.querySelectorAll("[data-solo-altri]"), !mfc);
    }
    tipo.addEventListener("change", aggiorna);
    aggiorna();
  }
  function avvia() {
    document.querySelectorAll("select[data-snmp-versione]").forEach(collegaVersione);
    document.querySelectorAll("select[data-tipo-apparato]").forEach(collegaTipo);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", avvia);
  } else {
    avvia();
  }
  document.addEventListener("htmx:afterSettle", avvia);
})();
