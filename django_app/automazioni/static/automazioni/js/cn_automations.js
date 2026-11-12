/* CN Automations: accende la vista in stile Power Automate sul designer delle regole.
   Preferenza per utente nel browser; senza JavaScript resta la vista classica. */
(function () {
  var KEY = "cn-automations-vista";
  function leggi() { try { return localStorage.getItem(KEY) !== "classica"; } catch (e) { return true; } }
  function scrivi(cn) { try { localStorage.setItem(KEY, cn ? "cn" : "classica"); } catch (e) { /* solo comodità */ } }
  function applica(cn) {
    document.querySelectorAll("[data-cn-shell]").forEach(function (el) { el.classList.toggle("cn-auto", cn); });
    document.querySelectorAll("[data-cn-toggle]").forEach(function (b) { b.setAttribute("aria-pressed", String(cn)); });
    // Le righe di condizione si leggono e si modificano aperte, come in Power Automate.
    if (cn) document.querySelectorAll("[data-cn-shell] [data-condition-card] details[data-card-details]").forEach(function (d) { d.open = true; });
  }
  function init() {
    applica(leggi());
    // Righe aggiunte con «+ Aggiungi riga»: aperte anche loro.
    document.addEventListener("click", function (ev) {
      if (ev.target.closest("[data-add-condition]")) setTimeout(function () { applica(leggi()); }, 0);
    });
    document.addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-cn-toggle]");
      if (!b) return;
      var cn = b.getAttribute("aria-pressed") !== "true";
      scrivi(cn);
      applica(cn);
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
