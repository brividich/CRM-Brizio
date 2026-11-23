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

## Scheda per mail (14/11/2026)

`python manage.py invia_mail_segnalazione <id…> --to … [--cc …] [--senza-nominativo] [--dry-run]` manda la scheda completa della segnalazione (`rilevazione_incidenti/mail_scheda.py`, layout `send_hub_mail`, riga in «Mail inviate»). Serve a rimandare a mano una mail AU3 non arrivata; `--senza-nominativo` toglie nome e descrizione come l'informativa a preposti e RLS. Legge il database locale. La stessa scheda parte da sola a ogni nuova segnalazione salvata dal portale (flusso evento `sicurezza_scheda_segnalazione`, destinatari SiteConfig `sicurezza_scheda_segnalazione_emails`, di base rspp@, modificabili e disattivabili da Automazioni).

## Hardening ottobre 2026

- In modalità SharePoint la lista è in cache per 60 secondi (invalidata a ogni creazione/modifica/eliminazione) e la paginazione Graph ha un tempo massimo di 45 secondi: lista, statistiche ed export non tengono più occupato un thread per ogni apertura.

## Ruoli del portale

Con il sistema dei ruoli attivo ([PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)) ogni rilevazione nuova registra l'autore (`segnalato_da_legacy_id`, migrazione 0007): il dipendente vede le proprie, preposto e responsabile quelle del team, la Sicurezza tutte e le gestisce/chiude. Lista, dettaglio, modifica, eliminazione, statistiche, heatmap ed export applicano la stessa regola. Le rilevazioni storiche e quelle lette da SharePoint non hanno un autore affidabile: le vede solo chi ha visibilità «tutti». Le liste «preposti / RSPP» delle impostazioni valgono solo a sistema spento.

**Pagina di dettaglio come il Diario del preposto** (15/11/2026): `/rilevazione-incidenti/<id>/` ha la stessa grafica di `/diario-preposto/<id>/` (classi `dp-*`, CSS condiviso in `diario_preposto/partials/_dettaglio_css.html`, `_infografica_css.html`, `_storyline_css.html`). In cima «Situazione della rilevazione» (`rilevazione_incidenti/scheda.py` `infografica`): riquadri di sintesi, percorso Fatto → Registrata → Notificata → Valutata RLS → Chiusa (→ Oggi), controlli (registrata entro `GIORNI_RITARDO_REGISTRAZIONE`=2 giorni, dati completi, 5WHY, misure, notifiche, valutazione RLS, chiusura entro `GIORNI_CHIUSURA`=30 giorni, CAPA concluse) e confronto col reparto sulle rilevazioni visibili all'utente (12 mesi, precedente/successiva). A destra «Storia della rilevazione» (`costruisci_storyline`): audit `auto_insert`/`auto_update`, date RLS e chiusura, azioni CAPA, mail del registro «Mail inviate» (`sorgente=rilevazione_incidenti`). Con i dati su SharePoint storico e mail non ci sono.

**Rimanda la scheda** (15/11/2026): nel dettaglio, per l'RSPP (`_can_manage_rspp`) e solo con i dati nel database del portale, pulsante «Rimanda la scheda» → `POST /rilevazione-incidenti/<id>/rimanda-scheda/` (`rilevazione_incidenti:rimanda_scheda`). Rimanda la scheda come alla creazione dal flusso `sicurezza_scheda_segnalazione` (`automazioni.ripeti.rimanda_evento_modulo`): destinatari del flusso, regole «Invia mail», riga collegata in «Mail inviate»; flusso spento o senza destinatari = avviso, niente invio. Log attività: `rimanda_scheda`.

## KPI cliccabili (18/11/2026)

- Ogni tessera numerica è un link (`kpi-link`) all'elenco che conta lo stesso insieme; test in `tests_kpi_link*.py`.
- Lista: filtro `anno` e stato «In analisi (non chiuse)» (`STATO_IN_ANALISI`, `anno_rilevazione`). `_safe_json` ora neutralizza davvero `<`, `>`, `&`. TRIR, giorni senza infortuni e headcount restano senza link.

**Audit 22/11/2026 (G1-G3):** TRIR su ore stimate in proporzione all'anno trascorso (`organico × 2000 × giorni trascorsi / giorni dell'anno`), con `trir_base` mostrata sotto l'indice; `active_headcount` restituisce `None` se l'anagrafica non risponde (avviso «Organico non disponibile»). «Elimina» archivia (`archiviata_il`/`archiviata_da`/`motivo_archiviazione`, migrazione 0009): il gestore `objects` esclude le archiviate, `tutte` le include; elenco «Eliminate» (`?archiviate=1`, solo RSPP/ASPP) e POST `<id>/ripristina/`. Con sorgente SharePoint la cancellazione resta, con il motivo nel registro azioni.

**Elenco locale (audit P7, 23/11/2026):** `_fetch_items_local` carica area e punto della planimetria con `select_related` (prima fino a due query per riga).
