# MANUTENZIONE — APPROFONDIMENTO (modulo `assets`)

Analisi statica del dominio manutenzione + ricerca di pattern CMMS. Data: 2026-07-14. Sola lettura, nessuna modifica, nessun test eseguito.
Complementare a `MIGLIORAMENTI_ASSETS.md`: i finding S1-S6, C1-C6, D1-D4, F11, U1-U3 **non** sono ripetuti; dove servono sono richiamati per ID.

## Executive summary

Il motore c'è ed è migliore di quanto ci si aspetti da un modulo interno: scadenzario unico regole+contatori, generazione automatica di OdL, checklist da template, reminder email **realmente schedulati** (django-q2 cron 06:00 + 07:00, `automazioni/schedules.py:356-376` — non è una regola dormiente come fu per la skill matrix). Ma sul rischio vero — *"una scadenza mancata = macchina ferma o NC in audit"* — ci sono **cinque buchi**, tutti a basso costo di chiusura:

1. **Le scadenze già scadute spariscono dai reminder.** Il comando filtra `due_date__gte=today` per le scadenze amministrative e `next_verification_date__gte=today` per le verifiche periodiche (`send_maintenance_reminders.py:83-100`): il giorno **dopo** la scadenza, la mail smette di parlarne. L'unico modulo che segnala le scadute è lo scadenzario rule-based (righe 116-129). È esattamente il contrario di ciò che serve: una scadenza superata deve gridare di più, non sparire (M1).
2. **Il ritardo si assorbe sempre, mai si recupera.** Sia le regole (`maintenance.py:460-468`) sia le verifiche (`views.py:13939-13945`, `models.py:1392-1395`) ricalcolano la prossima scadenza dalla data **reale** di esecuzione: è uno schedule *floating* al 100%, senza alcuna possibilità di schedule *fisso*. Per una verifica di legge/taratura annuale, 12 esecuzioni con 20 giorni di ritardo l'una spostano la scadenza di ~8 mesi senza che nessun indicatore lo registri (M2).
3. **La manutenzione a contatore non scatta se nessuno aggiorna il contatore**, e nessuno se ne accorge: lo stato `missing` ("Contatore h mancante", `maintenance.py:331-340`) è indistinguibile in gravità da "da pianificare", il generatore lo salta e basta (`generate_scheduled_workorders.py:167-170`, contatore `skipped_no_meter`), non esiste alcun alert "contatore fermo da N giorni" (M3).
4. **Nessuna escalation e nessuna notifica personale.** Gli OdL aperti da >21gg finiscono in una mail a una lista generica (SiteConfig `assets_reminder_emails` → ADMINS → superuser); il **manutentore assegnato non riceve nulla**, né alla creazione né all'assegnazione né allo scadere (nessuna chiamata a `invia_notifica*` in tutto `assets/` fuori dal reminder). Un OdL può restare aperto per sempre: non c'è stato "in ritardo", non c'è escalation a un responsabile (M4).
5. **La taratura (`KIND_CALIBRATION`) è solo un'etichetta.** Nessun flusso distinto: niente esito conforme/non conforme, niente certificato obbligatorio, nessuna valutazione dell'impatto sui prodotti misurati con uno strumento trovato fuori tolleranza — che è precisamente ciò che ISO 9001 §7.1.5 chiede di poter dimostrare (M5).

Per l'audit ISO 9001/AS9100 la tracciabilità *dell'eseguito* è buona (chi/quando/cosa/costi/allegati/checklist, e l'OdL non è modificabile dopo la creazione). Quello che oggi **non si può dimostrare in audit** è: (a) il tasso di rispetto del piano (PM compliance), (b) che le scadenze superate siano state gestite e non semplicemente dimenticate, (c) la catena "strumento fuori tolleranza → prodotti impattati".

---

## PARTE A — ANALISI INTERNA

### A1. Ciclo di vita dell'intervento

**Stati.** `WorkOrder.status` ha 3 valori: OPEN / DONE / CANCELED (`models.py:1820-1827`). Nessuno stato intermedio (assegnato, in corso, sospeso in attesa ricambi/fornitore) e nessuno stato di *ritardo*. La presa in carico è tracciata dal solo campo `assigned_to` (`workorder_claim`, `views.py:15153-15189`), che non cambia lo stato — scelta dichiarata nel docstring e sensata, ma significa che **"aperto da 3 giorni, nessuno l'ha guardato" e "aperto da 3 giorni, il tecnico ci sta lavorando" sono lo stesso stato** in ogni lista e KPI.

**Chi apre.** Tre strade, con `origin` diverso (`models.py:1829-1836`): il generatore automatico (`ORIGIN_PERIODIC`), l'utente da form (`workorder_create`, `views.py:14909`, `ORIGIN_MANUAL` di default), e i ticket MAN (`ORIGIN_TICKET`, FK `WorkOrder.ticket` `models.py:1867`). Nota: `origin` è impostato correttamente solo dal generatore; il difetto della registrazione rapida che nasce MANUAL è già C1 in MIGLIORAMENTI_ASSETS.

**Chi chiude.** `workorder_close` (`views.py:15193`), aperto a qualsiasi utente autenticato (vedi S3). Il form di chiusura è ricco e ben pensato: esito (chiusa/annullata), risoluzione, durata, **fermo impianto**, costi manodopera/materiali/override, contratto di copertura, `assigned_to` **e** `executed_by` distinti, nota di chiusura (`forms.py:2722-2760`). Distinguere "assegnato a" da "eseguito da" è una finezza che i CMMS commerciali spesso non hanno — buon punto per l'audit ("chi ha materialmente eseguito").

**Se resta aperto indefinitamente: non succede nulla.** Verifiche fatte:
- Nessun campo `due_date`/`target_date` sull'OdL: un OdL non ha una data entro cui va chiuso, solo `opened_at`. Il concetto di "OdL in ritardo" esiste **solo** come soglia di anzianità di 21 giorni calcolata al volo in due punti scollegati: il cockpit (`views.py:15514` `overdue_threshold = today - 21gg`) e il reminder (`send_maintenance_reminders.py:66,79`, parametro `--wo-overdue-days`). Due costanti gemelle, nessuna configurazione condivisa.
- **Nessuna escalation**: l'OdL vecchio finisce in un elenco dentro la mail collettiva. Nessun destinatario diverso al crescere del ritardo, nessuna notifica al responsabile, nessun cambio di stato/priorità. *(assenza = finding: M4)*
- **Nessuna priorità/criticità** sull'OdL né sull'asset: tutti gli interventi pesano uguale. Un fermo su una macchina di produzione critica e la sostituzione di un filtro competono per la stessa attenzione. *(assenza = finding)*

**Preventiva vs correttiva vs taratura: flussi identici.** `kind` (`models.py:1812-1818`) è un `CharField` con 5 scelte usato **solo** per: colore del badge (`views.py:1371-1385`), etichetta (`9531`), filtro lista (`_apply_workorder_list_filters`), breakdown nei KPI (`services/dashboard_kpi.py:522,656`), e come valore precompilato (`KIND_PREVENTIVE` quando l'OdL nasce da una regola, `maintenance.py:183`). Nessuna differenza nel form, nella chiusura, nei campi obbligatori, nelle notifiche.
- **Correttiva**: nessun campo per causa del guasto/modo di guasto → l'analisi dei guasti ricorrenti (e qualsiasi MTBF/Pareto per causa) è impossibile per costruzione. *(assenza = finding)*
- **`KIND_CALIBRATION`**: nessun esito conforme/non conforme, nessun campo per lo strumento/certificato/tolleranza, nessun obbligo di allegato. Formalmente indistinguibile da "Altro" (M5). Le tarature oggi vivono più probabilmente come `AssetAdministrativeDeadline` di tipo CERTIFICATE + allegato al completamento (`models.py:727-866`) — che è un buon veicolo documentale ma non un flusso di taratura.
- **`KIND_SAFETY`**: idem, nessun trattamento speciale.

**Ricostruibilità a posteriori (audit ISO).** Cosa esiste davvero:
- `WorkOrderLog` (`models.py:2125-2141`) con autore+timestamp, alimentato in 4 punti: creazione (`views.py:14963`), nota manuale (`15037`), presa in carico (`15183`), chiusura con eventuale nota (`15245`).
- `WorkOrderChecklist` con `is_done`/`done_at`/`done_by` per singolo step (`models.py:2144-2176`) — **questa è la prova d'oro in audit**: dimostra quali passi del template sono stati eseguiti, da chi, quando.
- Allegati (`WorkOrderAttachment`) con `uploaded_by`; costi, durata, fermo; `executed_by`; `meter_value_at_close`.
- **Immutabilità**: non esiste una view di *modifica* dell'OdL (in `urls.py:94-104` ci sono list/new/view/close/claim/checklist, **nessuna edit**): titolo, descrizione, asset e regola sono fissati alla creazione. Ottimo per l'audit, probabilmente non intenzionale.

Cosa **manca** per un audit rigoroso:
- Il log non copre le modifiche ai campi (chiusura riscrive costi/risoluzione senza diff; e vedi C3: l'OdL è ri-chiudibile, il che sovrascrive `closed_at` **senza traccia**).
- Nessuna firma/conferma di validazione (né digitale né "approvato da"): chi chiude è anche chi valida.
- Nessuna nozione di *ritardo rispetto al piano*: dall'archivio si può ricostruire quando un intervento è stato fatto, **non** quando avrebbe dovuto essere fatto. In audit questa è la domanda difficile (vedi §B3).

### A2. Scadenze — il cuore del rischio

**Come si calcola la prossima scadenza (regole a giorni).** `build_maintenance_schedule_rows` (`maintenance.py:460-468`): `due_date = AssetMaintenanceRuleState.last_execution_date + threshold_value giorni`. `last_execution_date` è la data **reale** di chiusura dell'OdL (`sync_workorder_maintenance_state`, `maintenance.py:243-254`). Se non c'è mai stata un'esecuzione: `due_date = None` → stato `missing` "Prima esecuzione da pianificare" (`maintenance.py:258-264`), e il generatore la tratta come dovuta subito (`generate_scheduled_workorders.py:156`).

**Come si calcola (verifiche periodiche).** `next_verification_date = _add_months(executed_on, frequency_months)` sia nel salvataggio del modello (`models.py:1392-1395`) sia alla registrazione dell'esecuzione (`views.py:13939-13945`) — con la guardia sensata `if previous_last is None or executed_on >= previous_last` (non si torna indietro registrando un'esecuzione vecchia).

**→ M2 · Schedule 100% floating, ritardo sempre assorbito, drift invisibile.** In entrambi i casi il calcolo parte dalla data reale, mai dalla data teorica. Conseguenze:
- Il ritardo **non si accumula mai** (nessun rischio di "catch-up impossibile", che è il pregio del floating).
- Ma **la data teorica non esiste da nessuna parte**: nessun campo conserva "quando sarebbe dovuta scadere". Quindi (a) lo slittamento progressivo è invisibile — una verifica annuale eseguita ogni anno con 30gg di ritardo migra di un mese all'anno senza che nulla lo segnali; (b) è **impossibile calcolare la PM compliance** (§B1), che è la metrica che un auditor chiede per prima; (c) per gli adempimenti a data fissa (verifiche di legge, tarature con validità certificata) il comportamento è **sbagliato**: lì la scadenza è un fatto esterno, non una conseguenza di quando siamo riusciti a fare il lavoro. Oggi il sistema non sa distinguere i due casi: `MaintenanceRule` non ha un flag "schedule fisso vs floating".

**Notifiche/reminder: esistono e sono davvero schedulati** (verificato, non è una regola dormiente):
- `automazioni/schedules.py:356-366` → `assets_generate_workorders`, cron `0 6 * * *`, `assets.tasks.run_generate_scheduled_workorders`.
- `automazioni/schedules.py:367-376` → `assets_maintenance_reminders`, cron `0 7 * * *`, `assets.tasks.run_maintenance_reminders`. Ordine corretto (genera prima, avvisa dopo — commento esplicito nel codice e in `tasks.py:18-20`).
- Il comando (`send_maintenance_reminders.py`) copre 4 sezioni: scadenze amministrative, verifiche periodiche, OdL aperti in ritardo, manutenzioni da regole; manda una mail HTML (`send_hub_mail`) **e** crea notifiche in-app (`invia_notifica_email`, righe 203-237) con deep-link corretti.

Ma con quattro difetti concreti:

**→ M1 · Le scadenze SCADUTE non sono nei reminder.** `due_date__gte=today` (righe 85-86) e `next_verification_date__gte=today` (righe 96-97): il filtro è una **finestra futura**. Il giorno dopo la scadenza, la scadenza amministrativa e la verifica periodica **escono dalla mail e restano solo nelle pagine "pull"**. L'unica sezione che include le scadute è quella rule-based (`status in ("overdue","warning")`, riga 119). Effetto pratico: la scadenza che nessuno ha visto in tempo è anche quella di cui il sistema smette di parlare. È il finding più grave della sezione, ed è un fix da due righe.

**→ M6 · Il reminder conta le verifiche legacy che il resto del sistema esclude.** Il cockpit e i KPI filtrano `is_legacy=False` per non contare due volte le verifiche ora gestite dalle regole (`views.py:15580-15585`, con commento esplicito). Il reminder **non lo fa** (`send_maintenance_reminders.py:93-100`): la stessa manutenzione può comparire due volte nella mail (come verifica legacy e come regola).

**→ M7 · Rumore: la stessa mail ogni giorno, a tutti, senza stato di presa visione.** Il docstring lo dichiara: *"Idempotente: eseguire più volte nello stesso giorno invia più email (nessun flag fired)"* (`send_maintenance_reminders.py:17`). Con 30 giorni di anticipo, la stessa scadenza è nella mail per 30 mattine consecutive, identica. È il meccanismo canonico con cui una mail di alert diventa invisibile.

**→ M4 · Destinatari generici, non le persone.** `resolve_reminder_recipients(config_key="assets_reminder_emails")` (riga 34-38): lista fissa → ADMINS → superuser. Un OdL assegnato a un manutentore compare nella mail **del gruppo**, non arriva a lui. `WorkOrder.assigned_to` esiste dal `0071` ma non è mai usato come destinatario: fuori dal reminder, in tutto `assets/` **non c'è una sola chiamata a `invia_notifica*`**. Nessuna notifica alla creazione, all'assegnazione, alla presa in carico o all'imminenza.

**Cosa succede a un asset con verifica scaduta: nulla, resta scaduto in silenzio.** Verificato: nessun blocco, nessun cambio di `Asset.status`, nessun flag di non-conformità, nessuna barra rossa che segua l'asset. Il segnale è: (a) una riga rossa nello scadenzario e nel cockpit, (b) fino al giorno della scadenza, una riga nella mail. L'asset resta usabile, assegnabile, pianificabile in produzione (il modulo carichi macchina non consulta lo stato manutenzione: nessun riferimento a `WorkOrder`/scadenze in `gestione_carichi_macchina/integrations.py`). Per una macchina con verifica di sicurezza scaduta questo è, in audit, la domanda scomoda: *"cosa impedisce di usarla?"* → oggi: niente. *(assenza = finding: M8)*

**Chi vede cosa, con che anticipo:**
| Canale | Chi | Anticipo | Pull/Push |
|---|---|---|---|
| Cockpit "Da fare" (`maintenance_hub`, views.py:15496) | non-admin: **solo i propri OdL** (15536-15537); admin: tutto | 7/14/30gg | pull |
| Scadenzario "Prossime" (`maintenance_schedule`) | tutti gli autenticati | tutto l'orizzonte | pull |
| Dashboard/widget, calendario asset | tutti | 30/90gg | pull |
| Mail reminder + notifica in-app | lista SiteConfig / ADMINS | `assets_reminder_days` (default 30); `warning_days` per regola (default 15, `models.py:954`) | **push** |
| QR landing su macchina | chiunque abbia il QR | scadenze azionabili dell'asset | pull (ma nel posto giusto: in officina) |

L'anticipo è configurabile a due livelli (globale SiteConfig, per-regola `warning_days`) — buono. Il difetto è che **il push è collettivo e il pull è personale**: l'unico che vede "i miei interventi" deve andarseli a cercare.

### A3. Regole a contatore

**Se il contatore non viene aggiornato, la manutenzione non scatta — e nessuno lo sa.**
- Nello scadenzario: contatore assente → `meter_schedule_payload(current_value=None)` → stato `missing`, badge `muted`, etichetta "Contatore h mancante" (`maintenance.py:331-340`). È in fondo all'ordinamento (`status_order[SCHEDULE_MISSING] = 3`, `maintenance.py:515-520`) e grigio: la regola più pericolosa (non so nemmeno *se* è scaduta) è visivamente la meno urgente.
- Nel generatore: `if current_val is None: skipped_no_meter += 1; continue` (`generate_scheduled_workorders.py:167-170`). Il conteggio finisce nel summary a stdout del task django-q — cioè in nessun posto che qualcuno legga.
- Nel reminder: la sezione regole prende solo `overdue`/`warning` (`send_maintenance_reminders.py:118-120`) → **`missing` non è mai notificato**. Una manutenzione a 500 ore su una macchina il cui contatore non è mai stato creato è, dal punto di vista di ogni canale attivo, *inesistente*.
- Caso peggiore e realistico: contatore **creato ma fermo** (nessuno lo aggiorna da 6 mesi). Qui non c'è nemmeno lo stato `missing`: il sistema calcola serenamente `remaining = soglia - consumato` su un valore vecchio e dice "Restano 320 h" — **una scadenza falsa presentata come verde** (`maintenance.py:365-373`). Questo è il rischio più insidioso di tutta la sezione.

**Alert "contatore non aggiornato da N giorni": NON esiste** (verificato: nessuna logica di staleness in `assets/`; `AssetMeter.updated_at` è mostrato solo come testo informativo nel pannello, `templates/assets/components/asset_meter_panel.html:57`). *(assenza = finding: M3)*

Nota di contesto: l'aggiornamento è **manuale** (pannello HTMX, `views.py:15299`), quindi la staleness non è un'ipotesi teorica — è lo scenario base. E il suo audit è rotto (S4 in MIGLIORAMENTI_ASSETS: `log_action` con firma sbagliata → nessuna traccia di chi ha scritto quel numero).

---

## PARTE B — RICERCA: cosa fanno i CMMS maturi che noi non facciamo

Vincolo rispettato: nessuna proposta di adottare un CMMS esterno. Ogni voce è valutata per *senso a questa scala* (parco macchine da decine di asset, team manutenzione piccolo) e *effort nel codice esistente* (S/M/L).

### B1. PM compliance rate — la metrica che manca (e che l'auditor chiede)

Standard di settore: la percentuale di PM completati **entro la finestra pianificata**; PM chiuso oltre ~7 giorni dalla data teorica = non conforme; benchmark SMRP "world class" ≥90%, sotto l'80% il programma è considerato non funzionante ([eWorkOrders, PM KPIs](https://eworkorders.com/preventive-maintenance/preventive-maintenance-kpis/); [Micromain, 12 Maintenance KPIs](https://micromain.com/maintenance-kpis/)).

Da noi: **impossibile da calcolare**, perché la data teorica non è mai persistita (M2). Abbiamo MTTR (`services/dashboard_kpi.py:381-420`), costi, downtime, backlog per tipo — cioè le metriche *lagging* — e zero metriche *leading*, che sono quelle che prevengono il fermo. Le fonti sopra sono esplicite: chi misura solo lagging reagisce, non previene.

**Senso per NOVICROM: sì, alto.** È l'unico numero che in audit risponde a "dimostrami che il piano di manutenzione viene rispettato", ed è anche quello che dice al responsabile se il team sta reggendo. **Effort: M** — richiede di persistere la data teorica (vedi B2) e poi è una query.

### B2. Schedule fisso vs floating: serve la scelta, non un default

Distinzione standard nei CMMS: *fixed* (la prossima scadenza è la data di calendario, indipendente da quando hai finito) vs *floating* (intervallo che riparte dal completamento reale) — e la raccomandazione ricorrente è **entrambi, scelti per asset/attività**: floating per lubrificazioni/ispezioni di routine, fisso per asset critici, vincoli normativi, finestre strette. Il rischio esplicito del floating puro è lo *schedule drift* ([Sockeye, Floating Maintenance Schedule](https://www.getsockeye.com/blog/floating-maintenance-schedule/); [SM Global](https://www.smglobal.com/blog/preventive-maintenance-schedule-maintenance-calendar/)).

Da noi: floating puro, imposto, senza alternativa (M2).

**Senso per NOVICROM: sì.** Non tutto il parco è uguale: la verifica di legge del carroponte e il cambio olio di un CNC non hanno la stessa natura. **Effort: M** — un flag `schedule_mode` su `MaintenanceRule` (+ override per asset, il meccanismo esiste già) e un campo `planned_due_date` su `AssetMaintenanceRuleState`/`WorkOrder` da cui derivano sia il calcolo fisso sia la PM compliance (B1). I due interventi condividono lo stesso pezzo di modello: farli insieme.

### B3. Ciò che un audit ISO 9001 / AS9100 pretende

- **§7.1.3 Infrastruttura**: mantenere l'infrastruttura necessaria; in audit si chiedono *record di manutenzione, rapporti di intervento, log di ispezioni/riparazioni*, chi è responsabile, con quale competenza, e come è gestita l'assistenza esterna (contratti/AMC) ([Core Solutions, Clause 7.1.3](https://www.thecoresolution.com/clause-7-1-3-iso-9001-explained); [Apogee QMS, AS9100 7.1.3](https://aqms.space/2023/04/as9100-clause-7-1-3-infrastructure); [Pretesh Biswas](https://preteshbiswas.com/2023/08/30/iso-90012015-clause-7-1-3-infrastructure/)). *Non c'è un obbligo esplicito di tenere i record, ma — testuale — è difficile dimostrare di seguire un programma se i record non esistono.*
  → **Qui siamo messi bene**: OdL non modificabili, log con autore, checklist spuntata per step, allegati, contratti di assistenza con fornitore. Il buco è la **competenza dell'esecutore** (`executed_by` è un `User`, senza collegamento alle abilitazioni/skill matrix già presenti in HUB) e la **prova del rispetto del piano** (B1).
- **§7.1.5 Risorse di monitoraggio e misurazione (tarature)**: identificare lo stato di taratura, conservare i certificati, e — il punto duro — se uno strumento è trovato **fuori tolleranza**, valutare la validità delle misure fatte in precedenza e agire di conseguenza (fino al richiamo del prodotto) ([Core Solutions, Clause 7.1.5](https://www.thecoresolution.com/clause-7-1-5-iso-9001-explained); [Richard Randall, Auditing 7.1.5](https://richardrandall.com/doku.php?id=articles:auditing_7.1.5); [Wilkshire Consulting](https://www.wilkshireconsulting.com/single-post/in-depth-calibration-requirements-for-iso-9001-2015)).
  → **Qui siamo scoperti** (M5): `KIND_CALIBRATION` non ha esito, non ha certificato obbligatorio, non ha "fuori tolleranza", e non esiste alcun aggancio tra uno strumento e ciò che ha misurato. Attenzione a non sovradimensionare: se gli strumenti di misura sono gestiti fuori dall'HUB (esiste una nota di fattibilità "strumenti di misura" nel progetto), la risposta corretta può essere *"questo dominio non vive qui"* — ma allora `KIND_CALIBRATION` andrebbe rimosso dalle scelte per non promettere ciò che non fa.

### B4. Meter-based: fallback a calendario e reminder di lettura

Pattern consolidato per il problema esatto di M3: (a) **trigger ibrido** — la stessa attività ha una soglia a contatore *e* un backstop a calendario, scatta il primo che arriva; (b) **reminder di lettura contatore** per gli asset a lettura manuale; il caso "il contatore smette di fluire e l'asset supera la soglia senza che nessuno se ne accorga" è citato come il rischio principale del meter-based puro ([MaintainX, Meter-Based Maintenance Best Practices](https://www.getmaintainx.com/blog/meter-based-maintenance-best-practices); [Oxmaint, Calendar vs Meter-Based](https://oxmaint.com/article/calendar-vs-meter-based-maintenance)).

**Senso per NOVICROM: sì, altissimo** — con lettura manuale è *il* fallimento probabile. **Effort: S/M.** Il fallback a calendario è un campo in più su `MaintenanceRule` (soglia contatore + `max_days` di sicurezza) e poche righe nel motore già unificato; il reminder di lettura è una sezione in più nel comando esistente. Da fare entrambi.

### B5. Escalation e notifiche per ruolo

Standard nei CMMS: notifiche diverse per tipo di OdL e **escalation automatica** verso il livello superiore quando un intervento resta aperto oltre una soglia; soglie di riordino con alert automatici sui ricambi ([Atlas CMMS](https://atlas-cmms.com/features/work-orders); [eWorkOrders, beyond work orders](https://eworkorders.com/10-things-you-didnt-know-modern-cmms-systems-can-do-beyond-work-orders/)).

Da noi: niente escalation (M4). **Senso: sì, ma in versione minima** — con un team piccolo bastano due livelli (assegnatario → responsabile manutenzione), non una piramide. **Effort: S**, perché l'infrastruttura c'è tutta: `core.notifiche` con registro tipi e preferenze per categoria, e nel progetto esiste già un precedente identico e funzionante (`run_tickets_escalation`). Il pezzo mancante è solo *chi è il responsabile manutenzione* (una chiave SiteConfig basta).

### B6. Firma/e-signature alla chiusura

Alcuni CMMS impediscono la chiusura senza firma elettronica del tecnico, con log timestampati per gli audit non annunciati ([eWorkOrders](https://eworkorders.com/10-things-you-didnt-know-modern-cmms-systems-can-do-beyond-work-orders/)).

**Senso per NOVICROM: no, scartare.** L'utente è già autenticato con SSO aziendale, `executed_by` è esplicito e il log è timestampato: una "firma" aggiuntiva sarebbe teatro di conformità. La cosa *davvero* mancante non è la firma, è il fatto che l'OdL sia ri-chiudibile senza traccia (C3).

### B7. Gestione ricambi / magazzino

Modulo core di qualunque CMMS (inventario, soglie di riordino, consumo per OdL).

**Senso per NOVICROM: no a questa scala, scartare.** Introdurrebbe un dominio intero (magazzino, giacenze, riordini) per un beneficio marginale; oggi il costo materiali è un campo dell'OdL (`materials_cost_eur`) e questo è probabilmente il livello di dettaglio giusto. Se un giorno servisse, il gancio naturale è `AssetComponent`, che già esiste.

### B8. Altre voci valutate e scartate

- **Mobile app dedicata**: no. La QR landing + le viste HTMX coprono già l'uso da telefono in officina; il gap vero è la responsività delle tabelle dense (U-finding già noto), non un'app.
- **IoT / lettura automatica contatori**: no per ora. Il modulo `contatori` dimostra che la lettura automatica (SNMP) è possibile dove il dispositivo la offre; le macchine utensili in genere no. Prima si risolve il fatto che nessuno *legga* i contatori (B4), poi eventualmente si automatizza.
- **Predizione guasti / IA predittiva**: no — già argomentato in MIGLIORAMENTI_ASSETS §A3, e qui c'è la conferma strutturale: senza *codice causa guasto* sui correttivi (A1) non esiste nemmeno il dato di partenza.
- **Priorità/criticità asset (ABC)**: **sì, ma leggera.** I benchmark PM compliance sono differenziati per criticità (95%+ sugli asset A). Un campo `criticita` su `AssetCategory`/`Asset` che ordina il cockpit e il reminder costa poco (S) e cambia il modo in cui il team spende la giornata. Da fare **dopo** che il piano è rispettato: prima la compliance, poi la priorità.

---

## PARTE C — PROPOSTE PRIORITIZZATE

### Quick win (effort basso, valore immediato)

| # | Intervento | Dove | Perché |
|---|---|---|---|
| **Q1** | **Includere le scadenze SCADUTE nei reminder** (togliere i filtri `due_date__gte=today` / `next_verification_date__gte=today`, sezione dedicata "SCADUTE" in cima alla mail) | `send_maintenance_reminders.py:83-100` | M1 — oggi la scadenza mancata è quella di cui il sistema smette di parlare. Fix da due righe, elimina il rischio nº1 |
| **Q2** | **Alert "contatore fermo da N giorni"** (nuova sezione del reminder + badge nello scadenzario) e **`missing` promosso** da grigio in fondo a rosso in cima | `send_maintenance_reminders.py`, `maintenance.py:331-340,515-520` | M3 — una manutenzione a ore che non scatta mai è invisibile; oggi il segnale più debole è sul rischio più alto |
| **Q3** | **Escludere `is_legacy=True` dalle verifiche nel reminder** (allineare al cockpit) | `send_maintenance_reminders.py:93-100` vs `views.py:15580-15585` | M6 — doppio conteggio nella mail |
| **Q4** | **Notificare l'assegnatario** alla creazione/assegnazione dell'OdL e all'avvicinarsi della scadenza (usare `core.notifiche`, tipo già esistente `asset_scadenza`) | `views.py:14963` (create), `15180` (claim), reminder | M4 — `assigned_to` esiste ma non riceve nulla; il push è collettivo, il personale è solo pull |
| **Q5** | **Anti-rumore sul reminder**: mail differenziata (scadute ogni giorno; in scadenza il primo giorno di warning, poi a cadenza settimanale) | `send_maintenance_reminders.py:17` | M7 — 30 mail identiche di fila sono il modo standard per rendere invisibile un alert |
| **Q6** | Unificare la soglia "OdL in ritardo" (21gg hardcoded in due punti) in una SiteConfig | `views.py:15514`, `send_maintenance_reminders.py:66` | Due costanti gemelle che possono divergere |

### Interventi strutturali

| # | Intervento | Effort | Note |
|---|---|---|---|
| **P1** | **Persistere la data teorica di scadenza** (`planned_due_date` su `AssetMaintenanceRuleState` e/o `WorkOrder`) e su di essa calcolare la **PM compliance** (% chiusi entro finestra, per asset/categoria/mese) | M | Abilita B1+B2 insieme; è il singolo pezzo di modello da cui dipendono sia la metrica d'audit sia lo schedule fisso. **Prima cosa strutturale da fare** |
| **P2** | **`schedule_mode` (FIXED/FLOATING) su `MaintenanceRule`** + override per asset (meccanismo già esistente) | M | B2 — verifiche di legge/tarature devono essere fisse; lubrificazioni floating. Poggia su P1 |
| **P3** | **Fallback a calendario per le regole a contatore** (soglia contatore + `max_days` di sicurezza: scatta il primo dei due) | S/M | B4 — chiude il rischio residuo di M3 anche se nessuno legge il contatore. Il motore è già unificato: si tocca `meter_schedule_payload` e il generatore |
| **P4** | **Escalation OdL a due livelli** (assegnatario → responsabile manutenzione da SiteConfig) al superamento della soglia | S | B5 — riusare il pattern già in produzione di `run_tickets_escalation` |
| **P5** | **Stato/segnale sull'asset con verifica scaduta**: non un blocco (troppo rigido), ma un badge di non-conformità visibile nel dettaglio, nella lista e — importante — nella QR landing letta in officina | M | M8 — oggi la macchina con verifica scaduta è indistinguibile dalle altre nel punto in cui la si usa |
| **P6** | **Decidere sulla taratura**: o si costruisce il flusso minimo ISO §7.1.5 (esito conforme/fuori tolleranza, certificato obbligatorio, campo "impatto su misure precedenti"), oppure si **rimuove `KIND_CALIBRATION`** dalle scelte e si dichiara che le tarature vivono nelle scadenze amministrative | S (rimozione) / L (flusso completo) | M5 — la peggiore delle opzioni è l'attuale: un'etichetta che promette un flusso inesistente |
| **P7** | **Stato intermedio "in corso"** + campo *causa guasto* sui correttivi | M | Sblocca la distinzione "nessuno l'ha guardato" vs "ci stanno lavorando" e, con il codice causa, l'analisi dei guasti ricorrenti (oggi impossibile) |

### Cosa NON fare (overengineering a questa scala)

- **FSM completa su `WorkOrder`** con libreria di stati/transizioni: 3 stati + 1 intermedio (P7) si gestiscono con un guard e un `choices`. Una macchina a stati formale è peso senza beneficio con questo volume.
- **Firma elettronica alla chiusura** (B6): SSO + `executed_by` + log timestampato sono già evidenza sufficiente; ciò che va chiuso è la ri-chiudibilità senza traccia (C3), non l'assenza di una firma.
- **Modulo ricambi/magazzino** (B7): dominio intero per beneficio marginale; `materials_cost_eur` è il livello giusto oggi.
- **Manutenzione predittiva / ML** (B8): manca il dato di partenza (causa guasto) e la scala non lo giustifica.
- **App mobile dedicata**: la QR landing è la strada giusta, va solo resa robusta su tabella/telefono.
- **Approvazione/workflow multi-livello degli OdL**: con un team piccolo aggiungerebbe attrito senza aumentare il controllo.

---

*Fonti interne: `django_app/assets/{models,views,forms,maintenance,tasks}.py`, `assets/management/commands/{generate_scheduled_workorders,send_maintenance_reminders}.py`, `assets/services/{maintenance_register,dashboard_kpi}.py`, `automazioni/schedules.py`, `core/{notifiche,audit}.py`, `templates/assets/`. Fonti web citate inline (CMMS: Sockeye, MaintainX, Oxmaint, eWorkOrders, Micromain, Atlas CMMS, SM Global; norme: Core Solutions, Apogee QMS, Pretesh Biswas, Richard Randall, Wilkshire Consulting).*
