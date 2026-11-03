# `suggestion_corner`

Area **Operations** · URL `/suggestion-corner/` (+ `/suggestion-corner/nuova/` pubblico, `/suggestion-corner/gestione/` console SMS_TEAM, `/suggestion-corner/gestione/locandine/` locandine QR, `/suggestion-corner/<id>/modifica/` gestione) · codice [`django_app/suggestion_corner/`](../../django_app/suggestion_corner/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

**Suggestion Corner** (SMS — Sistema Miglioramento/Segnalazione, sostituisce Microsoft Forms/PowerApps): ciclo **PDCA** su macchina a stati **django-fsm-2** (INSERITA→…→CHIUSA), UI in stile HUB (card, badge di stato, stepper PDCA). **Provenienza/destinazione = Reparto o Area Aziendale** (selettore a cascata). **Form pubblico anonimo** senza login (route esente ACL, rate-limit per IP + honeypot). Doppia autorizzazione: **ACL v2** per l'accesso al modulo + Django Group **SMS_TEAM** per lo scope dati (il team vede tutto, gli altri le proprie + gli incarichi). **Notifiche email** (mail al team all'invio + solleciti/escalation DO/CHECK via django-q2) e **in-app** (assegnazione incaricato/controllore, riuso `core.Notifica`). **Import storico SharePoint** (`import_suggestion_corner_legacy`, dry-run/idempotente + `--reparto-map` per rimappare i reparti). **Pagina di gestione interna** (`/suggestion-corner/<id>/modifica/`, riservata SMS_TEAM) per correggere reparti/persone/esiti/testi PDCA con traccia nello storico (lo stato resta gestito solo dal workflow). **Comunicazione al cliente per gli «SMS Sì»**: destinatario per-segnalazione, invio manuale via bottone, con tracciamento data/stato «comunicato» e voce di storico. **Copilota AI locale** (Ollama on-premise): classificazione SMS Sì/No, bozza PLAN e dedup segnalazioni simili — l'AI propone, l'operatore firma

## QR in bacheca e locandine (novembre 2026)

- **Form pubblico da telefono**: scelta obbligatoria fra «Anonimo» e «Mi identifico». Chi si identifica senza login scrive «Nome e cognome» (`segnalante_nome`, nessun recapito); con il login la segnalazione si lega all'account (`created_by`). Anonima: né account né nome. Il dettaglio mostra «Segnalata da» (con «nome dichiarato» per i nomi scritti a mano), la mail al team riporta la stessa riga.
- **Foto facoltativa**: JPG/PNG/WEBP fino a 15 MB, ricodificata in JPEG ≤2000 px senza EXIF/GPS (`foto.py`), salvata come `SuggestionCornerAllegato` nello storage privato cifrato. Si vede nel dettaglio tramite `/suggestion-corner/allegato/<id>/` (stessa visibilità della segnalazione).
- **Locandine QR** (`/suggestion-corner/gestione/locandine/`, solo team SMS; pulsante «Locandine QR» in elenco e in Gestione): preset `SuggestionCornerLocandina` con titolo, sottotitolo, testo sopra il QR, fino a 3 passi, riquadro in basso, piè di pagina, colori (4 temi), formato A4/A3, indirizzo stampato sì/no, preset predefinito. Il QR (vettoriale, sempre al centro) porta a `url_pubblico_form` della configurazione oppure `SITE_URL` + `/suggestion-corner/nuova/`. Anteprima PDF nella pagina (si aggiorna mentre si scrive), «Scarica PDF». Preset iniziali dalla migrazione: Standard, Sicurezza, Idee per migliorare, Essenziale.
- Migrazione `suggestion_corner 0008` (campo `segnalante_nome`, `url_pubblico_form` in configurazione, tabella `suggestion_corner_suggestioncornerlocandina` + preset). Rotte nuove legate a `suggestion_corner.segnalazione.view` (bootstrap ACL v8); il controllo team è nella view.

## Hardening ottobre 2026

- Form pubblico: il limite di invii per IP non si aggira più con l'header `X-Forwarded-For` (letto solo da proxy fidati) e c'è un limite globale di 50 invii/ora. Allegati in storage privato cifrato (migrazione `suggestion_corner 0007`).
