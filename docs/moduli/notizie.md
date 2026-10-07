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
