/* NOVICROM HUB — form MOD.128: mostra solo i campi che servono alla scelta fatta.
 * Un campo con data-mostra-se="tipo=corso" (o "ricorrenza=RICORRENTE", più valori
 * separati da |) compare solo quando il campo indicato ha quel valore. Il server
 * valida comunque tutto: qui si nasconde solo ciò che non c'entra. */
(function () {
  "use strict";
  function contenitore(el) {
    return el.closest(".mpqf-campo") || el.closest(".fmd-field") || el.parentElement;
  }
  function aggiorna(form) {
    form.querySelectorAll("[data-mostra-se]").forEach(function (el) {
      var regola = el.getAttribute("data-mostra-se").split("=");
      var sorgente = form.querySelector('[name="' + regola[0] + '"]:checked[type=radio]')
        || form.querySelector('[name="' + regola[0] + '"]');
      if (!sorgente) return;
      var valori = (regola[1] || "").split("|");
      var valore = sorgente.type === "checkbox" ? (sorgente.checked ? "1" : "0") : sorgente.value;
      var visibile = valori.indexOf(valore) >= 0;
      var box = el.hasAttribute("data-blocco") ? el : contenitore(el);
      if (box) box.hidden = !visibile;
    });
  }
  document.querySelectorAll("form").forEach(function (form) {
    if (!form.querySelector("[data-mostra-se]")) return;
    form.addEventListener("change", function () { aggiorna(form); });
    aggiorna(form);
  });
})();
