/* Impostazioni notifiche: push sul dispositivo (vedi core/push.py, core/views_push.py).
 *
 * - "Push" per categoria si spunta solo se la categoria è accesa nel portale.
 * - Attiva/Disattiva registra il service worker (/sw-notifiche.js) e
 *   l'iscrizione del browser presso il portale.
 */
(function () {
  "use strict";

  // Impostazioni notifiche (#ni-form) o wizard di primo accesso (il form che contiene #ni-push).
  const boxPush = document.getElementById("ni-push");
  const form = document.getElementById("ni-form") || (boxPush && boxPush.closest("form"));
  if (!form) return;

  // Push spuntabile solo con la categoria accesa.
  form.querySelectorAll("[data-ni-cat]").forEach(function (cat) {
    const push = form.querySelector('[data-ni-push="' + cat.dataset.niCat + '"]');
    if (!push) return;
    cat.addEventListener("change", function () {
      push.disabled = !cat.checked;
      if (!cat.checked) push.checked = false;
    });
  });

  const box = document.getElementById("ni-push");
  const stato = document.getElementById("ni-push-stato");
  if (!box || !stato) return;

  const btnAttiva = document.getElementById("ni-push-attiva");
  const btnDisattiva = document.getElementById("ni-push-disattiva");
  const btnProva = document.getElementById("ni-push-prova");
  const msg = document.getElementById("ni-push-msg");
  const vapid = box.dataset.vapid || "";
  const csrf = (form.querySelector("[name=csrfmiddlewaretoken]") || {}).value || "";

  function scrivi(testo) { if (msg) msg.textContent = testo || ""; }

  function setStato(testo, ok) {
    stato.textContent = testo;
    stato.classList.toggle("ok", ok === true);
    stato.classList.toggle("ko", ok === false);
  }

  function chiave(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, Accept: "application/json" },
      body: JSON.stringify(body || {}),
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false }; }).then(function (j) { j._status = r.status; return j; });
    });
  }

  const supportato = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (!vapid || !supportato || !window.isSecureContext) {
    if (!supportato) setStato("questo browser non supporta le notifiche push", false);
    else if (!window.isSecureContext) setStato("serve il portale in https", false);
    if (btnProva) btnProva.hidden = !vapid;
    return;
  }

  let registrazione = null;

  function aggiorna() {
    if (Notification.permission === "denied") {
      setStato("bloccate nelle impostazioni del browser per questo sito", false);
      btnAttiva.hidden = true;
      btnDisattiva.hidden = true;
      return Promise.resolve();
    }
    return registrazione.pushManager.getSubscription().then(function (sub) {
      if (sub) {
        setStato("attive", true);
        btnAttiva.hidden = true;
        btnDisattiva.hidden = false;
      } else {
        setStato("non attive", null);
        btnAttiva.hidden = false;
        btnDisattiva.hidden = true;
      }
    });
  }

  navigator.serviceWorker.register(box.dataset.urlSw, { scope: "/" })
    .then(function (reg) { registrazione = reg; return navigator.serviceWorker.ready; })
    .then(function (reg) { registrazione = reg; return aggiorna(); })
    .catch(function () { setStato("non disponibili (service worker non registrato)", false); });

  btnAttiva.addEventListener("click", function () {
    btnAttiva.disabled = true;
    scrivi("");
    Notification.requestPermission()
      .then(function (perm) {
        if (perm !== "granted") throw new Error("permesso");
        return registrazione.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: chiave(vapid) });
      })
      .then(function (sub) { return post(box.dataset.urlIscrizione, { endpoint: sub.endpoint }); })
      .then(function (r) {
        if (!r.ok) throw new Error(r.reason || "errore");
        scrivi("Push attivate. Ricarica la pagina per vederlo nell'elenco dei dispositivi.");
        if (btnProva) btnProva.disabled = false;
      })
      .catch(function (err) {
        scrivi(err && err.message === "permesso"
          ? "Il browser non ha dato il permesso: consenti le notifiche per questo sito e riprova."
          : "Attivazione non riuscita (" + ((err && err.message) || "errore") + ").");
      })
      .then(function () { btnAttiva.disabled = false; return aggiorna(); });
  });

  btnDisattiva.addEventListener("click", function () {
    btnDisattiva.disabled = true;
    registrazione.pushManager.getSubscription()
      .then(function (sub) {
        if (!sub) return null;
        const endpoint = sub.endpoint;
        return sub.unsubscribe().then(function () { return post(box.dataset.urlRevoca, { endpoint: endpoint }); });
      })
      .then(function () { scrivi("Push disattivate su questo dispositivo."); })
      .catch(function () { scrivi("Disattivazione non riuscita."); })
      .then(function () { btnDisattiva.disabled = false; return aggiorna(); });
  });

  if (btnProva) {
    btnProva.addEventListener("click", function () {
      btnProva.disabled = true;
      post(box.dataset.urlProva, {})
        .then(function (r) {
          scrivi(r.ok ? "Prova inviata: tra qualche secondo arriva su ogni dispositivo attivo."
                      : "Prova non inviata (" + (r.reason || "servizio push non raggiungibile") + ").");
        })
        .then(function () { btnProva.disabled = false; });
    });
  }

  box.querySelectorAll("[data-ni-revoca]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      post(box.dataset.urlRevoca, { id: btn.dataset.niRevoca }).then(function (r) {
        if (r.ok) btn.closest(".ni-dev").remove();
      });
    });
  });
})();
