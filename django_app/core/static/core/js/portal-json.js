/* NOVICROM HUB — lettura sicura delle risposte JSON (window.portalReadJsonResponse).
 * Spostato da template inline (12/11/2026): caricato nello stesso punto e senza defer,
 * quindi si esegue come prima; il browser lo tiene in cache. */
window.portalReadJsonResponse = async function (response, opts) {
  opts = opts || {};

  var rawText = "";
  try {
    rawText = await response.text();
  } catch (e) {
    rawText = "";
  }

  var contentType = String(response.headers.get("Content-Type") || "").toLowerCase();
  var trimmed = String(rawText || "").replace(/^\uFEFF/, "").trim();
  var shouldParseJson = contentType.indexOf("application/json") !== -1;
  var data = {};
  var hasJson = false;

  if (trimmed && (shouldParseJson || /^[\[{]/.test(trimmed))) {
    try {
      data = JSON.parse(trimmed);
      hasJson = true;
    } catch (e) {
      hasJson = false;
    }
  }

  var okFlagPresent = hasJson && data && typeof data === "object" && Object.prototype.hasOwnProperty.call(data, "ok");
  var dataSignalsError = okFlagPresent && data.ok === false;

  if (response.ok && hasJson && !dataSignalsError) {
    return data;
  }

  var message = "";
  if (hasJson && data && typeof data === "object") {
    message = String(data.error || data.message || "").trim();
  }

  if (!message) {
    if (response.status === 401) {
      message = "Sessione scaduta o autenticazione richiesta. Ricarica la pagina ed effettua di nuovo il login.";
    } else if (response.status === 403) {
      message = "Non hai i permessi per eseguire questa operazione.";
    } else if (!hasJson && trimmed && trimmed.charAt(0) === "<") {
      message = "Il server ha restituito HTML invece di JSON. Probabile sessione scaduta o accesso negato.";
    } else if (!response.ok) {
      message = String(opts.fallbackError || ("Errore server (" + response.status + ")."));
    } else {
      message = String(opts.invalidJsonMessage || "Il server ha restituito una risposta non valida.");
    }
  }

  var err = new Error(message);
  err.status = response.status;
  err.payload = hasJson ? data : null;
  err.rawText = rawText;
  throw err;
};
