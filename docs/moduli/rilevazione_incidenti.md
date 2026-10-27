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
- **Heatmap planimetria** in `/rilevazione-incidenti/heatmap/`: posizione presa, nell'ordine, dal **punto indicato** nel modulo (`planimetria_layout` + `planimetria_x/y`, migrazione 0008, selettore «Dove è successo» in nuovo/modifica, solo in modalità database locale come l'area), dalla **macchina coinvolta** (`asset` con marker collocato), dall'**area** scelta o dal riquadro con lo stesso reparto, dal **baricentro delle macchine collocate dello stesso reparto** (`heatmap_points`); punti raggruppati su griglia del 2%, disegnati in HTML (prima: SVG stirato con coordinate localizzate «25,3» che il browser scartava). Sotto la pianta il conteggio per fonte e le rilevazioni non collocabili
- **Statistiche** per reparto, causa, gravità e categoria evento

## Hardening ottobre 2026

- In modalità SharePoint la lista è in cache per 60 secondi (invalidata a ogni creazione/modifica/eliminazione) e la paginazione Graph ha un tempo massimo di 45 secondi: lista, statistiche ed export non tengono più occupato un thread per ogni apertura.

## Ruoli del portale

Con il sistema dei ruoli attivo ([PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)) ogni rilevazione nuova registra l'autore (`segnalato_da_legacy_id`, migrazione 0007): il dipendente vede le proprie, preposto e responsabile quelle del team, la Sicurezza tutte e le gestisce/chiude. Lista, dettaglio, modifica, eliminazione, statistiche, heatmap ed export applicano la stessa regola. Le rilevazioni storiche e quelle lette da SharePoint non hanno un autore affidabile: le vede solo chi ha visibilità «tutti». Le liste «preposti / RSPP» delle impostazioni valgono solo a sistema spento.
