/* Service worker notifiche push — NOVICROM HUB (servito da core.views_push).
 *
 * Il segnale push arriva SENZA contenuto: il testo si legge dal portale con la
 * sessione dell'utente. Se il portale non risponde (fuori rete, sessione
 * scaduta) si mostra un avviso generico che apre le notifiche.
 */
const ICONA = "{{ icona|escapejs }}";
const API_ULTIME = "/api/notifiche/push/ultime/";
const GENERICA = {
  titolo: "NOVICROM HUB",
  messaggio: "Hai una notifica nuova nel portale.",
  url: "/notifiche/",
};

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function urlInterno(url) {
  return typeof url === "string" && url.startsWith("/") && !url.startsWith("//") ? url : "/notifiche/";
}

self.addEventListener("push", (event) => {
  event.waitUntil(
    fetch(API_ULTIME, { credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" } })
      .then((resp) => (resp.ok ? resp.json() : null))
      .catch(() => null)
      .then((data) => {
        const n = data && data.ok ? data : GENERICA;
        const opzioni = {
          body: n.messaggio || GENERICA.messaggio,
          tag: "novicrom-hub-notifiche",
          renotify: true,
          data: { url: urlInterno(n.url) },
        };
        if (ICONA) {
          opzioni.icon = ICONA;
        }
        return self.registration.showNotification(n.titolo || GENERICA.titolo, opzioni);
      })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(urlInterno(event.notification.data && event.notification.data.url), self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((finestre) => {
      for (const f of finestre) {
        if (f.url === url && "focus" in f) {
          return f.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
