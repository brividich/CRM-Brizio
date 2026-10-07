# `rilevazione_incidenti` — incidenti e unsafe conditions

Area **Sicurezza** · URL `/rilevazione-incidenti/` · codice [`django_app/rilevazione_incidenti/`](../../django_app/rilevazione_incidenti/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Unsafe conditions, near miss, incidenti, KPI sicurezza e heatmap planimetria

## Dettaglio

Segnalazione e tracciamento incidenti/mancati incidenti con **SharePoint** come fonte di verità.

- **2 modelli**: RilevazioneIncidente (cache locale), SicurezzaImpostazioni
- **CRUD via Graph API** sulla lista SharePoint configurata
- **Cache locale** Django per performance e query offline
- **Tipi normalizzati**: `incidente`, `near_miss`, `unsafe_condition`, con filtri e KPI separati rispetto alle etichette legacy SharePoint
- **Workflow** apertura → analisi → azioni correttive → verifica → chiusura
- **Allegati** salvati su SharePoint (foto scena, medicazioni, referti)
- **KPI sicurezza**: TRIR, giorni senza infortuni, headcount anagrafica e trend mensile pubblicati anche nel dashboard hub
- **Heatmap planimetria** in `/rilevazione-incidenti/heatmap/` con FK opzionale ad area layout e overlay SVG dei punti incidente
- **Statistiche** per reparto, causa, gravità e categoria evento

## Hardening ottobre 2026

- In modalità SharePoint la lista è in cache per 60 secondi (invalidata a ogni creazione/modifica/eliminazione) e la paginazione Graph ha un tempo massimo di 45 secondi: lista, statistiche ed export non tengono più occupato un thread per ogni apertura.
