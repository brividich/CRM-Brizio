/* CN Automations: accende la vista in stile Power Automate sul designer delle regole.
   Preferenza per utente nel browser; senza JavaScript resta la vista classica. */
(function () {
  var KEY = "cn-automations-vista";
  function leggi() { try { return localStorage.getItem(KEY) !== "classica"; } catch (e) { return true; } }
  function scrivi(cn) { try { localStorage.setItem(KEY, cn ? "cn" : "classica"); } catch (e) { /* solo comodità */ } }
  function applica(cn) {
    document.querySelectorAll("[data-cn-shell]").forEach(function (el) { el.classList.toggle("cn-auto", cn); });
    document.querySelectorAll("[data-cn-toggle]").forEach(function (b) { b.setAttribute("aria-pressed", String(cn)); });
  }
  function init() {
    applica(leggi());
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
