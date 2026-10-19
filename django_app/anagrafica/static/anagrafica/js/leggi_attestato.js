/* «Leggi un attestato» (anagrafica/views_lettura_attestati.py).
 * «Leggi il documento» manda il file con azione=leggi_attestato e compila il modulo
 * con la proposta; «Registra» invia lo stesso modulo (file compreso). Nessun dato
 * resta sul server fra le due fasi.
 */
(function () {
  "use strict";
  var form = document.getElementById("la-form");
  var btn = document.getElementById("la-leggi");
  if (!form || !btn) return;

  var stato = document.getElementById("la-stato");
  var avvisi = document.getElementById("la-avvisi");
  var testoBox = document.getElementById("la-testo-box");
  var testo = document.getElementById("la-testo");

  function el(id) { return document.getElementById(id); }
  function hint(id, text, tone) {
    var h = el(id);
    if (!h) return;
    h.textContent = text || "";
    h.classList.toggle("ok", tone === "ok");
    h.classList.toggle("warn", tone === "warn");
  }
  function scegli(select, value) {
    if (!select || !value) return false;
    var found = Array.prototype.some.call(select.options, function (o) { return o.value === String(value); });
    if (found) select.value = String(value);
    return found;
  }
  function setIfEmpty(input, value) { if (input && value && !input.value) input.value = value; }

  btn.addEventListener("click", function () {
    var file = el("la-file");
    if (!file || !file.files || !file.files.length) { stato.textContent = "Scegli prima il file."; return; }
    var data = new FormData(form);
    data.set("azione", "leggi_attestato");
    btn.disabled = true;
    stato.textContent = "Lettura in corso… (una scansione può richiedere qualche secondo)";
    avvisi.textContent = "";
    fetch(form.getAttribute("action"), {
      method: "POST", body: data, credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" }
    })
      .then(function (r) { return r.json().catch(function () { return { ok: false, errore: "Risposta non valida." }; }); })
      .then(function (p) {
        if (!p.ok) { stato.textContent = p.errore || "Lettura non riuscita."; return; }
        stato.textContent = p.ocr ? "Letto con il riconoscimento del testo: controlla bene i campi." : "Letto.";

        var dip = p.dipendenti || [];
        if (dip.length === 1 && scegli(el("la-dipendente"), dip[0].legacy_id)) {
          hint("la-dipendente-hint", "Riconosciuto da " + dip[0].motivo + ".", "ok");
        } else if (dip.length > 1) {
          scegli(el("la-dipendente"), dip[0].legacy_id);
          hint("la-dipendente-hint", "Più persone possibili: " + dip.map(function (d) { return d.nome; }).join(", ") + ". Controlla.", "warn");
        } else {
          hint("la-dipendente-hint", "Non riconosciuto: sceglilo dall'elenco.", "warn");
        }

        var corsi = p.corsi || [];
        if (corsi.length && scegli(el("la-corso"), corsi[0].id)) {
          hint("la-corso-hint", (corsi.length > 1 ? "Più corsi possibili, scelto il più simile. " : "") + "Riconosciuto dal " + corsi[0].motivo + ".", corsi.length > 1 ? "warn" : "ok");
        } else {
          hint("la-corso-hint", "Non riconosciuto: sceglilo dall'elenco.", "warn");
        }

        setIfEmpty(el("la-data"), p.data_completamento);
        setIfEmpty(el("la-rilascio"), p.data_rilascio);
        setIfEmpty(el("la-ore"), p.ore);
        setIfEmpty(el("la-ente"), p.ente);
        setIfEmpty(el("la-numero"), p.numero);
        hint("la-scadenza-hint", p.data_scadenza_letta ? "Sull'attestato la scadenza è " + p.data_scadenza_letta.split("-").reverse().join("/") + ": confrontala con quella che calcolerà il portale." : "", p.data_scadenza_letta ? "warn" : "");

        avvisi.textContent = (p.avvisi || []).join(" ");
        if (p.testo) { testo.textContent = p.testo; testoBox.hidden = false; }
      })
      .catch(function () { stato.textContent = "Lettura non riuscita (rete)."; })
      .then(function () { btn.disabled = false; });
  });
})();
