# Check automazioni di produzione — 29 settembre 2026

Rilevazione in sola lettura: 2026-09-29 16:52:30.3193728 +02:00 (ora server, Europe/Rome). Release distribuita **1.6.1 / c4ead42**, compilata il 28 settembre; non assumere presenti le modifiche successive della release Git.

## Esito e priorità

**Criticità principale: il broker django-q accumula lavori mentre i completamenti risultano fermi.** Non è corretto descrivere tutte le automazioni come funzionanti solo perché presenti nello scheduler.

- 48 job nel codice distribuito; **46 pianificazioni nel database**, tutte con ripetizione illimitata; 2 disabilitazioni esplicite: `ai_readiness_alert`, `ai_warmup_ollama`. Nessuna pianificazione mancante non spiegata da queste disabilitazioni; funzione, tipo, intervallo/cron e ripetizioni coincidono con il catalogo per tutte le 46 registrate.
- Primo campione (ore 16:46 circa): **8.857 task nel broker**, 8.853 con lock già scaduto/disponibile; il lock più vecchio risale al 27/09 ore 17:53 locali. Il lock indica disponibilità/prenotazione, non certifica da solo l'istante di accodamento.
- Secondo campione alle 16:52:30: **8.887 task nel broker** (+30). I conteggi per funzione nelle tabelle sotto si riferiscono a questo secondo campione. La crescita conferma che il problema è ancora presente durante il controllo.
- Ultimo completamento django-q conservato: **29/09 ore 12:49:03 locali**, quasi 4 ore prima del controllo. La tabella conserva 255 risultati: configurazione codice `save_limit=250`, quindi l'assenza di storico lungo non prova che un job non sia mai partito.
- La coda eventi `automation_event_queue` è distinta: **393 eventi, tutti done**, nessun pending/error al campione. Il monitor `automazioni_process_queue` registra **60 successi nell'ultima ora**, ultimo alle 16:46:53 locali. Serve identificare l'esecutore che la sta smaltendo; probabile percorso separato, non certificabile senza ispezione processi/task Windows.
- 25 regole del designer: **16 attive pubblicate e 9 disattive** (incluse bozze). Gli esiti success/skipped non certificano consegna email al destinatario.
- Due approvazioni ancora `pending` oltre `expires_at`; richiedono riconciliazione di stato. Il codice controlla anche la scadenza del token: non è stata dimostrata una possibilità di approvare link scaduti.
- Sei risultati falliti conservati per `contatori.tasks.poll_dispositivo`, seguiti da almeno un successo il 27/09. Causa e dispositivi non attribuiti in questo audit.
- Solo due job censiti in `monitoring_automationjob`: processore eventi e report settimanale. Copertura insufficiente per sorvegliare i 48 job.

### Interventi proposti

1. **P0 — ripristino controllato worker/broker.** Verificare processi e servizio qcluster, eventuali doppi esecutori e blocchi SNMP/Graph/OCR; misurare consumo coda. Non cancellare indiscriminatamente né rilanciare tutte le 8.857 invocazioni: distinguere polling ripetibili, reminder ormai superati e operazioni con effetti. Nessuna correzione applicata in questa sessione.
2. **P1 — watchdog indipendente.** Allarmi su età ultimo completamento, quantità/età arretrato e ultimo risultato utile per modulo. Il solo digest eseguito nello stesso cluster può restare bloccato insieme ai task che dovrebbe sorvegliare.
3. **P1 — attivazione reale regole evento.** Tabelle Visite mediche, Diario preposto, RENTRI e Incidenti prive di trigger SQL al controllo. Per le regole attive dei primi tre moduli non risultano eventi nella coda né `last_run_at`. Verificare/realizzare il collegamento evento prima di considerarle operative; non basta attivare la regola nel designer.
4. **P1 — Assenze e destinatari.** Verificare mutua esclusione tra flusso unico e regole legacy; riconciliare approvazioni scadute; assegnare destinatari di dominio espliciti.
5. **P2 — risultati utili e documentazione.** Distinguere completato/con lavoro, nessun dato, disabilitato, non configurato ed errore. Il catalogo auto-generato chiama “attive” tutte le definizioni; inoltre i commenti HR non descrivono sempre il fallback reale verso ADMINS/superuser.

## Come leggere l'inventario

Ogni riga identifica il job, il comportamento previsto dal codice distribuito, la cadenza e il conteggio nel broker al campione. **In coda non significa che tutte le invocazioni siano ancora utili**. Zero non prova salute: per mensili/trimestrali il prossimo appuntamento è il 1 ottobre. Orari della schedulazione in Europe/Rome (UTC+2 al controllo).

Punto comune di intervento: Centrale di comando / Task pianificati (`ScheduleControl`), impostazioni del modulo, poi funzione indicata per correzioni tecniche. Prima va risolto P0: le ottimizzazioni funzionali non rimuovono l'arretrato del cluster.

## Anagrafica / Formazione

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `archivia_attestati_mancanti` | Archivia gli attestati mancanti nel fascicolo dipendente, se abilitato. | ogni giorno, alle 02:15 | Registrata; 2 in coda | Mostrare quanti documenti mancano e distinguere funzione spenta da archivio completo. |
| `attiva_assegnazioni_programmate` | Applica gli spostamenti organizzativi alla decorrenza. | ogni giorno, alle 00:05 | Registrata; 2 in coda | Allertare sulle decorrenze arretrate; verificare conflitti tra assegnazioni e tracciamento prima/dopo. |
| `contratti_expiry_reminders` | Avvisa delle scadenze contratti a termine e periodi di prova. | ogni giorno, alle 07:50 | Registrata; 2 in coda | Configurare destinatari HR espliciti; correggere la descrizione del fallback amministrativo. |
| `elearning_reminders` | Sollecita corsi e-learning incompleti con notifiche e digest. | ogni giorno, alle 07:55 | Registrata; 2 in coda | Deduplicare per corso/persona e raccogliere completati dopo il sollecito. |
| `formazione_audit_digest` | Riepilogo trimestrale abilitazioni/formazione in scadenza. | il giorno 1 di gen/apr/lug/ott del mese, alle 08:00 | Registrata; 0 in coda | Destinatari HR/RSPP dedicati; evitare sovrapposizione col reminder giornaliero. |
| `formazione_session_reminders` | Ricorda le sessioni a T-7 e T-1 con invito ICS e notifica. | ogni giorno, alle 07:30 | Registrata; 2 in coda | Gestire anche iscrizioni tardive e recupero dopo fermo, evitando inviti per incontri passati. |
| `idoneita_digest` | Digest di idoneità negative o con riserve. | ogni lun, alle 07:00 | Registrata; 1 in coda | Verificare destinatari autorizzati e minimizzazione contenuti; esplicitare esito saltato senza destinatari. |
| `intake_referti_sanitari` | Acquisisce certificati dalla cartella scanner, se abilitato. | ogni 10 minuti | Registrata; 174 in coda | Segnalare share irraggiungibile e arretrato; conservare revisione umana dei dati estratti. |
| `intake_scansioni_formazione` | Associa fogli firme scansionati alla giornata tramite QR. | ogni 2 minuti | Registrata; 864 in coda | Coda dei non riconosciuti, deduplica documento e indicatore ultima scansione utile. |
| `training_expiry_reminders` | Promemoria formazione obbligatoria scaduta/in scadenza. | ogni giorno, alle 08:05 | Registrata; 2 in coda | Destinatari espliciti; verificare aggiornamento cache scadenze e limitare notifiche ripetute. |
| `visite_expiry_reminders` | Promemoria visite scadute/in scadenza ai referenti e dipendenti. | ogni giorno, alle 07:45 | Registrata; 2 in coda | Configurare destinatari HR espliciti e allineare il catalogo al fallback effettivo. |
| `visite_mediche_digest` | Riepilogo mensile visite in scadenza. | il giorno 1 del mese, alle 08:00 | Registrata; 0 in coda | Definire una finalità distinta dal reminder quotidiano o accorpare i due invii. |

Intervento tecnico: `anagrafica.tasks.run_attiva_assegnazioni_programmate`, `anagrafica.tasks.run_idoneita_digest`, `anagrafica.tasks.run_archivia_attestati_mancanti`, `anagrafica.tasks.run_intake_scansioni_formazione`, `anagrafica.tasks.run_intake_referti_sanitari`, `anagrafica.tasks.run_formazione_session_reminders`, `anagrafica.tasks.run_visite_expiry_reminders`, `anagrafica.tasks.run_contratti_expiry_reminders`, `anagrafica.tasks.run_formazione_audit_digest`, `anagrafica.tasks.run_visite_mediche_digest`, `anagrafica.tasks.run_training_expiry_reminders`, `anagrafica.tasks.run_elearning_reminders`.

## Assets / Manutenzione

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `assets_generate_occurrences` | Genera occorrenze dovute dai piani attivi; gli ordini di lavoro restano una scelta umana. | ogni giorno, alle 06:00 | Registrata; 2 in coda | Misurare piani senza occorrenze e recuperare scadenze perse dopo il fermo. |
| `assets_maintenance_reminders` | Avvisa di manutenzioni, verifiche periodiche e ordini scaduti. | ogni giorno, alle 07:00 | Registrata; 2 in coda | Responsabile per impianto e digest unico; verificare destinatari di ripiego. |
| `assets_reportistica` | Controlla report dovuti, crea snapshot/PDF/Excel e ritenta errori temporanei. | ogni minuto | Registrata; 1727 in coda | Una sola elaborazione concorrente per programma; distinguere report pronti, saltati ed errori. |
| `intake_verifiche_periodiche` | Importa fogli scanner con QR; gli esiti restano da confermare. | ogni 2 minuti | Registrata; 865 in coda | Evidenziare non riconosciuti/share indisponibile e bloccare import duplicati. |

Intervento tecnico: `assets.services.reporting.dispatch_due_reports`, `assets.tasks.run_periodic_check_intake`, `assets.tasks.run_generate_maintenance_occurrences`, `assets.tasks.run_maintenance_reminders`.

## DPI

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `dpi_expiry_reminders` | Avvisa DPI scaduti/in scadenza via email e portale. | ogni giorno, alle 07:10 | Registrata; 2 in coda | Instradare al responsabile effettivo, deduplicare e misurare sostituzioni dopo avviso. |

Intervento tecnico: `dpi.tasks.run_dpi_expiry_reminders`.

## RENTRI

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `rentri_scadenze_check` | Segnala registrazioni non confermate/trasmesse oltre soglia. | ogni giorno, alle 07:20 | Registrata; 2 in coda | Allineare con le regole evento RENTRI e rendere visibili soglie, destinatari e mancato invio. |

Intervento tecnico: `rentri.tasks.run_rentri_scadenze_check`.

## Ticket

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `tickets_daily_digest` | Digest dei ticket assegnati in scadenza oggi o scaduti. | ogni giorno, alle 07:40 | Registrata; 2 in coda | Accorpare con reminder SLA e verificare ticket senza assegnatario. |
| `tickets_escalation` | Aggiorna promemoria e, se abilitato, riepiloga urgenti non assegnati in orario lavorativo. | ogni giorno, ogni ora al minuto 0 | Registrata; 30 in coda | Misurare tempo alla presa in carico; escalation a sostituto e configurazione esplicita. |
| `tickets_sla_reminders` | Sollecita assegnatari per SLA scaduti. | ogni giorno, alle 08:30 | Registrata; 2 in coda | Unificare i messaggi con digest giornaliero; gestire pausa e calendario di servizio. |

Intervento tecnico: `tickets.tasks.run_tickets_escalation`, `tickets.tasks.run_sla_reminders`, `tickets.tasks.run_ticket_daily_digest`.

## Anomalie qualità

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `anomalie_cleanup_allegati` | Elimina cartelle orfane ferme da oltre 30 giorni, massimo 500 per giro. | ogni giorno, alle 03:45 | Registrata; 2 in coda | Anteprima e conteggio eliminabili; verificare riferimenti prima della cancellazione. |
| `anomalie_escalation` | Aggiorna promemoria OP e invia il resoconto all’ora configurata se abilitato. | ogni giorno, ogni ora al minuto 0 | Registrata; 30 in coda | Deduplicare rispetto alle regole evento e misurare OP presi in carico. |
| `anomalie_pending_notifications` | Invia riepiloghi dopo almeno 5 minuti senza modifiche. | ogni minuto | Registrata; 1727 in coda | Controllare ritardo reale del debounce; evitare raffiche al recupero della coda. |

Intervento tecnico: `anomalie.tasks.run_anomalie_pending_notifications`, `anomalie.tasks.run_anomalie_escalation`, `anomalie.tasks.run_anomalie_cleanup_allegati`.

## Gestione Specifiche

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `gestione_specifiche_escalation` | Escalation dopo 14 giorni ad approvatore e DM. | ogni giorno, alle 07:15 | Registrata; 2 in coda | Sostituti e conferma presa in carico; deduplica tra livelli di escalation. |
| `gestione_specifiche_reminder` | Sollecito dopo 7 giorni per MOD.133 non presi in carico, con pause previste. | ogni giorno, alle 07:00 | Registrata; 2 in coda | Mostrare timer e motivi di pausa; verificare recupero dei due run arretrati. |
| `gestione_specifiche_verifica_periodica` | Verifica ricorrente semestrale a partire dalla data verifica. | ogni giorno, alle 06:30 | Registrata; 2 in coda | Pannello scadenze e misurazione verifiche completate dopo promemoria. |

Intervento tecnico: `gestione_specifiche.tasks.run_specifiche_reminder`, `gestione_specifiche.tasks.run_specifiche_escalation`, `gestione_specifiche.tasks.run_specifiche_verifica_periodica`.

## Procedure / SGI

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `pr_assignment_lifecycle` | Marca scadute le prese visione oltre termine; invia reminder e digest se abilitati. | ogni giorno, alle 06:45 | Registrata; 2 in coda | Separare aggiornamento stato e consegna avvisi, con storico esiti e sostituzioni. |
| `pr_sgi_auto_sync` | Importa nuovi documenti e aggiornamenti ammessi dalla share senza sovrascrivere quelli protetti. | ogni giorno, alle 03:00 | Registrata; 2 in coda | Flag trovato acceso: verificare recupero, documenti scartati e concatenazione con indicizzazione. |
| `sgi_share_check` | Rileva differenze tra share e corpus importato e apre segnalazione informativa. | ogni giorno, alle 04:30 | Registrata; 2 in coda | Distinguere drift reale, documenti esclusi intenzionalmente e share irraggiungibile. |

Intervento tecnico: `procedure_refresh.tasks.run_sgi_share_check`, `procedure_refresh.tasks.run_sgi_auto_sync`, `procedure_refresh.tasks.run_assignment_lifecycle`.

## Monitoraggio

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `ai_readiness_alert` | Controlla servizi AI/readyz e avvisa sui cambi di stato. | ogni 15 minuti | Disabilitata esplicitamente | Disattivato: valutare riattivazione con destinatari e rate limit definiti. |
| `system_digest` | Digest giornaliero stato portale, automazioni, servizi e issue. | ogni giorno, alle 07:00 | Registrata; 2 in coda | Inviare watchdog fuori dal worker sorvegliato: questo digest è anch’esso arretrato. |

Intervento tecnico: `monitoring.tasks.run_system_digest`, `monitoring.tasks.run_ai_readiness_alert`.

## Assistente AI

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `ai_index_sgi_documents` | Prepara indice documentale SGI e cache embeddings prima dell’uso. | ogni giorno, alle 03:30 | Registrata; 2 in coda | Avviare dopo fine sincronizzazione, non solo a orario fisso; misurare documenti/chunk indicizzati. |
| `ai_rag_quality_alert` | Valuta qualità recupero SGI e segnala indice vuoto o qualità sotto soglia. | ogni giorno, alle 04:00 | Registrata; 2 in coda | Conservare metriche e campione di valutazione; distinguere indice vecchio da servizio indisponibile. |
| `ai_warmup_ollama` | Preriscalda il modello Ollama e rinnova il mantenimento in memoria. | ogni 25 minuti | Disabilitata esplicitamente | Disattivato: valutare necessità su latenza reale e memoria disponibile. |

Intervento tecnico: `ai_assistant.tasks.run_warmup_ollama`, `ai_assistant.tasks.run_index_sgi_documents`, `ai_assistant.tasks.run_rag_quality_alert`.

## KICK-OFF

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `tasks_meetings_digest` | Ricorda incontri del giorno dopo e sollecita problemi aperti degli incontri scaduti il lunedì. | ogni giorno, alle 17:00 | Registrata; 1 in coda | Recuperare solo avvisi ancora utili dopo il fermo e misurare risoluzione problemi. |
| `tasks_send_reminders` | Trasforma i promemoria attività dovuti in notifiche portale, con flag di invio. | ogni giorno, alle 07:30 | Registrata; 2 in coda | Mostrare reminder arretrati e controllare duplicazioni fra task ed eventi. |

Intervento tecnico: `tasks.tasks.run_send_task_reminders`, `tasks.tasks.run_meetings_digest`.

## Core / Reparti

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `caporeparto_morning_digest` | Riepiloga DPI in attesa e incidenti aperti del reparto ai capi. | da lun a ven, alle 07:00 | Registrata; 2 in coda | Allineare responsabilità HR e sostituzioni; dichiarare nella UI quali moduli sono coperti. |

Intervento tecnico: `core.tasks.run_caporeparto_morning_digest`.

## Motore automazioni

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `approval_mailbox` | Legge risposte di approvazione via Microsoft Graph e applica la decisione riconosciuta. | ogni 2 minuti | Registrata; 864 in coda | Misurare ultimo polling riuscito, messaggi non interpretabili e approvazioni scadute. |
| `automation_queue` | Processa eventi SQL e relative condizioni/azioni, normalmente a blocchi di 50. | ogni minuto | Registrata; 1727 in coda | Verificare gli esecutori concorrenti: eventi smaltiti ma oltre 1.700 invocazioni q in arretrato al campione. |
| `cleanup_run_logs` | Elimina RunLog oltre retention configurata, default 90 giorni. | ogni giorno, alle 03:30 | Registrata; 2 in coda | Preservare statistiche aggregate e verificare retention anche dei risultati django-q. |
| `report_scadenze_settimanale` | Riepilogo settimanale visite e contratti secondo impostazioni del modulo. | ogni lun, alle 06:00 | Registrata; 1 in coda | Accorpare con HR quotidiano/mensile e definire un unico owner per ciascuna scadenza. |

Intervento tecnico: `automazioni.tasks.run_automation_queue`, `automazioni.tasks.run_approval_mailbox`, `automazioni.tasks.run_report_scadenze_settimanale`, `automazioni.tasks.run_cleanup_run_logs`.

## Assenze

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `assenze_sharepoint_sync` | Sincronizza modifiche locali e delta SharePoint se Graph è configurato. | ogni 5 minuti | Registrata; 346 in coda | Chiarire fonte autorevole e convivenza; monitorare conflitti, coda push e ultimo delta. |

Intervento tecnico: `assenze.tasks.run_assenze_sharepoint_sync`.

## Checklist operativa

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `checklist_chiusura_reminders` | Ricorda task non confermati prima delle chiusure, alle soglie 7/3/1/0 giorni. | ogni giorno, alle 07:15 | Registrata; 2 in coda | Gestire sostituti e recupero dopo stop senza notifiche di chiusure già passate. |

Intervento tecnico: `checklist_operativa.tasks.run_checklist_chiusura_reminders`.

## Contatori / SNMP

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `contatori_letture_mensili` | Salva una lettura per macchina/mese senza sovrascrivere i trimestri. | il giorno 1 del mese, alle 08:00 | Registrata; 0 in coda | Verificare il primo run del 1 ottobre e recuperare solo macchine/mensilità mancanti. |
| `contatori_poll_snmp` | Pianifica il polling dei dispositivi attivi, un task per apparato. | ogni 5 minuti | Registrata; 345 in coda | Timeout per dispositivo, limite concorrenza e separazione dai reminder; indagare i sei fallimenti conservati. |

Intervento tecnico: `contatori.tasks.run_poll_snmp`, `contatori.tasks.run_letture_mensili`.

## Security Center

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `security_cycle` | Acquisisce report caselle Graph, esegue parser, regole, heartbeat e KPI. | ogni 15 minuti | Registrata; 116 in coda | Allarme di mancata acquisizione indipendente dal worker; misurare età ultima sorgente utile. |

Intervento tecnico: `security.tasks.run_security_cycle_task`.

## Suggestion Corner

| Automazione | Cosa fa | Quando | Stato al campione | Miglioramento |
|---|---|---|---|---|
| `suggestion_corner_reminders` | Sollecita fasi DO/CHECK ed escalation dei suggerimenti. | ogni giorno, alle 08:00 | Registrata; 2 in coda | Riepilogo per responsabile, sostituzione assenti e misurazione passaggi di fase. |

Intervento tecnico: `suggestion_corner.tasks.run_suggestion_corner_reminders`.

## Regole del designer — inventario completo

“Attiva” indica il flag e la pubblicazione, non l'effettiva alimentazione degli eventi. `last_run_at` registra anche valutazioni saltate: non equivale a un invio. Nella finestra di sette giorni le regole 6 e 18 hanno un successo reale ciascuna; 5, 7 e 9 hanno una valutazione saltata ciascuna; la 4 ha un test riuscito. Nessun errore regola nella finestra interrogata.

| Modulo / ID | Regola | Funzione | Stato | Ultima valutazione UTC |
|---|---|---|---|---|
| anagrafica_visite_mediche / 17 | `au29-visita-non-idonea-notifica` | Cambio esito visita a non idoneità: email. | Attiva | Nessuna registrata |
| anomalie / 10 | `au41-anomalia-creata-notifica` | Nuova anomalia: email. | Bozza disattiva | Nessuna registrata |
| anomalie / 15 | `au41-anomalia-creata-notifica-2` | Seconda regola nuova anomalia: email. | Bozza disattiva | Nessuna registrata |
| anomalie / 29 | `au-mail-anomalie-cc-car-insert` | Inserimento anomalia: mail-action nativa, con filtro OP e cooldown. | Attiva | 2026-07-23 14:12:01.4181160 +00:00 |
| anomalie / 30 | `au-mail-anomalie-cc-car-update` | Aggiornamento anomalia: chiamata HTTP, con filtro OP e cooldown. | Attiva | 2026-07-23 14:14:56.4660470 +00:00 |
| anomalie / 32 | `au51-anomalia-creata-mail-action-op-2` | Azione manuale: mail-action per OP. | Attiva | Nessuna registrata |
| assenze / 4 | `assenze-pa-richiesta-approvazione-caporeparto` | Richiesta assenza senza salto approvazione: approvazione al capo; rami con aggiornamento record, split giornaliero, email e log. | Attiva | 2026-09-16 06:50:49.1134020 +00:00 |
| assenze / 5 | `assenze-pa-skip-approvazione-avviso-inserimento` | Assenza con salto approvazione: aggiornamento record, split giornaliero, email e log. | Attiva | 2026-09-29 10:33:53.7692270 +00:00 |
| assenze / 6 | `assenze-pa-approvata-avviso-inserimento` | Assenza approvata: email di avviso e log. | Attiva | 2026-09-29 10:55:55.6126600 +00:00 |
| assenze / 7 | `assenze-pa-assemblea-sindacale-avviso` | Assemblea sindacale al cambio approvazione: email. | Attiva | 2026-09-29 10:55:55.6437830 +00:00 |
| assenze / 8 | `assenze-pa-flessibilita-avviso` | Flessibilità al cambio approvazione: email. | Disattiva | 2026-09-16 06:51:51.5971510 +00:00 |
| assenze / 9 | `assenze-pa-malattia-avviso-capo` | Malattia con email capo disponibile: email e log. | Attiva | 2026-09-29 10:33:53.8129490 +00:00 |
| assenze / 16 | `au13-ferie-lunghe-doppia-approvazione` | Ferie lunghe: richiesta approvazione; soglia da validare nel designer. | Bozza disattiva | Nessuna registrata |
| assenze / 18 | `au-assenze-unico-branch-per-tipo` | Assenza senza salto approvazione: ramificazione per tipo con email e approvazione nei rami. | Attiva | 2026-09-29 10:33:55.4956200 +00:00 |
| diario_preposto / 14 | `au34-segnalazione-preposto-followup-rspp` | Nuova segnalazione preposto: attesa programmata e successiva email. | Attiva | Nessuna registrata |
| rentri / 13 | `au31-scarico-senza-fir-notifica` | Scarico senza FIR: email. | Attiva | Nessuna registrata |
| rentri / 19 | `rentri-invio-carico` | Nuovo carico RENTRI: email; il nome non dimostra invio al servizio RENTRI. | Disattiva | Nessuna registrata |
| rentri / 20 | `pa-rentri-nuovo-carico-notifica` | Nuovo carico salvato: email e log. | Attiva | Nessuna registrata |
| rentri / 21 | `pa-rentri-carico-non-trasmesso-promemoria-5g` | Carico non trasmesso e salvato: ciclo do_until con email/log; intervallo dichiarato nel nome 5g, da collaudare. | Attiva | Nessuna registrata |
| rentri / 22 | `pa-rentri-scarico-senza-fir-promemoria-30g` | Scarico senza FIR salvato: ciclo do_until con email/log; intervallo dichiarato nel nome 30g, da collaudare. | Bozza disattiva | Nessuna registrata |
| rilevazione_incidenti / 11 | `au3-incidente-approvazione-rls-rspp` | Nuovo incidente: richiesta approvazione RLS/RSPP. | Disattiva | Nessuna registrata |
| rilevazione_incidenti / 12 | `au3-incidente-approvazione-rls-rspp-2` | Seconda regola incidente con richiesta approvazione. | Bozza disattiva | Nessuna registrata |
| tickets / 1 | `tickets-nuovo-critico-notifica-operativa` | Nuovo ticket critico: email operativa e log. | Attiva | 2026-09-18 11:13:54.0999850 +00:00 |
| tickets / 2 | `tickets-nuovo-impatto-sicurezza-notifica-rspp` | Nuovo ticket con impatto sicurezza: email RSPP e log. | Bozza disattiva | Nessuna registrata |
| tickets / 3 | `tickets-cambio-stato-email-richiedente` | Cambio stato ticket con email richiedente disponibile: email e log. | Attiva | Nessuna registrata |

### Dove intervenire sulle regole

- **Assenze:** regole 4 e 18 condividono il caso senza salto approvazione e non hanno gruppo esclusione; 7 e 6 possono entrambe valutare un'approvazione. È un rischio di doppio percorso/invio da verificare su casi sintetici, non un duplicato dimostrato. Scegliere flusso autorevole e casi esclusivi, senza disattivare in produzione alla cieca. Verificare capo mancante e rami di errore.
- **Anomalie:** rimuovere l'ambiguità delle bozze 10/15 dopo validazione; uniformare, se opportuno, l'azione nativa 29 con la chiamata HTTP 30, mantenendo cooldown e destinatari. La 32 è manuale: non aspettarsi partenza su inserimento. Ultimi eventi coda osservati a luglio: verificare fonte delle modifiche recenti e flussi alternativi prima di diagnosticare perdita eventi.
- **Ticket:** mantenere distinta urgenza da impatto sicurezza; la regola RSPP è una bozza disattiva. Validare la sorgente del cambio stato: la 3 è attiva ma senza ultima esecuzione registrata.
- **Visite mediche:** collegare evento esito alla regola 17 e definire destinatari autorizzati. Il trigger SQL sulla tabella non è presente.
- **Diario preposto:** collegare la sorgente della 14 e chiarire ritardo, presa in carico e cancellazione sollecito dopo chiusura. Nessun trigger SQL sulla tabella.
- **RENTRI:** collegare la sorgente prima di confidare nelle regole 13/20/21. La 21 parte su UPDATE, quindi un carico mai modificato potrebbe non avviare il ciclo: verificare copertura del job giornaliero. Consolidare regole 19/20 e attivare la 22 soltanto dopo collaudo. Nessun trigger SQL sulla tabella.
- **Incidenti:** entrambe le approvazioni del designer sono disattive, una in bozza. Questo non dimostra che manchi il workflow nativo del modulo; definire se queste regole sono ancora richieste e collaudare il percorso scelto.

## Automatismi interni e moduli senza job dedicati

- **Sistema Gestione / Audit:** il codice distribuito include generazione assistita di checklist, salvataggio bozze, riepiloghi fattuali, proposte di priorità e revisione documentale. Sono azioni legate al lavoro dell'utente, non job periodici del catalogo. Miglioramento: tracciare adozione delle proposte e completezza delle evidenze. Non attribuire alla produzione le successive estensioni procedure/CAR/KPI presenti nel repository dopo `c4ead42`.
- **Incidenti e Diario preposto:** oltre alle regole sopra, il digest caporeparto copre incidenti aperti. Non è stato svolto un collaudo end-to-end dei workflow nativi.
- **Timbri, Notizie, Planimetria, dashboard, admin_portale, setup_wizard, hub_tools:** nessun job dedicato nel catalogo dei 48 e nessuna regola designer dedicata nel campione. Non significa assenza di automatismi al salvataggio o comandi esterni: quelli Windows/servizi non sono stati inventariati, perché WinRM non è raggiungibile.

## Verifiche, fonti e limiti

- Fonti: `Y:/current/BUILD_INFO.json`; codice effettivamente distribuito `automazioni/schedules.py`, `tasks.py`, `source_registry.py`, `system_runlog.py`, `config/settings/base.py`, comandi reminder HR e servizio `anagrafica/services/reminders.py`.
- SQL: sole SELECT su metadati, pianificazioni/controlli, conteggi broker, esiti aggregati, definizioni regole/azioni/condizioni, stati approvazioni e trigger. Connessione ODBC richiesta read-only, transazione chiusa con rollback; nessuna esecuzione di job o Django startup.
- Payload broker analizzati localmente solo tramite opcodes `pickletools`, senza eseguire deserializzazione pickle e senza esportare contenuti: nel documento sono riportati esclusivamente conteggi per funzione nota. Una voce non classificata; nessuna attribuzione inventata.
- Risultati e stati cambiano nel tempo; fotografia non transazionale tra tutte le query. L'indagine non prova consegna email, correttezza dei destinatari, salute di ogni dispositivo o causa definitiva del fermo.
- `core_siteconfig` non contiene le chiavi destinatari HR cercate; non equivale a “nessun destinatario”: il servizio comune contempla ADMINS/superuser. I valori degli indirizzi non sono stati estratti. L'unico flag trovato nella selezione reminder/intake/escalation/SGI è `pr_sgi_auto_sync_attivo=1`; le altre funzioni possono avere impostazioni in modelli dedicati o default.
- Nessun log grezzo, credenziale, messaggio email, nominativo o referto incluso. Nessuna modifica a produzione, configurazione, ACL, database o invio messaggi. Nessun test con effetti reali.

## Chiusura sessione

- Modifiche: solo questo rapporto, registro agente e checkpoint in worktree dedicato.
- File critici modificati: nessuno. Backup aggiuntivi: nessuno (produzione invariata).
- README / CHANGELOG: non aggiornati, comportamento operativo invariato. AGENT_CHANGELOG / checkpoint: aggiornati.
- Verifiche: confronto catalogo/DB e stati; copertura 48 job + 25 regole; controllo differenze whitespace. Suite applicative non necessarie per sola documentazione.
- Esito: inventario completato; criticità runtime aperta. Note altro agente: partire da P0, verificare esecutori reali prima di ripulire broker o modificare scheduling; implementazioni e deploy separati.
