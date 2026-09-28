/* Progressive enhancement: forms and explicit save continue to work without JS. */
(() => {
  const filter = document.getElementById("filtro-verifiche");
  if (filter) filter.addEventListener("change", () => {
    document.querySelectorAll(".sg-esito-card").forEach(card => {
      card.hidden = filter.value === "aperte" ? card.dataset.completo === "1"
        : filter.value === "rilievi" ? !["NC", "OFI"].includes(card.dataset.esito) : false;
    });
  });
  document.querySelectorAll("form[data-audit-autosave]").forEach(form => {
    const status = form.querySelector("[data-save-status]");
    const version = form.querySelector('[name="versione"]');
    let timer, saving = false, dirty = false, blocked = false, submitted = false, changes = 0;
    const announce = (message, error = false) => {
      status.textContent = message;
      status.dataset.error = error ? "1" : "0";
    };
    async function save() {
      if (saving || blocked || !dirty) return;
      saving = true;
      const revision = changes;
      announce("Salvataggio bozza...");
      try {
        const response = await fetch(form.dataset.auditAutosave, {
          method: "POST", body: new FormData(form), credentials: "same-origin",
          headers: {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
        });
        const contentType = response.headers.get("content-type") || "";
        if (response.redirected || !contentType.includes("application/json")) {
          throw new Error("Sessione scaduta o risposta non valida. Il testo resta qui: accedi e riprova.");
        }
        const data = await response.json();
        if (!response.ok) {
          blocked = [401, 403, 409].includes(response.status);
          const details = Object.values(data.errori || {}).flat().map(item => item.message).join(" ");
          throw new Error(details || data.errore || "Salvataggio non riuscito.");
        }
        version.value = data.versione;
        dirty = changes !== revision;
        const missing = data.mancanti.length;
        announce(`Bozza salvata alle ${data.salvato_il}. ${missing ? missing + " informazioni da completare." : "Pronta per registrare l'esito."}`);
      } catch (error) {
        announce("Non salvato: " + error.message, true);
      } finally {
        saving = false;
        // Only queue when the user typed during this request; no retry loop on errors.
        if (dirty && changes !== revision && !blocked) timer = setTimeout(save, 900);
      }
    }
    form.addEventListener("input", () => {
      dirty = true;
      changes += 1;
      clearTimeout(timer);
      if (!blocked) timer = setTimeout(save, 900);
    });
    form.addEventListener("change", () => {
      if (!dirty) { dirty = true; changes += 1; }
      clearTimeout(timer);
      if (!blocked) timer = setTimeout(save, 900);
    });
    form.addEventListener("submit", event => {
      clearTimeout(timer);
      if (saving) {
        event.preventDefault();
        announce("Attendi il salvataggio della bozza, poi registra l'esito.");
        return;
      }
      if (blocked) {
        event.preventDefault();
        announce("La verifica non e piu modificabile o e cambiata altrove. Conserva il testo e ricarica la pagina.", true);
        return;
      }
      submitted = true;
    });
    window.addEventListener("beforeunload", event => {
      if (!submitted && (dirty || saving)) { event.preventDefault(); event.returnValue = ""; }
    });
  });
})();
