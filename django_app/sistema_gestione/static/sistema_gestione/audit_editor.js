/* Progressive enhancement: forms and explicit save continue to work without JS.
 * Rete instabile (audit in reparto, tablet): ogni modifica è tenuta anche sul dispositivo
 * finché il server non conferma; i salvataggi falliti per rete si ritentano con attesa
 * crescente e al ritorno della connessione. Ogni tentativo porta un identificativo, così un
 * retry dopo una risposta persa non genera un falso conflitto di versione. */
(() => {
  const filter = document.getElementById("filtro-verifiche");
  if (filter) filter.addEventListener("change", () => {
    document.querySelectorAll(".sg-esito-card").forEach(card => {
      card.hidden = filter.value === "aperte" ? card.dataset.completo === "1"
        : filter.value === "rilievi" ? !["NC", "OFI", "OSS"].includes(card.dataset.esito) : false;
    });
  });

  const nuovoId = () => (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
    : String(Date.now()) + Math.random().toString(16).slice(2);
  const storage = (() => { try { const k = "__sg"; localStorage.setItem(k, k); localStorage.removeItem(k); return localStorage; } catch (e) { return null; } })();
  const ATTESE = [2000, 4000, 8000, 16000, 30000, 60000];

  document.querySelectorAll("form[data-audit-autosave]").forEach(form => {
    const status = form.querySelector("[data-save-status]");
    const version = form.querySelector('[name="versione"]');
    // Chiave per utente (tablet condivisi) e scadenza: le bozze locali non restano per sempre.
    const chiave = "sg-bozza:" + (form.dataset.utente || "") + ":" + form.dataset.auditAutosave;
    const SCADENZA_MS = 7 * 24 * 3600 * 1000;
    let timer, saving = false, dirty = false, blocked = false, submitted = false, changes = 0;
    let tentativo = 0, salvataggioId = nuovoId(), daConfermare = false;
    const announce = (message, error = false) => {
      status.textContent = message;
      status.dataset.error = error ? "1" : "0";
    };
    const campi = () => {
      const dati = {};
      new FormData(form).forEach((v, k) => { if (k !== "csrfmiddlewaretoken" && typeof v === "string") dati[k] = v; });
      return dati;
    };
    const conserva = () => {
      if (!storage) return;
      try { storage.setItem(chiave, JSON.stringify({versione: version.value, campi: campi(), quando: Date.now()})); } catch (e) { /* quota piena: resta solo il server */ }
    };
    const dimentica = () => { if (storage) storage.removeItem(chiave); };

    // Bozza locale rimasta da una sessione interrotta (rete caduta, batteria, pagina chiusa).
    if (storage) {
      try {
        const locale = JSON.parse(storage.getItem(chiave) || "null");
        const attuali = campi();
        const scaduta = locale && Date.now() - (locale.quando || 0) > SCADENZA_MS;
        // Si propone il ripristino ogni volta che il testo locale differisce da quello del server,
        // anche se nel frattempo la versione è cambiata (risposta persa, altro salvataggio).
        if (locale && !scaduta && Object.keys(locale.campi).some(k => (attuali[k] || "") !== locale.campi[k])) {
          const banner = document.createElement("div");
          banner.className = "sg-alert warn";
          banner.setAttribute("role", "status");
          const titolo = document.createElement("strong");
          titolo.textContent = "Modifiche non salvate su questo dispositivo";
          banner.append(titolo, " del " + new Date(locale.quando).toLocaleString("it-IT") + ". " +
            (locale.versione !== version.value ? "La verifica è stata salvata anche dopo: controlla i campi prima di ripristinare. " : ""));
          const ripristina = document.createElement("button");
          ripristina.type = "button"; ripristina.className = "btn"; ripristina.textContent = "Ripristina";
          const scarta = document.createElement("button");
          scarta.type = "button"; scarta.className = "btn btn-secondary"; scarta.textContent = "Scarta";
          banner.append(ripristina, " ", scarta);
          form.prepend(banner);
          ripristina.addEventListener("click", () => {
            Object.entries(locale.campi).forEach(([k, v]) => {
              form.querySelectorAll(`[name="${CSS.escape(k)}"]`).forEach(el => {
                if (el.type === "radio" || el.type === "checkbox") el.checked = el.value === v;
                else el.value = v;
              });
            });
            banner.remove(); dirty = true; changes += 1; salvataggioId = nuovoId(); save();
          });
          scarta.addEventListener("click", () => { dimentica(); banner.remove(); });
        } else if (locale) {
          dimentica();
        }
      } catch (e) { dimentica(); }
    }

    async function save() {
      if (saving || blocked || !dirty) return;
      saving = true;
      const revision = changes;
      announce("Salvataggio bozza...");
      const body = new FormData(form);
      body.set("salvataggio_id", salvataggioId);
      let retry = false;
      try {
        const response = await fetch(form.dataset.auditAutosave, {
          method: "POST", body, credentials: "same-origin",
          headers: {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
        });
        // 5xx prima del tipo di risposta: una pagina d'errore HTML del server (502/503) va ritentata,
        // non scambiata per una sessione scaduta.
        if (response.status >= 500) { retry = true; throw new Error("Server non disponibile, riprovo."); }
        const contentType = response.headers.get("content-type") || "";
        if (response.redirected || !contentType.includes("application/json")) {
          blocked = true;
          throw new Error("Sessione scaduta o risposta non valida. Il testo resta su questo dispositivo: accedi e riprova.");
        }
        const data = await response.json();
        if (!response.ok) {
          blocked = [401, 403, 409].includes(response.status);
          const details = Object.values(data.errori || {}).flat().map(item => item.message).join(" ");
          throw new Error(details || data.errore || "Salvataggio non riuscito.");
        }
        version.value = data.versione;
        tentativo = 0;
        daConfermare = false;
        salvataggioId = nuovoId();
        // «ripetuto»: il server aveva già applicato il tentativo precedente e ha ignorato questo
        // corpo; le modifiche fatte nel frattempo vanno salvate con un nuovo tentativo.
        dirty = data.ripetuto ? true : changes !== revision;
        if (data.ripetuto) { saving = false; setTimeout(save, 300); }
        if (!dirty) dimentica(); else conserva();
        const missing = data.mancanti.length;
        announce(`Bozza salvata alle ${data.salvato_il}. ${missing ? missing + " informazioni da completare." : "Pronta per registrare l'esito."}`);
      } catch (error) {
        if (error instanceof TypeError) retry = true;  // rete assente o caduta durante la richiesta
        if (retry && !blocked) {
          daConfermare = true;  // la richiesta potrebbe essere arrivata: stesso id al prossimo tentativo
          const attesa = ATTESE[Math.min(tentativo, ATTESE.length - 1)];
          tentativo += 1;
          announce(`${navigator.onLine === false ? "Offline" : "Rete instabile"}: la bozza è conservata su questo dispositivo. Nuovo tentativo tra ${Math.round(attesa / 1000)} s.`, true);
          clearTimeout(timer);
          timer = setTimeout(save, attesa);
        } else {
          announce("Non salvato: " + error.message, true);
        }
      } finally {
        saving = false;
        if (!retry && dirty && changes !== revision && !blocked) {
          salvataggioId = nuovoId();
          timer = setTimeout(save, 900);
        }
      }
    }
    const modificato = () => {
      dirty = true;
      changes += 1;
      if (!daConfermare) salvataggioId = nuovoId();
      conserva();
      clearTimeout(timer);
      if (!blocked) timer = setTimeout(save, 900);
    };
    form.addEventListener("input", modificato);
    form.addEventListener("change", modificato);
    window.addEventListener("online", () => { if (dirty && !blocked) { tentativo = 0; save(); } });
    window.addEventListener("offline", () => announce("Offline: continua pure, la bozza resta su questo dispositivo.", true));
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
      // La bozza locale resta finché la pagina successiva non conferma che il server ha lo stesso testo.
      submitted = true;
    });
    window.addEventListener("beforeunload", event => {
      if (!submitted && (dirty || saving)) { event.preventDefault(); event.returnValue = ""; }
    });
  });

  // Evidenze: caricamento senza ricaricare la pagina (anche foto dalla fotocamera).
  document.querySelectorAll("form[data-audit-upload]").forEach(form => {
    const esito = form.querySelector("[data-upload-status]");
    const lista = document.querySelector(form.dataset.auditUpload);
    let inAttesa = null;  // file non caricato per rete assente: si riprova al ritorno della connessione
    window.addEventListener("online", () => { if (inAttesa) invia(inAttesa); });
    form.querySelectorAll('input[type="file"]').forEach(input => {
      input.addEventListener("change", () => { if (input.files.length) invia(input); });
    });
    form.addEventListener("submit", event => {
      const input = Array.from(form.querySelectorAll('input[type="file"]')).find(i => i.files.length);
      if (!input || !window.fetch) return;
      event.preventDefault();
      invia(input);
    });
    async function invia(input) {
      const body = new FormData();
      body.set("csrfmiddlewaretoken", form.querySelector("[name=csrfmiddlewaretoken]").value);
      body.set("file", input.files[0]);
      esito.textContent = "Caricamento di " + input.files[0].name + "...";
      esito.dataset.error = "0";
      let errRete = false;
      try {
        const response = await fetch(form.action, {method: "POST", body, credentials: "same-origin",
          headers: {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}});
        if (response.status >= 500 || !(response.headers.get("content-type") || "").includes("application/json")) {
          errRete = response.status >= 500;
          throw new Error(response.status === 413 ? "File troppo grande per il server." : "Risposta non valida dal server: riprova.");
        }
        const data = await response.json();
        if (!response.ok) throw new Error(data.errore || "Caricamento non riuscito.");
        inAttesa = null;
        const riga = document.createElement("p");
        const link = document.createElement("a");
        link.href = data.url; link.textContent = data.nome;
        riga.append(link, ` · ${Math.round(data.dimensione / 1024)} kB · SHA-256 ${data.sha256.slice(0, 12)}…`);
        if (lista) { lista.querySelector("[data-vuoto]")?.remove(); lista.append(riga); }
        esito.textContent = data.rilievo_emesso ? "Evidenza archiviata: il rilievo è stato registrato nel MOD.174." : "Evidenza archiviata con impronta SHA-256.";
        input.value = "";
      } catch (error) {
        if (error instanceof TypeError || errRete) {
          // Rete assente: la foto resta selezionata e si ricarica da sola appena torna la connessione.
          inAttesa = input;
          esito.textContent = "Rete non disponibile: il file resta in attesa e verrà caricato appena torna la connessione.";
        } else {
          esito.textContent = error.message;
          input.value = "";
        }
        esito.dataset.error = "1";
      }
    }
  });
})();
