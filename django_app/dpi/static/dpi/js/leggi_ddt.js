/* Magazzino DPI · «Leggi un DDT» (dpi/views.py _magazzino_ddt, dpi/lettura_ddt.py).
 * «Leggi il DDT» manda il file con azione=leggi_ddt e mostra testata e righe proposte;
 * il gestore spunta, corregge le quantità e invia (azione=carico_ddt).
 */
(function () {
  "use strict";
  var form = document.getElementById("pane-leggi-ddt");
  var btn = document.getElementById("ddt-leggi");
  if (!form || !btn) return;

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  btn.addEventListener("click", function () {
    var file = el("ddt-file");
    if (!file.files || !file.files.length) { el("ddt-stato").textContent = "Scegli prima il file."; return; }
    var data = new FormData(form);
    data.set("azione", "leggi_ddt");
    btn.disabled = true;
    el("ddt-stato").textContent = "Lettura in corso…";
    fetch(form.getAttribute("action"), {
      method: "POST", body: data, credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" }
    })
      .then(function (r) { return r.json().catch(function () { return { ok: false, errore: "Risposta non valida." }; }); })
      .then(function (p) {
        if (!p.ok) { el("ddt-stato").textContent = p.errore || "Lettura non riuscita."; return; }
        el("ddt-stato").textContent = p.ocr ? "Letto con il riconoscimento del testo: controlla le quantità." : "Letto.";
        if (p.numero) el("ddt-numero").value = p.numero;
        if (p.data) el("ddt-data").value = p.data;
        if (p.fornitore && !el("ddt-fornitore").value) el("ddt-fornitore").value = p.fornitore;
        el("ddt-avvisi").textContent = (p.avvisi || []).join(" ");
        var body = el("ddt-righe-body");
        body.innerHTML = (p.righe || []).map(function (r) {
          return "<tr>" +
            '<td><input type="hidden" name="riga_modello" value="' + esc(r.modello_id) + '">' +
            '<input type="checkbox" name="riga_ok_' + esc(r.modello_id) + '" value="1" checked aria-label="Carica ' + esc(r.codice) + '"></td>' +
            "<td><strong>" + esc(r.codice) + "</strong> " + esc(r.nome) + '<div class="dpi-muted">' + esc(r.tipo) + "</div></td>" +
            '<td><input type="number" min="1" name="riga_qta_' + esc(r.modello_id) + '" value="' + esc(r.quantita) + '" style="width:90px">' +
            (r.da_controllare ? ' <span class="dpi-muted">da controllare</span>' : "") + "</td>" +
            '<td class="dpi-muted">' + esc(r.riga) + "</td></tr>";
        }).join("");
        el("ddt-righe").hidden = !(p.righe || []).length;
        el("ddt-carica").disabled = !(p.righe || []).length;
      })
      .catch(function () { el("ddt-stato").textContent = "Lettura non riuscita (rete)."; })
      .then(function () { btn.disabled = false; });
  });
})();
