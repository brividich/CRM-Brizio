/* NOVICROM HUB — da anomalie/pages/anomalie_configurazione.html (blocco 1), spostato dall'inline il 12/11/2026: stesso punto, ora in cache. */
(function () {
  const defaults = {
    capi_reparto: [],
    capi_commessa: [],
    causali_doc: ["OP", "OG"],
    stati_superficie: ["Finito macchinato", "Con sovrametallo", "Finito trattato"],
    avanzamenti: ["Accetto lo stato", "In attesa", "Finito trattato"],
    autorizzati_modifica: [
      "Benedetta Bellucci",
      "Serena Giani",
      "Luca Bova",
      "Simone Smarrella",
      "Sara Gentile",
    ],
    conferma_aggiornamenti: [],
    rdc_segnalazione: [],
    escalation_supervisori: [],
    azioni_effettuate: ["Rilavorato", "Riparato", "Scartato", "Reso al fornitore", "Accettato in deroga"],
    referenti_rdc: [],
    avanzamenti_qualita: ["In attesa", "In attesa chiarimenti"],
    attachments_dir: "media\\anomalie_allegati",
  };

  const ids = [
    "causali_doc",
    "stati_superficie",
    "avanzamenti",
    "azioni_effettuate",
    "autorizzati_modifica",
    "referenti_rdc",
    "avanzamenti_qualita",
  ];
  const ccChiudeEl = document.getElementById("cc_puo_chiudere");
  const fields = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));
  // Liste derivate: la composizione (ruoli + override persona) e' modificabile,
  // l'elenco risultante resta calcolato dal server.
  const derivedLists = {
    capi_reparto: {
      el: document.getElementById("capi_reparto_list"),
      empty: "Nessun nominativo: seleziona almeno un ruolo operativo o aggiungi una persona",
    },
    capi_commessa: {
      el: document.getElementById("capi_commessa_list"),
      empty: "Nessun nominativo: seleziona almeno un ruolo operativo o aggiungi una persona",
    },
  };
  const esc = (v) => String(v == null ? "" : v).replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
  const ruoliOperativi = Array.isArray(window._CFG_RUOLI_OPERATIVI) ? window._CFG_RUOLI_OPERATIVI : [];
  const anagraficaNames = Array.isArray(window._CFG_ANAGRAFICA_NAMES) ? window._CFG_ANAGRAFICA_NAMES : [];
  // Referenti RDC: scelta rapida dall'anagrafica (si può anche scrivere a mano).
  (function () {
    const picker = document.getElementById("referenti_rdc_picker");
    const addBtn = document.getElementById("referenti_rdc_add");
    const area = document.getElementById("referenti_rdc");
    if (!picker || !addBtn || !area) return;
    picker.innerHTML = "<option value=''>— scegli una persona —</option>" +
      anagraficaNames.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
    addBtn.addEventListener("click", () => {
      const name = picker.value;
      if (!name) return;
      const current = area.value.split(/\r?\n/).map((t) => t.trim()).filter(Boolean);
      if (!current.some((n) => n.toLowerCase() === name.toLowerCase())) current.push(name);
      area.value = current.join("\n");
      picker.value = "";
    });
  })();
  const derivedBlocks = {};
  document.querySelectorAll(".derived-block").forEach((block) => {
    const key = block.dataset.derivedKey;
    if (!key) return;
    derivedBlocks[key] = block;
    const rolesBox = block.querySelector('[data-role="roles"]');
    if (rolesBox) {
      rolesBox.innerHTML = ruoliOperativi.length
        ? ruoliOperativi.map((r) =>
            `<label><input type="checkbox" value="${r.id}">${r.icona ? esc(r.icona) + " " : ""}${esc(r.nome)}</label>`
          ).join("")
        : "<span class='empty'>Nessun ruolo operativo in Anagrafica</span>";
    }
    ["extra", "esclusi"].forEach((kind) => {
      const picker = block.querySelector(`[data-role="${kind}-picker"]`);
      const addBtn = block.querySelector(`[data-role="${kind}-add"]`);
      const area = block.querySelector(`[data-role="${kind}"]`);
      if (!picker || !addBtn || !area) return;
      picker.innerHTML =
        "<option value=''>— scegli una persona —</option>" +
        anagraficaNames.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
      addBtn.addEventListener("click", () => {
        const name = picker.value;
        if (!name) return;
        const current = fromText(area.value);
        if (!current.some((n) => n.toLowerCase() === name.toLowerCase())) current.push(name);
        area.value = current.join("\n");
        picker.value = "";
      });
    });
  });

  const readDerivedSources = () => {
    const out = {};
    Object.entries(derivedBlocks).forEach(([key, block]) => {
      out[key] = {
        ruoli: Array.from(block.querySelectorAll('[data-role="roles"] input:checked'))
          .map((el) => parseInt(el.value, 10))
          .filter((n) => !isNaN(n)),
        extra: fromText((block.querySelector('[data-role="extra"]') || {}).value || ""),
        esclusi: fromText((block.querySelector('[data-role="esclusi"]') || {}).value || ""),
      };
    });
    return out;
  };

  const fillDerivedSources = (sources) => {
    const src = sources && typeof sources === "object" ? sources : {};
    Object.entries(derivedBlocks).forEach(([key, block]) => {
      const cfg = src[key] || {};
      const ruoli = (cfg.ruoli || []).map(Number);
      block.querySelectorAll('[data-role="roles"] input').forEach((el) => {
        el.checked = ruoli.indexOf(parseInt(el.value, 10)) !== -1;
      });
      const extraEl = block.querySelector('[data-role="extra"]');
      const escluEl = block.querySelector('[data-role="esclusi"]');
      if (extraEl) extraEl.value = (cfg.extra || []).join("\n");
      if (escluEl) escluEl.value = (cfg.esclusi || []).join("\n");
    });
  };
  const attachmentsDirEl = document.getElementById("attachments_dir");
  const statusEl = document.getElementById("status");
  const btnSave = document.getElementById("btn-save");
  const btnDefault = document.getElementById("btn-default");

  if (!btnSave) return; // non siamo nella tab config

  const getCsrf = () =>
    (document.cookie.split(";").find((c) => c.trim().startsWith("csrftoken=")) || "").split("=")[1] || "";

  const toText = (arr) => (Array.isArray(arr) ? arr.join("\n") : "");

  const fromText = (value) => {
    const seen = new Set();
    const out = [];
    (value || "").split(/\r?\n/).forEach((raw) => {
      const text = String(raw || "").trim();
      if (!text) return;
      const key = text.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push(text);
    });
    return out;
  };

  const setStatus = (type, message) => {
    statusEl.className = "status " + type;
    statusEl.textContent = message;
  };

  const fill = (payload, attachmentsDir) => {
    const src = payload && typeof payload === "object" ? payload : {};
    ids.forEach((id) => {
      if (fields[id]) fields[id].value = toText(src[id] ?? defaults[id]);
    });
    Object.entries(derivedLists).forEach(([key, cfg]) => {
      if (!cfg.el) return;
      const lista = Array.isArray(src[key]) ? src[key] : [];
      cfg.el.innerHTML = lista.length
        ? lista.map(n => `<li>${esc(n)}</li>`).join("")
        : `<li class='empty'>${cfg.empty}</li>`;
    });
    if (attachmentsDirEl) attachmentsDirEl.value = String(attachmentsDir || defaults.attachments_dir || "").trim();
  };

  const loadFromApi = async () => {
    try {
      const r = await fetch("/api/anomalie/config/liste");
      const j = await r.json();
      if (!r.ok || !j.success) throw new Error(j.error || "Errore caricamento configurazione");
      fill(j.lists || {}, j.attachments_dir || defaults.attachments_dir);
      if (ccChiudeEl) ccChiudeEl.checked = j.cc_puo_chiudere !== false;
      fillDerivedSources(j.derived_sources || window._CFG_DERIVED_SOURCES);
    } catch (e) {
      fill(window._CFG_LISTS || defaults, window._CFG_ATTACHMENTS_DIR || defaults.attachments_dir);
      fillDerivedSources(window._CFG_DERIVED_SOURCES);
      setStatus("err", e.message || "Errore caricamento configurazione");
    }
  };

  btnDefault.addEventListener("click", () => {
    fill(defaults, defaults.attachments_dir);
    setStatus("ok", "Default caricati in pagina. Premi 'Salva configurazione' per confermare.");
  });

  btnSave.addEventListener("click", async () => {
    const payload = Object.fromEntries(ids.map((id) => [id, fromText(fields[id].value)]));
    payload.attachments_dir = String(attachmentsDirEl.value || "").trim();
    payload.derived_sources = readDerivedSources();
    if (ccChiudeEl) payload.cc_puo_chiudere = ccChiudeEl.checked;
    btnSave.disabled = true;
    btnDefault.disabled = true;
    try {
      const r = await fetch("/api/anomalie/config/liste", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCsrf(),
        },
        body: JSON.stringify(payload),
      });
      const j = await r.json();
      if (!r.ok || !j.success) throw new Error(j.error || "Salvataggio non riuscito");
      fill(j.lists || payload, j.attachments_dir || payload.attachments_dir);
      fillDerivedSources(j.derived_sources || payload.derived_sources);
      setStatus("ok", "Configurazione salvata correttamente.");
    } catch (e) {
      setStatus("err", e.message || "Errore durante il salvataggio");
    } finally {
      btnSave.disabled = false;
      btnDefault.disabled = false;
    }
  });

  fill(window._CFG_LISTS || defaults, window._CFG_ATTACHMENTS_DIR || defaults.attachments_dir);
  fillDerivedSources(window._CFG_DERIVED_SOURCES);
  loadFromApi();
})();
