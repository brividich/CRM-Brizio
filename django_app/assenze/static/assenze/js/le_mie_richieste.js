/* NOVICROM HUB — Assenze, pagina «Le mie richieste».
 * Blocchi richiudibili che ricordano lo stato, ricerca, filtro per mese,
 * azioni di riga (Elimina, Sollecita, Certificato arrivato) e modale «Modifica». */
(function () {
  "use strict";

  var root = document.getElementById("abs-root");
  if (!root) return;

  var CHIAVE_SEZIONI = "assenze.mieRichieste.sezioni";
  var MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];
  var csrfInput = document.querySelector('#gestione-csrf input[name="csrfmiddlewaretoken"]');
  var csrf = csrfInput ? csrfInput.value : "";

  // ── Chiamate ────────────────────────────────────────────────────────────
  function isCsrfRetryResponse(response, payload) {
    if (payload && payload.csrf_retry) return true;
    var finalUrl = String((response && response.url) || "");
    return Boolean(response && response.redirected && finalUrl.indexOf("csrf_retry=1") >= 0);
  }

  async function postJsonWithCsrfRetry(url, body) {
    function doRequest() {
      return fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify(body),
      });
    }
    var res = await doRequest();
    var data = await res.json().catch(function () { return {}; });
    if (!isCsrfRetryResponse(res, data)) return { res: res, data: data };

    res = await doRequest();
    data = await res.json().catch(function () { return {}; });
    if (!isCsrfRetryResponse(res, data)) return { res: res, data: data };

    window.location.assign(data.reload_url || res.url || window.location.href);
    throw new Error("Sessione scaduta o cookie mancante. Pagina ricaricata.");
  }

  /** Conferma, chiamata, ricarica. In caso di errore il pulsante torna com'era. */
  async function azione(btn, opzioni) {
    if (opzioni.conferma && !(await window.hubConfirm(opzioni.conferma))) return;
    var testo = btn.textContent;
    btn.disabled = true;
    btn.textContent = opzioni.attesa;
    try {
      var result = await postJsonWithCsrfRetry(opzioni.url, opzioni.body);
      if (!result.res.ok || !result.data.ok) {
        throw new Error(result.data.error || ("HTTP " + result.res.status));
      }
      window.location.reload();
    } catch (err) {
      alert(opzioni.errore + err.message);
      btn.disabled = false;
      btn.textContent = testo;
    }
  }

  function elimina(btn) {
    return azione(btn, {
      conferma: "Eliminare questa richiesta di assenza? L'operazione non e reversibile.",
      attesa: "Eliminazione...",
      url: btn.dataset.deleteUrl,
      body: { item_id: Number(btn.dataset.id) },
      errore: "Errore eliminazione: ",
    });
  }

  // ── Blocchi richiudibili ────────────────────────────────────────────────
  var sezioni = Array.prototype.slice.call(root.querySelectorAll("details[data-mr-sec]"));
  var salvate = {};
  try { salvate = JSON.parse(window.localStorage.getItem(CHIAVE_SEZIONI)) || {}; } catch (e) { salvate = {}; }
  /** Apre o chiude senza ricordarlo: lo fanno i filtri e i link in arrivo. */
  function apri(sezione, aperta) {
    if (sezione.open === aperta) return;
    sezione.mrAutomatico = aperta;
    sezione.open = aperta;
  }

  sezioni.forEach(function (sezione) {
    var chiave = sezione.dataset.mrSec;
    sezione.dataset.mrPredefinita = sezione.open ? "1" : "";
    if (Object.prototype.hasOwnProperty.call(salvate, chiave)) apri(sezione, Boolean(salvate[chiave]));
    sezione.addEventListener("toggle", function () {
      if (sezione.mrAutomatico === sezione.open) { sezione.mrAutomatico = null; return; }
      sezione.mrAutomatico = null;
      salvate[chiave] = sezione.open;
      try { window.localStorage.setItem(CHIAVE_SEZIONI, JSON.stringify(salvate)); } catch (e) { /* senza memoria */ }
    });
  });

  function statoRicordato(sezione) {
    var chiave = sezione.dataset.mrSec;
    if (Object.prototype.hasOwnProperty.call(salvate, chiave)) return Boolean(salvate[chiave]);
    return sezione.dataset.mrPredefinita === "1";
  }

  // I link nell'intestazione non devono aprire o chiudere il blocco.
  root.addEventListener("click", function (event) {
    if (event.target.closest("summary a")) event.stopPropagation();
  }, true);

  // ── Ricerca e filtro per mese ───────────────────────────────────────────
  var searchInput = document.getElementById("filterSearch");
  var gruppi = Array.prototype.slice.call(root.querySelectorAll("details[data-mr-gruppo]"));
  var righe = Array.prototype.slice.call(root.querySelectorAll(".mr-item[data-id]"));
  var testi = righe.map(function (riga) { return String(riga.textContent || "").toLowerCase(); });
  var mesi = Array.prototype.slice.call(root.querySelectorAll("[data-mr-mese]"));
  var meseReset = document.getElementById("mr-mese-reset");
  var annoNota = document.getElementById("mr-anno-nota");
  var vuoto = document.getElementById("mr-vuoto");
  var meseAttivo = "";

  function applyFilters() {
    if (!righe.length) return;
    var query = String((searchInput && searchInput.value) || "").trim().toLowerCase();
    var filtro = Boolean(query || meseAttivo);
    var visibili = 0;

    righe.forEach(function (riga, indice) {
      var mostra = (!query || testi[indice].indexOf(query) >= 0) &&
        (!meseAttivo || String(riga.dataset.mesi || "").indexOf("," + meseAttivo + ",") >= 0);
      riga.hidden = !mostra;
      if (mostra) visibili += 1;
    });

    gruppi.forEach(function (gruppo) {
      var n = gruppo.querySelectorAll(".mr-item[data-id]:not([hidden])").length;
      var contatore = gruppo.querySelector("[data-mr-count]");
      if (contatore) contatore.textContent = filtro ? n + " di " + contatore.dataset.totale : contatore.dataset.totale;
      gruppo.hidden = n === 0;
      // Con un filtro i risultati si vedono subito; tolto il filtro torna come l'avevi lasciato.
      apri(gruppo, filtro ? n > 0 : statoRicordato(gruppo));
    });
    if (vuoto) vuoto.hidden = visibili > 0;
  }

  function scegliMese(numero) {
    meseAttivo = meseAttivo === numero ? "" : numero;
    var etichetta = "";
    mesi.forEach(function (btn) {
      var attivo = btn.dataset.mrMese === meseAttivo;
      btn.setAttribute("aria-pressed", attivo ? "true" : "false");
      if (attivo) etichetta = btn.dataset.label;
    });
    if (meseReset) meseReset.hidden = !meseAttivo;
    if (annoNota) annoNota.textContent = meseAttivo ? "solo " + etichetta : annoNota.dataset.base;
    applyFilters();
  }

  mesi.forEach(function (btn) {
    btn.addEventListener("click", function () { scegliMese(btn.dataset.mrMese); });
  });
  if (meseReset) meseReset.addEventListener("click", function () { scegliMese(meseAttivo); });
  if (searchInput) searchInput.addEventListener("input", applyFilters);

  // ?stato=waiting|approved|rejected (tessere della home): apre il blocco giusto.
  var perStato = { waiting: ["attesa"], approved: ["programma", "passate"], rejected: ["rifiutate"] };
  var richiesti = perStato[new URLSearchParams(window.location.search).get("stato")] || [];
  var primo = null;
  richiesti.forEach(function (chiave) {
    var sezione = document.getElementById("mr-" + chiave);
    if (!sezione) return;
    apri(sezione, true);
    sezione.dataset.mrPredefinita = "1";
    delete salvate[chiave];
    primo = primo || sezione;
  });
  if (primo) primo.scrollIntoView({ block: "start" });

  // ── Azioni di riga ──────────────────────────────────────────────────────
  root.addEventListener("click", function (event) {
    var btn = event.target.closest("button");
    if (!btn || btn.disabled) return;
    if (btn.classList.contains("btn-elimina")) {
      elimina(btn);
    } else if (btn.classList.contains("btn-cert-arrivato")) {
      azione(btn, {
        conferma: "Il certificato medico è arrivato? La modifica viene comunicata all'ufficio assenze e al capo reparto.",
        attesa: "Salvataggio...",
        url: "/assenze/api/mia/" + btn.dataset.id + "/update",
        body: { certificato_medico: "Arrivato" },
        errore: "Errore: ",
      });
    } else if (btn.classList.contains("btn-sollecita")) {
      azione(btn, {
        conferma: "Mandare al capo una mail di sollecito per questa richiesta?",
        attesa: "Invio...",
        url: "/assenze/api/sollecita/" + btn.dataset.id,
        body: {},
        errore: "Errore: ",
      });
    } else if (btn.classList.contains("btn-modifica")) {
      apriModale(btn);
    }
  });

  // ── Modale «Modifica» ───────────────────────────────────────────────────
  var overlay = document.getElementById("modal-modifica-overlay");
  if (!overlay) return;
  var modale = document.getElementById("modal-modifica");
  var modalItemId = document.getElementById("modal-item-id");
  var modalInizio = document.getElementById("modal-inizio");
  var modalFine = document.getElementById("modal-fine");
  var modalMotivazione = document.getElementById("modal-motivazione");
  var modalCertificatoWrap = document.getElementById("modal-certificato-wrap");
  var modalCertificato = document.getElementById("modal-certificato");
  var modalError = document.getElementById("modal-error");
  var modalSave = document.getElementById("modal-save");
  var modalDurata = document.getElementById("modal-durata");
  var modalElimina = document.getElementById("modal-elimina");
  var tipi = Array.prototype.slice.call(overlay.querySelectorAll('input[name="modal-tipo"]'));
  var apertoDa = null;

  function tipoScelto() {
    return tipi.filter(function (radio) { return radio.checked; })[0] || null;
  }

  function isoToLocal(isoStr) {
    if (!isoStr) return "";
    var d = new Date(isoStr);
    if (isNaN(d)) return "";
    function pad(n) { return String(n).padStart(2, "0"); }
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function scrivi(nodo, classe, parti) {
    nodo.className = classe;
    nodo.textContent = "";
    parti.forEach(function (parte) {
      if (typeof parte === "string") {
        nodo.appendChild(document.createTextNode(parte));
      } else {
        var forte = document.createElement("b");
        forte.textContent = parte.forte;
        nodo.appendChild(forte);
      }
    });
  }

  /** Colore del tipo, riquadro data e durata: seguono quello che scrivi. */
  function aggiornaModale() {
    var scelto = tipoScelto();
    modale.className = scelto ? "t-" + scelto.dataset.chiave : "";
    modalCertificatoWrap.hidden = !scelto || scelto.value !== "Malattia";

    var inizio = new Date(modalInizio.value);
    var fine = new Date(modalFine.value);
    document.getElementById("modal-tile-mese").textContent = isNaN(inizio) ? "" : MESI[inizio.getMonth()];
    document.getElementById("modal-tile-giorno").textContent = isNaN(inizio) ? "–" : inizio.getDate();

    if (isNaN(inizio) || isNaN(fine)) {
      scrivi(modalDurata, "mr-durata is-err", ["Indica inizio e fine."]);
      return;
    }
    if (fine <= inizio) {
      scrivi(modalDurata, "mr-durata is-err", ["La fine deve venire dopo l'inizio."]);
      return;
    }
    if (inizio.toDateString() === fine.toDateString()) {
      var ore = Math.round((fine - inizio) / 36e5 * 10) / 10;
      scrivi(modalDurata, "mr-durata", [
        { forte: String(ore).replace(".", ",") },
        (ore === 1 ? " ora" : " ore") + " · " + inizio.getDate() + " " + MESI[inizio.getMonth()],
      ]);
      return;
    }
    var giorni = Math.round(
      (new Date(fine.getFullYear(), fine.getMonth(), fine.getDate()) -
        new Date(inizio.getFullYear(), inizio.getMonth(), inizio.getDate())) / 864e5
    ) + 1;
    scrivi(modalDurata, "mr-durata", [
      { forte: String(giorni) },
      " giorni di calendario · dal " + inizio.getDate() + " " + MESI[inizio.getMonth()] +
        " al " + fine.getDate() + " " + MESI[fine.getMonth()],
    ]);
  }

  function closeModal() {
    if (!overlay.classList.contains("open")) return;
    overlay.classList.remove("open");
    if (apertoDa && document.contains(apertoDa)) apertoDa.focus();
    apertoDa = null;
  }

  function apriModale(btn) {
    apertoDa = btn;
    modalItemId.value = btn.dataset.id || "";
    var tipo = btn.dataset.tipo || "Ferie";
    var trovato = false;
    tipi.forEach(function (radio) {
      radio.checked = radio.value === tipo;
      trovato = trovato || radio.checked;
    });
    if (!trovato && tipi.length) tipi[tipi.length - 1].checked = true; // «Altro»
    modalInizio.value = isoToLocal(btn.dataset.inizioIso);
    modalFine.value = isoToLocal(btn.dataset.fineIso);
    modalMotivazione.value = btn.dataset.motivazione || "";
    modalCertificato.checked = Boolean((btn.dataset.certificatoMedico || "").trim());
    document.getElementById("modal-stato").textContent = btn.dataset.stato || "In attesa";
    document.getElementById("modal-attesa").textContent = btn.dataset.attesa ? "in attesa " + btn.dataset.attesa : "";
    modalError.textContent = "";
    modalSave.disabled = false;
    var riga = btn.closest(".mr-item");
    modalElimina.hidden = !(riga && riga.querySelector(".btn-elimina"));
    aggiornaModale();
    overlay.classList.add("open");
    (tipoScelto() || modalInizio).focus();
  }

  overlay.addEventListener("input", aggiornaModale);
  overlay.addEventListener("change", aggiornaModale);
  document.getElementById("modal-cancel").addEventListener("click", closeModal);
  document.getElementById("modal-chiudi").addEventListener("click", closeModal);
  overlay.addEventListener("mousedown", function (event) {
    if (event.target === overlay) closeModal();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeModal();
  });

  modalElimina.addEventListener("click", function () {
    var riga = apertoDa && apertoDa.closest(".mr-item");
    var btn = riga && riga.querySelector(".btn-elimina");
    if (!btn) return;
    closeModal();
    elimina(btn);
  });

  modalSave.addEventListener("click", async function () {
    var itemId = modalItemId.value;
    var scelto = tipoScelto();
    if (!itemId || !scelto) return;

    modalSave.disabled = true;
    modalError.textContent = "";
    try {
      var result = await postJsonWithCsrfRetry("/assenze/api/mia/" + itemId + "/update", {
        tipo: scelto.value,
        inizio: modalInizio.value ? new Date(modalInizio.value).toISOString() : "",
        fine: modalFine.value ? new Date(modalFine.value).toISOString() : "",
        motivazione: modalMotivazione.value.trim(),
        certificato_medico: modalCertificato.checked ? "Arrivato" : "",
      });
      if (!result.res.ok || !result.data.ok) {
        throw new Error(result.data.error || ("HTTP " + result.res.status));
      }
      window.location.reload();
    } catch (err) {
      modalError.textContent = "Errore: " + err.message;
      modalSave.disabled = false;
    }
  });
})();
