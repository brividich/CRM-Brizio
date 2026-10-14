# `hub_tools` — hub strumenti interni admin

Area **Core** · URL `/admin-portale/hub/` · codice [`django_app/hub_tools/`](../../django_app/hub_tools/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Module Manager, DB Manager, Schema infografica, Homepage builder, Guide

## Dettaglio

Collezione di tool sotto `/admin-portale/hub/` protetti da `@legacy_admin_required`.

- **Module Manager** — abilita/disabilita moduli visibili, configura redirect post-login
- **Database Manager** — statistiche tabelle, backup, pulizia log/sessioni, ottimizzazione, ripristino. Engine rilevato automaticamente (SQLite dev / SQL Server prod)
- **Schema DB** (`/admin-portale/hub/database/schema/`) — generato a runtime dai modelli (`hub_tools/schema_db.py`, cache per processo): panoramica con le connessioni verso i sistemi esterni (`CONNESSIONI_ESTERNE`, scritto a mano: nomi delle chiavi `.env`, mai i valori) e tra moduli; pagina per modulo `?app=<label>` con «Usa» / «Usato da», campi, tipi, PK/FK/1:1/M:M e «Usata da» per tabella; ricerca su tabella, modello e campo. Una nuova app va aggiunta ad `APP_INFO` (area, colore, descrizione), una nuova integrazione a `CONNESSIONI_ESTERNE`
- **Homepage Builder** — editor visuale layout home per ruolo
- **Setup Wizard Hub** — rilancia il wizard di configurazione (14 step) sul `.env` corrente, normalizzando i booleani `True`/`False` e `1`/`0`; la sezione Microsoft Graph / SharePoint centralizza credenziali e ID delle liste usate da assenze, incidenti e automazioni.
- **Guide** — catalogo auto-indicizzato di documenti (HTML/PDF/MD) da `tools/`, `doc/`, `deployment/`, con dedup per formato
- **Categorie moduli / branding portale** — raggruppa la navigazione e personalizza nome, loghi upload/URL, favicon e colori globali della shell
