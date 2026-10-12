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
