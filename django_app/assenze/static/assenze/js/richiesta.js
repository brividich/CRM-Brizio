/* NOVICROM HUB — Assenze, form «Richiesta assenza».
 *
 * Il server fa il lavoro che dipende dai dati (HTMX nel template):
 *   - cambio dipendente → campo «Capo reparto» ridisegnato (assenze_richiesta_campo_capo);
 *   - saldo, avvisi HR e corsi nei giorni scelti → riquadro «Controlli» (assenze_richiesta_controlli).
 * Qui restano solo le regole del form: tipo dalle date, orari, riepilogo laterale,
 * errori accanto al campo prima dell'invio, niente doppio invio.
 * Valori dal template negli attributi data- del form (#richiestaForm).
 */
(function () {
  "use strict";

  var form = document.getElementById("richiestaForm");
  var conferma = document.getElementById("abs-conferma");
  var erroreServer = document.getElementById("abs-errore-server");

  // Dopo l'invio (Post/Redirect/Get) o con un errore del server: lo si porta in vista.
  var inEvidenza = conferma || erroreServer;
  if (inEvidenza) {
    inEvidenza.scrollIntoView({ block: "start" });
    try { inEvidenza.focus({ preventScroll: true }); } catch (e) { inEvidenza.focus(); }
  }
  if (!form) return;

  var NOME = form.getAttribute("data-nome") || "";
  var FLESS_ABILITATO = form.getAttribute("data-fless-abilitato") === "1";
  var MALATTIA_PER_TUTTI_SOLO = form.getAttribute("data-malattia-per-tutti-solo") === "1";

  var PRESETS = {
    mattina: ["06:00", "14:00"],
    sera:    ["14:00", "22:00"],
    normale: ["08:00", "17:00"],
    lunga:   ["08:00", "18:00"],
    mezza1:  ["08:00", "12:00"],
    mezza2:  ["13:00", "17:00"]
  };
  var AUTO_FINE_MINUTI = 30;

  function $(id) { return document.getElementById(id); }
  var tipoSel = $("tipoassenza");
  var certificatoWrap = $("certificato-wrap");
  var certificatoInput = $("certificato_medico");
  var skipApprovalInput = $("salta_approvazione");
  var startInput = $("time_start");
  var endInput = $("time_end");
  var dateStartInput = $("date_start");
  var dateEndInput = $("date_end");
  var typeCards = Array.prototype.slice.call(document.querySelectorAll("[data-type-card]"));
  var submitBtn = document.querySelector('button[type="submit"][form="richiestaForm"]');

  // ── Utilità ────────────────────────────────────────────────────────────
  function normalizeText(value) {
    return String(value || "").trim().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  }
  function tipo() { return tipoSel ? normalizeText(tipoSel.value) : ""; }
  function isPresenza() { return tipo() === "certifica presenza"; }
  function isMalattia() { return tipo() === "malattia"; }
  function isFerie() { return tipo() === "ferie"; }
  function isPermesso() { return tipo() === "permesso"; }
  function isFlessibilita() { return tipo() === "flessibilita"; }
  function selectedText(sel) {
    if (!sel || sel.selectedIndex < 0) return "";
    return sel.options[sel.selectedIndex].text.replace(/\s+/g, " ").trim();
  }
  function setText(el, text) { if (el) el.textContent = text; }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function minutesOf(value) {
    var parts = String(value || "").split(":");
    if (parts.length < 2) return null;
    var h = parseInt(parts[0], 10), m = parseInt(parts[1], 10);
    return (isNaN(h) || isNaN(m)) ? null : h * 60 + m;
  }
  function dateLabel(value) {
    var p = String(value || "").split("-");
    return p.length === 3 ? p[2] + "/" + p[1] + "/" + p[0] : String(value || "");
  }
  function parseDateTime(d, t) {
    if (!d) return null;
    var x = new Date(d + "T" + (t || "00:00"));
    return isNaN(x.getTime()) ? null : x;
  }
  function formatMinutes(min) {
    if (min === null || typeof min === "undefined") return "--";
    if (min < 60) return min + " min";
    var h = Math.floor(min / 60), m = min % 60;
    return m ? (h + "h " + m + "m") : (h + "h");
  }
  function inclusiveDays(ds, de) {
    var s = parseDateTime(ds), e = parseDateTime(de || ds);
    if (!s || !e || e < s) return null;
    return Math.floor((e - s) / 86400000) + 1;
  }
  function presenceTime(prefix) {
    var h = ($(prefix + "_h") || {}).value || "00";
    var m = ($(prefix + "_m") || {}).value || "00";
    return h + ":" + m;
  }
  function changed(el) { if (el) el.dispatchEvent(new Event("change", { bubbles: true })); }

  // Tom Select (tendine con più di 10 voci, tomselect-init.js): impostare solo il
  // <select> nativo non aggiorna la tendina visibile.
  function setSelectValue(el, value) {
    if (!el) return;
    if (el.tomselect) el.tomselect.setValue(value, true); else el.value = value;
    changed(el);
  }
  function setSelectDisabled(el, off) {
    if (!el) return;
    if (el.tomselect) { if (off) el.tomselect.disable(); else el.tomselect.enable(); }
    el.disabled = !!off;
  }

  // ── Tipo: card, Ferie/Permesso dalle date, Flessibilità ────────────────
  function setTypeValue(value) {
    if (!tipoSel) return;
    var target = normalizeText(value);
    for (var i = 0; i < tipoSel.options.length; i++) {
      var o = tipoSel.options[i];
      if (normalizeText(o.value) === target || normalizeText(o.text) === target) {
        tipoSel.selectedIndex = i;
        changed(tipoSel);
        return;
      }
    }
  }

  typeCards.forEach(function (card) {
    card.addEventListener("click", function () {
      setTypeValue(card.getAttribute("data-type-card"));
      syncFeriePermesso();
    });
  });

  // Card unica «Ferie / Permesso»: decidono le date, come il server
  // (permesso nello stesso giorno, ferie su più giorni a giornata intera).
  var tipoDateHint = $("abs-tipo-date-hint");
  var orarioPermesso = null;
  function syncFeriePermesso() {
    if (!isFerie() && !isPermesso()) {
      if (tipoDateHint) { tipoDateHint.hidden = true; tipoDateHint.textContent = ""; }
      return;
    }
    var ds = dateStartInput ? dateStartInput.value : "";
    var de = dateEndInput ? dateEndInput.value : "";
    var piuGiorni = !!(ds && de && de > ds);
    if (piuGiorni && !isFerie()) {
      if (startInput && endInput) orarioPermesso = [startInput.value, endInput.value];
      setTypeValue("Ferie");
    } else if (!piuGiorni && !isPermesso()) {
      setTypeValue("Permesso");
      if (orarioPermesso && startInput && endInput) {
        startInput.value = orarioPermesso[0];
        endInput.value = orarioPermesso[1];
      }
    }
    if (tipoDateHint) {
      tipoDateHint.textContent = piuGiorni
        ? "Più giorni: la richiesta è di ferie a giornata intera."
        : "Un solo giorno: la richiesta è un permesso, scegli l'orario.";
      tipoDateHint.hidden = !ds;
    }
  }

  var flessOrari = $("abs-fless-orari");
  var flessEntrata = $("fless_entrata");
  var flessUscita = $("fless_uscita");
  var flessNota = $("abs-fless-nota");
  function syncFlessibilitaToTimes() {
    if (!flessEntrata || !flessUscita) return;
    if (startInput) startInput.value = flessEntrata.value;
    if (endInput) endInput.value = flessUscita.value;
    // La flessibilità resta nello stesso giorno.
    if (dateStartInput && dateEndInput && dateStartInput.value) dateEndInput.value = dateStartInput.value;
    changed(endInput);
  }
  function applyFlessibilita() {
    var on = isFlessibilita();
    if (flessOrari) flessOrari.hidden = !on;
    // Orari fissi e un solo giorno: niente «Durata rapida», «Ora inizio/fine» e «Data fine» doppi.
    var orariLiberi = $("abs-orari-liberi");
    var campoDataFine = $("abs-campo-data-fine");
    var shortcutWrap = $("abs-shortcut-wrap");
    if (orariLiberi) orariLiberi.hidden = on;
    if (campoDataFine) campoDataFine.hidden = on;
    if (shortcutWrap && on) shortcutWrap.hidden = true;
    if (startInput) startInput.readOnly = on || startInput.readOnly;
    if (endInput) endInput.readOnly = on || endInput.readOnly;
    if (flessNota) {
      if (on && !FLESS_ABILITATO) {
        flessNota.textContent = "La flessibilità non risulta abilitata per te: la richiesta verrà rifiutata. Chiedi all'Amministrazione.";
      } else if (on) {
        flessNota.textContent = "Orari stabiliti dall'Amministrazione. Almeno 9 ore e non più di 10, massimo 2 a settimana.";
      }
      flessNota.hidden = !on;
      if (!on) flessNota.textContent = "";
    }
    if (on) syncFlessibilitaToTimes();
  }
  if (flessEntrata) flessEntrata.addEventListener("change", syncFlessibilitaToTimes);
  if (flessUscita) flessUscita.addEventListener("change", syncFlessibilitaToTimes);

  function applyTypeDefaults() {
    var shortcutWrap = $("abs-shortcut-wrap");
    if (shortcutWrap) shortcutWrap.hidden = isFerie() || isFlessibilita();
    if (isFerie()) {
      var custom = document.querySelector('input[name="shortcut"][value="custom"]');
      if (custom) custom.checked = true;
      if (startInput) { startInput.value = "00:00"; startInput.readOnly = true; }
      if (endInput) { endInput.value = "23:59"; endInput.readOnly = true; }
      if (dateStartInput && dateEndInput && dateStartInput.value && !dateEndInput.value) dateEndInput.value = dateStartInput.value;
      applyFlessibilita();
      return;
    }
    if (startInput) startInput.readOnly = false;
    if (endInput) endInput.readOnly = false;
    if (isPermesso() && dateStartInput && dateEndInput && dateStartInput.value && !dateEndInput.value) {
      dateEndInput.value = dateStartInput.value;
    }
    applyFlessibilita();
  }

  // Ora fine non successiva all'inizio: inizio + 30 minuti sullo stesso giorno,
  // come il server (_autocorreggi_fine), dichiarato a video.
  function autoFixEndTime() {
    var hint = $("abs-auto-fine-hint");
    function clearHint() { if (hint) { hint.hidden = true; hint.textContent = ""; } }
    if (!startInput || !endInput || !dateStartInput || !dateEndInput || isFerie()) { clearHint(); return; }
    if (dateStartInput.value && dateEndInput.value && dateEndInput.value !== dateStartInput.value) { clearHint(); return; }
    var start = minutesOf(startInput.value), end = minutesOf(endInput.value);
    if (start === null || end === null || end > start) { clearHint(); return; }
    var corrected = start + AUTO_FINE_MINUTI;
    if (corrected >= 24 * 60) { clearHint(); return; } // oltre mezzanotte decide il server
    var day = dateStartInput.value || dateEndInput.value || "";
    endInput.value = pad2(Math.floor(corrected / 60)) + ":" + pad2(corrected % 60);
    if (day && dateEndInput.value !== day) dateEndInput.value = day;
    if (hint) {
      hint.textContent = "L'ora di fine non era successiva all'inizio: impostata alle " + endInput.value + ".";
      hint.hidden = false;
    }
    changed(endInput);
  }
  if (startInput) startInput.addEventListener("change", autoFixEndTime);
  if (endInput) endInput.addEventListener("blur", autoFixEndTime);

  function applyShortcutLock() {
    if (isFerie()) return; // Ferie ha già gli orari bloccati
    var checked = document.querySelector('input[name="shortcut"]:checked');
    var isCustom = !checked || checked.value === "custom";
    if (startInput) startInput.readOnly = !isCustom;
    if (endInput) endInput.readOnly = !isCustom;
  }

  document.querySelectorAll('input[name="shortcut"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      if (isFerie()) { applyTypeDefaults(); return; }
      var p = PRESETS[this.value];
      if (p && startInput && endInput) { startInput.value = p[0]; endInput.value = p[1]; }
      applyShortcutLock();
    });
  });

  // ── Certifica presenza ─────────────────────────────────────────────────
  var togglePm = $("pres_toggle_pm");
  if (togglePm) {
    togglePm.addEventListener("change", function () {
      var pm = $("presenza-pm-section");
      if (pm) pm.classList.toggle("visible", togglePm.checked);
    });
  }

  function switchForm() {
    var standard = $("standard-section"), presenza = $("presenza-section");
    if (standard) standard.classList.toggle("hidden", isPresenza());
    if (presenza) presenza.classList.toggle("visible", isPresenza());
    if (certificatoWrap) certificatoWrap.classList.toggle("visible", isMalattia());
    var ripetiWrap = $("abs-ripeti-wrap");
    if (ripetiWrap) {
      ripetiWrap.hidden = !isPermesso();
      if (!isPermesso() && $("ripeti_fino_al")) $("ripeti_fino_al").value = "";
    }
    applyTypeDefaults();
    applyShortcutLock();
  }

  // ── Malattia per tutti: la scelta del dipendente vale solo per «Malattia» ─
  function syncMalattiaPerTutti() {
    if (!MALATTIA_PER_TUTTI_SOLO) return;
    var proprio = document.querySelector("[data-dip-proprio]");
    var scelta = document.querySelector("[data-dip-malattia]");
    var dipSel = $("dipendente_id");
    if (!proprio || !scelta || !dipSel) return;
    var malattia = isMalattia();
    scelta.hidden = !malattia;
    proprio.hidden = malattia;
    setSelectDisabled(dipSel, !malattia);
    // Azzerarlo scatena il cambio dipendente: HTMX riporta il capo di chi compila.
    if (!malattia && dipSel.value) setSelectValue(dipSel, "");
  }

  // ── Riepilogo laterale ─────────────────────────────────────────────────
  function currentDuration() {
    if (isPresenza()) {
      var data = ($("presenza_data") || {}).value || "";
      if (!data) return { label: "--", minutes: null, period: "Data non impostata", ready: false };
      var minutes = Math.max(0, minutesOf(presenceTime("pres_um")) - minutesOf(presenceTime("pres_em")));
      if (togglePm && togglePm.checked) {
        minutes += Math.max(0, minutesOf(presenceTime("pres_up")) - minutesOf(presenceTime("pres_ep")));
      }
      return { label: formatMinutes(minutes), minutes: minutes, period: dateLabel(data) + " (presenza certificata)", ready: minutes > 0 };
    }
    var ds = dateStartInput ? dateStartInput.value : "";
    var de = dateEndInput ? (dateEndInput.value || ds) : ds;
    var ts = startInput ? (startInput.value || "00:00") : "00:00";
    var te = endInput ? (endInput.value || "23:59") : "23:59";
    if (!ds) return { label: "--", minutes: null, period: "Date non impostate", ready: false };
    if (isFerie()) {
      var days = inclusiveDays(ds, de);
      if (!days) return { label: "--", minutes: null, period: "Periodo non valido", ready: false };
      return {
        label: days + (days === 1 ? " giornata" : " giornate"),
        minutes: days * 480,
        period: dateLabel(ds) + (de && de !== ds ? " - " + dateLabel(de) : ""),
        ready: true
      };
    }
    var start = parseDateTime(ds, ts), end = parseDateTime(de, te);
    var min = (start && end && end > start) ? Math.round((end - start) / 60000) : null;
    if (min === null) return { label: "--", minutes: null, period: "Periodo non valido", ready: false };
    return { label: formatMinutes(min), minutes: min, period: dateLabel(ds) + " " + ts + " - " + dateLabel(de) + " " + te, ready: true };
  }

  function updateTypeCards() {
    var current = tipo();
    typeCards.forEach(function (card) {
      var group = (card.getAttribute("data-type-group") || card.getAttribute("data-type-card") || "").split(" ").map(normalizeText);
      var on = !!current && group.indexOf(current) !== -1;
      card.classList.toggle("is-active", on);
      card.setAttribute("aria-pressed", on ? "true" : "false");
    });
    document.querySelectorAll(".abs-shortcut-item").forEach(function (label) {
      var input = label.querySelector('input[name="shortcut"]');
      label.classList.toggle("is-active", !!input && input.checked);
    });
  }

  function updatePreview() {
    var capo = $("caporeparto"); // ridisegnato da HTMX: lo si cerca ogni volta
    var dipSel = $("dipendente_id");
    var dur = currentDuration();
    var approvazione = "", approvazioneOk = false;
    if (skipApprovalInput && skipApprovalInput.checked) {
      approvazione = "Approvata subito (salta approvazione)"; approvazioneOk = true;
    } else if (capo && capo.value) {
      approvazione = selectedText(capo); approvazioneOk = true;
    } else {
      approvazione = "Capo reparto da scegliere";
    }
    updateTypeCards();
    setText($("abs-live-dipendente"), (dipSel && dipSel.tagName === "SELECT" && dipSel.value && !dipSel.disabled) ? selectedText(dipSel) : NOME);
    setText($("abs-live-type"), tipo() ? selectedText(tipoSel) : "Da scegliere");
    setText($("abs-live-period"), dur.period);
    setText($("abs-live-duration"), dur.label);
    setText($("abs-live-approval"), approvazione);

    var mancano = [];
    if (!tipo()) mancano.push("tipo");
    if (!dur.ready) mancano.push(isPresenza() ? "data e orari" : "date e orari validi");
    if (!approvazioneOk) mancano.push("capo reparto");
    var note = [];
    if (isFlessibilita() && dur.minutes !== null) {
      var ore = dur.minutes / 60;
      if (ore < 9) note.push("Flessibilità sotto le 9 ore: usa Permesso.");
      else if (ore > 10) note.push("Flessibilità oltre le 10 ore: riduci l'orario.");
      else if (Math.abs(ore - 10) < 0.001) note.push("Con 10 ore di flessibilità la pausa è di 2 ore (12:00-14:00).");
    }
    var badge = $("abs-live-ready");
    var pronta = !mancano.length;
    setText(badge, pronta ? "Pronta" : "Da completare");
    if (badge) badge.classList.toggle("is-ready", pronta);
    var box = $("abs-live-mancano");
    if (box) {
      var righe = [];
      if (mancano.length) righe.push("Manca: " + mancano.join(", ") + ".");
      box.textContent = righe.concat(note).join(" ");
      box.hidden = !box.textContent;
    }
  }

  // ── Errori accanto al campo ────────────────────────────────────────────
  var erroreInvio = $("abs-errore-invio");
  function pulisciErrori() {
    form.querySelectorAll(".abs-field-error").forEach(function (el) { el.remove(); });
    form.querySelectorAll("[aria-invalid]").forEach(function (el) {
      el.removeAttribute("aria-invalid");
      var prima = el.getAttribute("data-describedby-prima");
      if (prima) el.setAttribute("aria-describedby", prima); else el.removeAttribute("aria-describedby");
      el.removeAttribute("data-describedby-prima");
    });
    var campoTipo = $("abs-campo-tipo");
    if (campoTipo) campoTipo.classList.remove("has-error");
    if (erroreInvio) { erroreInvio.hidden = true; erroreInvio.textContent = ""; }
  }
  function segnalaErrore(el, msg) {
    var campo = (el && el.closest(".abs-field")) || el;
    if (!campo) return;
    var box = document.createElement("div");
    box.className = "abs-field-error";
    box.id = (el.id || "campo") + "-errore";
    box.textContent = msg;
    campo.appendChild(box);
    if (el.matches("input, select")) {
      if (el.hasAttribute("aria-describedby")) el.setAttribute("data-describedby-prima", el.getAttribute("aria-describedby"));
      el.setAttribute("aria-invalid", "true");
      el.setAttribute("aria-describedby", ((el.getAttribute("data-describedby-prima") || "") + " " + box.id).trim());
    } else {
      campo.classList.add("has-error");
    }
    if (erroreInvio) { erroreInvio.textContent = msg; erroreInvio.hidden = false; }
    var focusTarget = el.matches("input, select, button") ? el : el.querySelector("button, input, select");
    campo.scrollIntoView({ block: "center", behavior: "smooth" });
    if (focusTarget) { try { focusTarget.focus({ preventScroll: true }); } catch (e) { focusTarget.focus(); } }
  }

  function setHidden(name, val) {
    var el = form.querySelector('[name="' + name + '"]');
    if (!el) {
      el = document.createElement("input");
      el.type = "hidden";
      el.name = name;
      form.appendChild(el);
    }
    el.value = val;
  }

  function valida() {
    var t = tipo();
    if (!t) return segnalaErrore($("abs-campo-tipo"), "Scegli il tipo di assenza."), false;
    if (certificatoInput && t !== "malattia") certificatoInput.checked = false;

    if (t === "certifica presenza") {
      var data = ($("presenza_data") || {}).value || "";
      if (!data) return segnalaErrore($("presenza_data"), "Inserisci la data della certificazione presenza."), false;
      var pm = togglePm && togglePm.checked;
      var em = presenceTime("pres_em"), um = presenceTime("pres_um");
      setHidden("date_start", data);
      setHidden("time_start", em);
      setHidden("date_end", data);
      setHidden("time_end", pm ? presenceTime("pres_up") : um);
      setHidden("pres_entrata_mattina", em);
      setHidden("pres_uscita_mattina", um);
      setHidden("pres_turno_pomeriggio", pm ? "1" : "0");
      if (pm) {
        setHidden("pres_entrata_pomeriggio", presenceTime("pres_ep"));
        setHidden("pres_uscita_pomeriggio", presenceTime("pres_up"));
      }
      return true;
    }

    var ds = String(dateStartInput ? dateStartInput.value : "").trim();
    var de = String(dateEndInput ? dateEndInput.value : "").trim();
    var ts = String(startInput ? startInput.value : "").trim() || "00:00";
    var te = String(endInput ? endInput.value : "").trim() || "23:59";
    if (!ds) return segnalaErrore(dateStartInput, "Scegli la data di inizio."), false;
    if ((t === "permesso" || t === "ferie") && !de) { de = ds; if (dateEndInput) dateEndInput.value = de; }
    if (t === "ferie") {
      ts = "00:00"; te = "23:59";
      if (startInput) startInput.value = ts;
      if (endInput) endInput.value = te;
    }
    if (t === "permesso" && ds !== de) return segnalaErrore(dateEndInput, "Il permesso deve iniziare e finire nello stesso giorno."), false;
    var ripeti = String(($("ripeti_fino_al") || {}).value || "").trim();
    if (t === "permesso" && ripeti && ripeti < ds) return segnalaErrore($("ripeti_fino_al"), "Deve essere uguale o successiva alla data di inizio."), false;
    var start = parseDateTime(ds, ts), end = parseDateTime(de || ds, te);
    if (!start || !end) return segnalaErrore(dateStartInput, "Formato di data o ora non valido."), false;
    if (end <= start) return segnalaErrore(de && de !== ds ? dateEndInput : endInput, "La fine deve essere successiva all'inizio."), false;
    if (t === "flessibilita") {
      var ore = (end - start) / 3600000;
      if (ore < 9) return segnalaErrore(flessUscita || endInput, "Per la flessibilità servono almeno 8 ore di lavoro più 1 di pausa; altrimenti usa Permesso."), false;
      if (ore > 10) return segnalaErrore(flessUscita || endInput, "Flessibilità: massimo 10 ore."), false;
    }
    return true;
  }

  form.addEventListener("submit", function (evt) {
    pulisciErrori();
    if (!valida()) { evt.preventDefault(); return; }
    // Nessuno ha bloccato l'invio: il pulsante si spegne, un secondo clic non fa doppioni.
    if (submitBtn) {
      setTimeout(function () { submitBtn.disabled = true; submitBtn.textContent = "Invio in corso…"; }, 0);
    }
  });
  window.addEventListener("pageshow", function (evt) {
    if (evt.persisted && submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Conferma invio"; }
  });

  // ── Collegamenti ───────────────────────────────────────────────────────
  if (tipoSel) {
    tipoSel.addEventListener("change", function () { switchForm(); syncMalattiaPerTutti(); });
  }
  if (dateStartInput) {
    dateStartInput.addEventListener("change", function () {
      if ((isPermesso() || isFerie()) && dateEndInput && (!dateEndInput.value || dateEndInput.value < dateStartInput.value)) {
        dateEndInput.value = dateStartInput.value;
      }
      if (isFlessibilita() && dateEndInput) dateEndInput.value = dateStartInput.value;
      syncFeriePermesso();
    });
  }
  if (dateEndInput) dateEndInput.addEventListener("change", syncFeriePermesso);

  // Un solo ascoltatore per il riepilogo: vale anche per i campi ridisegnati da HTMX.
  form.addEventListener("change", function (evt) {
    updatePreview();
    // Si corregge qualcosa: gli errori spariscono, il prossimo invio ricontrolla tutto.
    if (erroreInvio && !erroreInvio.hidden) pulisciErrori();
  });
  form.addEventListener("input", updatePreview);
  // Il campo capo arriva dal server dopo il cambio dipendente.
  document.addEventListener("htmx:afterSettle", updatePreview);

  switchForm();
  syncMalattiaPerTutti();
  syncFeriePermesso();
  updatePreview();
})();
