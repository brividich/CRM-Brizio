# `notizie` — bacheca comunicazioni aziendali

Area **HR & Workflow** · URL `/notizie/` · codice [`django_app/notizie/`](../../django_app/notizie/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Bacheca con audience, allegati, letture tracked

## Dettaglio

Sistema di comunicazione top-down con target per ruolo/reparto.

- **4 modelli**: Notizia, NotiziaAudience, NotiziaAllegato, NotiziaLettura
- **Audience targeting** per ruolo/reparto/utente specifico
- **Allegati** multipli
- **Tracking letture** per misurare engagement
- **KPI dashboard** apertura per notizia
- **ACL bootstrap automatico** degli endpoint API all'avvio

## Hardening ottobre 2026

- Allegati in storage privato cifrato (`PRIVATE_ATTACHMENTS_ROOT`): si scaricano solo da `/notizie/allegato/<id>/`, con la stessa visibilità della notizia (o con il permesso di gestione). I file già caricati restano leggibili; IIS non serve più `media/notizie`. Migrazione `notizie 0004`.

## Ruoli del portale

Con il sistema dei ruoli attivo ([PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)) report e gestione delle notizie sono di chi ha «gestire» su Notizie (preset HR e Sicurezza), non più del nome del ruolo legacy. La visibilità delle notizie segue il pubblico della notizia.

## KPI coerenti e in tempo reale (02/11/2026)

Conformità = conferme della versione corrente / destinatari delle obbligatorie pubblicate (`_dashboard_rows`). Dal 13/11/2026 sta nella testata del Report letture (`_conformita_obbligatorie`).

## Anteprima PDF e pagine ridisegnate (13/11/2026)

- **Lettura** (`/notizie/<id>/`): PDF e immagini allegati in un visualizzatore accanto al testo; su schermi stretti il PDF si apre a schermo intero («Apri il PDF»). Conferma di lettura in una barra fissa in fondo.
- **Download protetto**: `/notizie/allegato/<id>/?anteprima=1` risponde inline solo per PDF, PNG, JPG, GIF e WEBP (`Content-Type` fissato dal server, `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`); senza parametro o per altri tipi resta `attachment`. La visibilità non cambia.
- **Elenco**: filtri a schede con i conteggi e ricerca `?q=` nel titolo e nel testo.
- **Gestione** (`/notizie/dashboard/`): schede di stato con i conteggi (contano la ricerca, non lo stato scelto), barra di copertura delle letture, permessi della dashboard in pannello laterale.
- **Inserimento/modifica**: «Scrivi / Anteprima», più file trascinati insieme (campo `nuovi_allegati`, stessa validazione di `NotiziaAllegatoForm`), destinatari a caselle per ruolo (`audience_picker=1` + `audience_roles`); il vecchio formset `audience-*` per ID resta accettato.
- Stile e script del modulo in `notizie/static/notizie/` (serve `collectstatic`).

## Report letture e Impostazioni ridisegnati (13/11/2026)

- **Report** (`/notizie/report/`, solo admin/HR): una riga per persona e notizia (prima una per ogni riga di lettura/versione), con nome e ruolo da `Profile`/utente invece dell'ID. Stato con la stessa regola di `_compliance_breakdown` (`_stato_persona`): Non letta, Da riconfermare, Da confermare, Confermata. Con `?notizia_id=` entrano anche i destinatari senza letture. Filtri: `stato`, `q` (persona, ruolo, titolo), `da`/`a` sulla data di conferma (chi non ha confermato esce), paginazione da 100. Schede di stato con i conteggi (non contano lo stato scelto). Impronta della versione letta visibile.
- **CSV** (`/notizie/report/export-csv/`): stesse righe e filtri della pagina (`_report_dataset`); colonne Persona, Ruolo, Utente ID, Notizia, Stato, Versione letta/corrente, Impronta, Aperta il, Confermata il (ora locale).
- **Impostazioni** (`/notizie/impostazioni/`): schede `permessi` (predefinita), `aspetto` (branding), `registro` (audit del modulo con etichette in italiano, filtro per azione, ricerca, paginazione da 50, link alla notizia se esiste). Tolti i riepiloghi doppi; `?tab=record` reindirizza alla Gestione notizie (`q`, `filter_stato`→`stato`), `?tab=log` apre il registro.
- **Gestione notizie**: pulsante «Letture» sulle pubblicate (apre il report di quella notizia); «Report letture» visibile solo a chi può aprirlo.
