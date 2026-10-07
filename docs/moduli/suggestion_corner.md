# `suggestion_corner`

Area **Operations** · URL `/suggestion-corner/` (+ `/suggestion-corner/nuova/` pubblico, `/suggestion-corner/gestione/` console SMS_TEAM, `/suggestion-corner/<id>/modifica/` gestione) · codice [`django_app/suggestion_corner/`](../../django_app/suggestion_corner/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

**Suggestion Corner** (SMS — Sistema Miglioramento/Segnalazione, sostituisce Microsoft Forms/PowerApps): ciclo **PDCA** su macchina a stati **django-fsm-2** (INSERITA→…→CHIUSA), UI in stile HUB (card, badge di stato, stepper PDCA). **Provenienza/destinazione = Reparto o Area Aziendale** (selettore a cascata). **Form pubblico anonimo** senza login (route esente ACL, rate-limit per IP + honeypot). Doppia autorizzazione: **ACL v2** per l'accesso al modulo + Django Group **SMS_TEAM** per lo scope dati (il team vede tutto, gli altri le proprie + gli incarichi). **Notifiche email** (mail al team all'invio + solleciti/escalation DO/CHECK via django-q2) e **in-app** (assegnazione incaricato/controllore, riuso `core.Notifica`). **Import storico SharePoint** (`import_suggestion_corner_legacy`, dry-run/idempotente + `--reparto-map` per rimappare i reparti). **Pagina di gestione interna** (`/suggestion-corner/<id>/modifica/`, riservata SMS_TEAM) per correggere reparti/persone/esiti/testi PDCA con traccia nello storico (lo stato resta gestito solo dal workflow). **Comunicazione al cliente per gli «SMS Sì»**: destinatario per-segnalazione, invio manuale via bottone, con tracciamento data/stato «comunicato» e voce di storico. **Copilota AI locale** (Ollama on-premise): classificazione SMS Sì/No, bozza PLAN e dedup segnalazioni simili — l'AI propone, l'operatore firma

## Hardening ottobre 2026

- Form pubblico: il limite di invii per IP non si aggira più con l'header `X-Forwarded-For` (letto solo da proxy fidati) e c'è un limite globale di 50 invii/ora. Allegati in storage privato cifrato (migrazione `suggestion_corner 0007`).
