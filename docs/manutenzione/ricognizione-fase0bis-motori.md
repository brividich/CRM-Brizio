# Ricognizione Fase 0bis — i motori di generazione

Documento di sola lettura. Nessun file applicativo del dominio manutenzione è
stato modificato; l'unica modifica al codice è l'estensione del comando di audit
`manut_audit` (sola lettura, tre sezioni nuove) richiesta dal mandato.

**Branch:** `docs/manut-fase0bis-motori`, worktree dedicato `C:\Dev\pn-manut-fase0bis`,
creato da `origin/main` (`da17aa03`).
**Riferimento temporale:** 2026-09-07.
**Documento presupposto:** `docs/manutenzione/ricognizione-fase0.md` su
`docs/manut-ricognizione-fase0` (`91ce8b7c`).

> **Regola seguita, come in Fase 0:** nessun nome di modello, campo, funzione o job è
> stato assunto. Tutto è ricavato dal codice o da artefatti verificabili, con
> riferimento `file:riga`. Dove la risposta non è determinabile è scritto **non
> determinato**, con l'indicazione di come determinarla.

---

## Esito esecutivo

La domanda del mandato era: *il codice analizzato in Fase 0 è quello che gira in
produzione?* La risposta è più precisa di un sì o di un no, e nessuna delle due
posizioni in campo la conteneva.

**Fino al 2026-09-07 alle 09:01 la premessa dell'audit Codex era vera in produzione.**
La release attiva era la `20260904_101909` (v1.3.0, commit `d39c5fa3`), che contiene
`generate_scheduled_workorders.py` e registra il job `assets_generate_workorders` →
`assets.tasks.run_generate_scheduled_workorders`. Il codice studiato in Fase 0 non era
quello in esercizio.

**Dalle 09:01 di oggi non lo è più.** La release `20260907_090132` (v1.4.0, commit
`9fc8e3a6`) è stata attivata in produzione: il generatore legacy non esiste più nel
pacchetto installato e lo scheduler nel codice punta al motore nuovo.

**Il job schedulato non ha però ancora girato nemmeno una volta col motore nuovo.** È
schedulato alle 06:00 (`schedules.py:407`) e la corsa delle 06:00 di oggi è avvenuta **tre
ore prima** del deploy, quindi ancora col motore vecchio. **La prima corsa automatica sarà
quella del 2026-09-08 alle 06:00.**

Attenzione a non confondere il job con il motore: il *comando* è già stato eseguito a mano.
La verifica del 07-09 trova **321 occorrenze con `source=SCHEDULER`** (§8), che solo
`generate_occurrences` può aver scritto — `migrate_maintenance_to_plans` marca
esplicitamente `MIGRATION` in tutti e tre i suoi `create` (`:285`, `:361`, `:374`), quindi
non è un effetto del valore di default del campo. Il motore nuovo ha quindi già popolato il
portale; è la sua esecuzione **automatica** a non essere ancora avvenuta.

Restava una condizione da verificare, che il codice da solo non poteva chiudere. Il job è
stato **rinominato** insieme al motore (`assets_generate_workorders` →
`assets_generate_occurrences`); `register_schedule` fa `update_or_create` **per nome**
(`schedules.py:653`), quindi non aggiorna la riga vecchia; e il passo che la rimuove —
`setup_q_schedules`, che consuma `RETIRED_SCHEDULE_NAMES` — **non è nel flusso di promote
usato in produzione** (§2.2). Se nessuno l'avesse eseguito, la tabella `django_q_schedule`
avrebbe conservato il job vecchio, puntato a una funzione che non esiste più, e il job
nuovo non sarebbe mai stato registrato: generazione automatica ferma del tutto.

**Verificato a runtime il 2026-09-07: non è successo. Lo scheduler è allineato.**

```
assets_generate_occurrences | assets.tasks.run_generate_maintenance_occurrences
                            | next = 2026-09-08 04:00 UTC (06:00 locali)
```

`assets_generate_workorders` **non è presente**, e le schedule registrate sono 41, quante
ne prevede `SCHEDULES`. Il motivo è che `setup_q_schedules` è stato eseguito a mano dopo il
deploy: la Centrale di comando espone il pulsante **«📅 Registra schedule»**
(`monitoring/views.py:214`), che lo lancia (`monitoring/views.py:242-246`). È una terza
strada, oltre a `deploy-release.ps1` e alla riga di comando, e in questo caso ha
compensato la lacuna del promote.

**Cosa resta vero, e cosa no.** Non c'è alcun guasto in corso: la generazione riparte
domani mattina con il motore giusto, e non serve fare nulla. Resta però la **fragilità di
processo**: il flusso di promote non registra gli schedule, quindi la correttezza della
tabella dipende dal fatto che qualcuno si ricordi di premere un pulsante. Ha funzionato
oggi; è un presidio umano, non una garanzia del processo, e al prossimo rename di un job si
ripresenterà identica.

**Conseguenza sull'import.** Cade il vincolo di sequenza: lo scheduler è a posto, quindi
l'import dello storico non deve più aspettare. Restano i due punti di merito di §5 — le 5
occorrenze che nascono già scadute e lo scarto fra la semantica legacy del foglio e quella
nuova dell'importatore — che vanno affrontati per conto loro.

**Raccomandazione (dettaglio in §7):** tenere il motore a occorrenze
(`generate_maintenance_occurrences`), che è già l'unico presente nel codice installato;
dismettere formalmente il residuo `WorkMachine.next_maintenance_date`, che è l'unica
delle fonti parallele a essere una *duplicazione* del dominio manutenzione e non un
sottodominio autonomo.

---

## 1. Inventario dei motori

### 1.1 Percorsi che creano occorrenze o OdL in automatico

Ricerca su `django_app/` (esclusi test e migrazioni) dei punti di creazione:
`MaintenanceOccurrence.objects.create/get_or_create` e `WorkOrder.objects.create`/`WorkOrder(`.

| # | Percorso | `file:riga` | Cosa crea | Periodicità applicata | Usa `compute_next_due`? |
|---|---|---|---|---|---|
| 1 | Generatore a occorrenze | `assets/services/maintenance_domain.py:376` | `MaintenanceOccurrence` (OPEN, `source=SCHEDULER`) | `MaintenancePlanAssignment` risolta da `build_plan_resolutions` | **Sì**, via `compute_due_date_for` (`maintenance_domain.py:271`) |
| 2 | Chiusura occorrenza → avanzamento | `assets/services/maintenance_domain.py:477` | occorrenza successiva | stessa applicazione | **Sì** |
| 3 | Import storico — riga storica | `assets/services/maintenance_history_import.py:337` | `MaintenanceOccurrence` (DONE, `source=IMPORT`) | nessuna: data dichiarata nel foglio | no (è storia, non calcolo) |
| 4 | Import storico — prossima scadenza | `assets/services/maintenance_history_import.py:367` | `MaintenanceOccurrence` (OPEN, `source=IMPORT`) | applicazione risolta | **Sì**, chiamata diretta a `maintenance_history_import.py:302` |
| 5 | Migrazione dal vecchio motore | `assets/management/commands/migrate_maintenance_to_plans.py:276,350,367` | occorrenze `source=MIGRATION` | regole legacy convertite | one-shot, non schedulato |
| 6 | OdL da occorrenze selezionate | `assets/services/maintenance_domain.py:636` | `WorkOrder` | — (raggruppa occorrenze esistenti) | n/a |
| 7 | OdL da verifica periodica | `assets/views.py:2788`, `2829` | `WorkOrder` | `PeriodicVerification.frequency_months` | **no**, logica propria |
| 8 | OdL follow-up | `assets/views.py:15547`, `views_maintenance.py:1326` | `WorkOrder` figlio | nessuna | n/a |
| 9 | OdL da guasto / creazione manuale | `assets/views.py:9090`, `14613` | `WorkOrder` | nessuna | n/a |
| 10 | Import Excel asset | `assets/management/commands/import_assets_excel.py:872` | `WorkOrder` storici | nessuna | one-shot |
| 11 | Import storico collaudi | `assets/management/commands/import_collaudo_history.py:210` | `WorkOrder` storici | nessuna | one-shot |
| 12 | Servizio interno | `assets/services/__init__.py:208` | `WorkOrder` | — | n/a |

**Signal:** nessuno. `grep` di `post_save`/`pre_save`/`@receiver` su `assets/` non produce
alcun risultato fuori dai test: non esistono percorsi di creazione nascosti dietro un
segnale.

**Chiamate da `automazioni/`:** una sola, il job schedulato (§2).

### 1.2 I due motori a confronto — quello che resta e quello che non c'è più

Il motore legacy (`generate_scheduled_workorders.py`) **non esiste più nel codice**: è
stato rimosso in `70e3889f` (§6). Nel ramo `main` ne restano solo menzioni in commenti
(`assets/maintenance.py:615`, `assets/models.py:1611`) e nel `CHANGELOG`.

Resta però vivo `assets/maintenance.py` (651 righe), il motore di risoluzione a regole:
`MaintenanceRule`, `MaintenanceRuleAssetOverride`, `AssetMaintenanceRuleState`, `AssetMeter`.
Non genera più nulla in automatico — nessun chiamante schedulato — ma alimenta ancora
viste di anteprima e scadenzario. È **codice di lettura**, non un secondo motore di
generazione. Questa è la differenza sostanziale rispetto alla fotografia dell'audit
Codex, che lo classificava come «runtime attivo» perché all'epoca lo era.

---

## 2. Cosa gira davvero

### 2.1 Configurazione (dal codice)

`django_app/automazioni/schedules.py:399-409`:

```
"name": "assets_generate_occurrences",
"func": "assets.tasks.run_generate_maintenance_occurrences",
"schedule_type": "C",        # cron
"cron": "0 6 * * *",         # ogni mattina alle 06:00
"repeats": -1,
```

Il wrapper è `assets/tasks.py:13`, che a `:24` esegue
`call_command("generate_maintenance_occurrences", verbosity=0)`.

Il job successivo `assets_maintenance_reminders` (`schedules.py:415`, cron `0 7 * * *`)
è deliberatamente un'ora dopo, così le scadenze appena create entrano nella mail del
giorno.

**Abilitazione:** i job possono essere disattivati dalla Centrale di comando; il filtro
è `disabled_schedule_names()` (`schedules.py:664`), che legge `monitoring.ScheduleControl`
ed è fail-safe (set vuoto in caso di errore). Se `assets_generate_occurrences` fosse
disabilitato lì, `setup_q_schedules` non lo registrerebbe e anzi lo eliminerebbe
(`setup_q_schedules.py:66-72`). **Non determinato dal codice:** va letto a DB.

**Ambienti:** `SCHEDULES` non è differenziato per ambiente. Ciò che cambia è quale
cluster django-q è in esecuzione; in produzione è `QCluster_PROD`.

### 2.2 Il ritiro del job vecchio: il processo non lo garantisce, una persona sì

Il nome del job è cambiato con il motore:

| | release 20260904 (v1.3.0) | release 20260907 (v1.4.0) |
|---|---|---|
| `name` | `assets_generate_workorders` | `assets_generate_occurrences` |
| `func` | `assets.tasks.run_generate_scheduled_workorders` | `assets.tasks.run_generate_maintenance_occurrences` |

`register_schedule` fa `update_or_create(name=...)` (`schedules.py:653`): **cambiando il
nome non aggiorna la riga vecchia, ne crea una seconda.** Gli autori lo sapevano e hanno
predisposto il rimedio — `RETIRED_SCHEDULE_NAMES` (`schedules.py:489-493`) contiene
`assets_generate_workorders`, con il commento esplicito *«Se restasse attivo produrrebbe
una seconda fonte di scadenze»* — consumato in `setup_q_schedules.py:90-97`.

**Il rimedio però non viene eseguito dal percorso di promote usato in produzione.**

- `deployment/scripts/deploy-release.ps1:607-625` esegue `setup_q_schedules` allo step 11/12;
- il promote effettivo è passato dal Setup Wizard (`deployment/setup_wizard.py`, step 6
  «Attivazione release» a `:5722`, step 7 «Riavvio App Pool IIS» a `:5746`): **quel flusso
  non contiene lo step `setup_q_schedules`**, che nel Wizard esiste solo come pulsante
  manuale («🟡 Automazioni · Registra schedule», `setup_wizard.py:6807`);
- nel log del promote di oggi, `setup_q_schedules` compare **zero volte**.

Questa è la stessa classe di difetto già nota per il Setup Wizard: un passo presente nel
percorso di installazione e assente in quello di release.

**Esiste però una terza strada, ed è quella che è stata usata.** La Centrale di comando
espone l'azione «📅 Registra schedule» (`monitoring/views.py:214`), che esegue
`call_command("setup_q_schedules")` (`monitoring/views.py:242-246`) e registra l'operazione
nell'audit (`:247`). Lanciata a mano dopo il promote del 07-09, ha allineato la tabella:
verifica in §2.3.

Il difetto di processo resta comunque aperto: perché la tabella sia corretta serve che
qualcuno **si ricordi** di premere quel pulsante dopo ogni release che tocca i job. È un
presidio, non una garanzia.

### 2.3 Evidenze di esercizio (artefatti di produzione)

`Y:` è `\\pclogsys\PortaleNovicrom\prod`: la produzione è ispezionabile in sola lettura.

| Evidenza | Fonte | Fatto |
|---|---|---|
| Versione installata | `Y:\current\BUILD_INFO.json` | v1.4.0, commit `9fc8e3a6`, branch `release/prod`, `dirty: false`, `delta_vs_export_branch: 0`, build 2026-09-06 19:29 |
| Attivazione | `Y:\logs\release_promote_20260907_090132.log` | release attivata 2026-09-07 ~09:01; `current → 20260907_090132`; App Pool riciclato |
| Release precedente | `Y:\releases\20260904_101909\BUILD_INFO.json` | v1.3.0, commit `d39c5fa3` — attiva fino a stamattina |
| Migrazioni applicate | stesso log | `assets.0098_assetgroup_and_more`, `assets.0099_sidebar_manutenzione_nuovo_dominio` |
| `setup_q_schedules` | stesso log | **assente** |
| Codice installato | `Y:\current\django_app\assets\tasks.py` | definisce solo `run_generate_maintenance_occurrences`; il legacy non c'è |
| Comandi installati | `Y:\current\django_app\assets\management\commands\` | solo `generate_maintenance_occurrences.py` |
| Cluster django-q | `Y:\logs\qcluster.log` | avvio 2026-08-06 14:02; **riavvio 2026-09-07 10:36** |

> Il processo cluster avviato il 06-08 ha tenuto in memoria il codice di allora fino al
> riavvio di oggi alle 10:36. La corsa delle 06:00 di oggi è quindi stata eseguita dal
> motore vecchio, che a quell'ora era anche quello su disco.

**Verifica a DB (2026-09-07, sola lettura).** `django_q.Schedule` in produzione:

| | |
|---|---|
| Schedule registrate | **41** (quante ne prevede `SCHEDULES`) |
| `assets_generate_occurrences` | **presente** → `assets.tasks.run_generate_maintenance_occurrences`, `next_run` 2026-09-08 04:00 UTC = **06:00 locali** |
| `assets_generate_workorders` | **assente** |
| `assets_maintenance_reminders` | presente → `run_maintenance_reminders`, `next_run` 05:00 UTC = 07:00 locali |

Nessuna schedule orfana, nessun job mancante. La previsione di §2.2 — riga vecchia
superstite e job nuovo non registrato — **non si è avverata**, perché `setup_q_schedules` è
stato eseguito dalla Centrale di comando dopo il promote.

### 2.4 Cosa non è determinabile dal codice, e come determinarlo

Tre fatti vivono solo nel database di produzione. Il primo è stato verificato (§2.3); gli
altri due restano da guardare:

1. ~~quali righe esistono in `django_q_schedule`, con `next_run` e il `func` registrato~~
   — **verificato il 07-09: allineato**;
2. l'esito della **prima corsa del motore nuovo**, attesa il 2026-09-08 alle 06:00
   (`Success` / `Failure`, e quante occorrenze ha creato);
3. se qualche job sia disabilitato in `monitoring.ScheduleControl`.

Sono esattamente le cose che stampa la sezione nuova:

```powershell
C:\PortaleNovicrom\prod\venv\Scripts\python.exe manage.py manut_audit `
    --runtime --sorgenti --fonti-parallele --settings=config.settings.prod
```

La sezione «PUNTO 7» stampa le `Schedule` registrate con cadenza, `next_run` ed esito
dell'ultimo task; segnala in errore le **schedule orfane** (il `func` registrato non è più
importabile nel codice installato — è il caso atteso qui) e i **job attesi dal codice ma
non registrati a DB**. Il comando non scrive nulla: solo `values()`/`annotate()` e un
`importlib.import_module` per verificare che il `func` esista.

---

## 3. Divergenza semantica

Confronto tra il motore a occorrenze (in esercizio dal 07-09) e il motore a regole
(in esercizio fino al 07-09, ora presente solo come codice di lettura).

| Aspetto | Motore a occorrenze | Motore a regole (legacy) |
|---|---|---|
| Unità creata | `MaintenanceOccurrence` per coppia (piano, asset) | `WorkOrder` per coppia (asset, regola) |
| Raggruppamento in OdL | decisione umana, pagina «Da fare» | automatico, un OdL per asset |
| Sorgente della periodicità | `MaintenancePlanAssignment` risolta per specificità | `MaintenanceRule` + `MaintenanceRuleAssetOverride` |
| Base del calcolo, ancoraggio `FROM_COMPLETION` | `completed_on` dell'ultima occorrenza chiusa (`recurrence.py:198-201`) | `closed_at` dell'ultimo OdL chiuso |
| Base del calcolo, ancoraggio `FIXED_CALENDAR` | `previous_due` (scadenza teorica), con fallback su `completed_on` | non previsto |
| **Date nel passato — con storico** | **nessun recupero**: `compute_next_due` fa **una sola** addizione (`recurrence.py:204` → `add_recurrence`). Una base vecchia produce una scadenza vecchia | analogo |
| **Date nel passato — senza storico** | `first_due_date_for` (`recurrence.py:207`) **avanza di ricorrenza in ricorrenza fino a oggi**, max 2000 giri | non previsto |
| Mai eseguita, senza `first_due_date` | dovuta subito (`maintenance_domain.py:281`) | dovuta subito |
| Finestra di creazione | solo dentro il preavviso: `(due_date - oggi).days > window` → saltata (`maintenance_domain.py:353`) | preavviso della regola |
| Stati scritti | `MaintenanceOccurrence.status` + `source` | `AssetMaintenanceRuleState`, `WorkOrder.status`, `WorkMachine.next_maintenance_date` |
| Idempotenza | vincolo DB unico su (piano, asset, scadenza) + salto se esiste un'occorrenza aperta; `IntegrityError` intercettato (`maintenance_domain.py:381`) | dedup su «esiste un OdL OPEN per la coppia» |
| Conflitti di periodicità | **rispettati**: `RESOLUTION_CONFLICT` → nessuna occorrenza creata, conteggiata a parte (`maintenance_domain.py:335`) | non previsti |
| Esclusioni | `RESOLUTION_EXCLUDED` → saltata | override `is_disabled` |
| Asset fuori uso | esclusi salvo `--include-out-of-service` | filtro per categoria |

### 3.1 Il punto che conta: `compute_next_due` non recupera l'arretrato

Le due funzioni di `recurrence.py` si comportano in modo opposto davanti a una data vecchia:

- **`compute_next_due`** (`recurrence.py:185`) → `add_recurrence(spec, base)`: **una sola
  addizione**. Se `base` è di tre anni fa e la ricorrenza è annuale, il risultato è di due
  anni fa.
- **`first_due_date_for`** (`recurrence.py:207`) → ciclo `while candidate < today`: **avanza
  fino a oggi**, con il commento esplicito *«Con una data di partenza nel passato non si
  crea una scadenza vecchia di anni»*.

L'intenzione di non far nascere scadenze nel passato esiste ed è scritta nel codice. Ma
è implementata **soltanto** nel ramo «nessuno storico». Il ramo «c'è uno storico» — che è
quello dell'import e quello dell'avanzamento dopo ogni chiusura — usa `compute_next_due`
e non ha alcuna guardia. Non è una svista dell'import: è una proprietà del motore.

---

## 4. Tracce nei dati

**Sì, i record sono distinguibili, e senza euristiche.**

`MaintenanceOccurrence.source` (`assets/models.py:3679`) è un `CharField` indicizzato
(`db_index=True`), obbligatorio, con default `SCHEDULER` e quattro valori
(`models.py:3582-3590`):

| Valore | Etichetta | Scritto da |
|---|---|---|
| `SCHEDULER` | Generata dallo scheduler | `maintenance_domain.py:376` |
| `MANUAL` | Creata a mano | UI |
| `MIGRATION` | Migrata dal vecchio motore | `migrate_maintenance_to_plans.py` |
| `IMPORT` | Importata | `maintenance_history_import.py:337,367` |

Ogni percorso di creazione valorizza il campo esplicitamente, tranne quello scheduler che
si affida al default. Non serve inferire nulla da `created_by` o dai pattern nelle date.

Gli OdL, invece, **non** hanno un campo equivalente: `WorkOrder` non porta traccia del
motore che lo ha aperto. Per gli OdL creati prima del 07-09 dal generatore legacy l'unico
indizio è `WorkOrder.maintenance_rule` (`models.py:2266`), la FK legacy: valorizzata ⇒
aperto dal motore a regole. È un indizio, non una garanzia, perché la stessa FK è
valorizzabile da altri percorsi.

**Estensione realizzata.** `manut_audit --sorgenti` (sezione «PUNTO 8») conta le occorrenze
per `source` × `status` con l'intervallo di date coperto, e in più isola **le occorrenze
aperte già scadute, per sorgente**, con la più vecchia di ciascuna: è la spia diretta del
fenomeno descritto in §3.1 e §5.

---

## 5. Conseguenza sull'import — risposta diretta

### 5.1 Provenienza del foglio: **non è un export dell'HUB**

Questo va detto prima di tutto il resto, perché cambia la natura del rischio.

L'unico esportatore dell'HUB è `maintenance_history_template`
(`views_maintenance.py:1537`) → `build_template_workbook()`
(`maintenance_history_import.py:387`). Produce un file con:
foglio intitolato **«Storico manutenzioni»**, intestazioni, **una riga di esempio**
(`TORNIO01 / Cambio olio / 15/03/2026`), nome `storico_manutenzioni_modello.xlsx`.

Il file fornito ha foglio **`storico`**, **379 righe reali** e nessuna riga di esempio.
I metadati OOXML dicono `dc:creator = openpyxl`, creato `2026-09-07T07:49:30Z` — coerente
con il timestamp nel nome, e con uno **script ad hoc**, non con la pagina «Importa storico».

Uno script di questa forma esiste ed è documentato: `genera_foglio_storico.py`, prodotto in
una sessione precedente (04-09), la cui docstring dichiara *«Legge SOLO il vecchio motore
(regole + stati)»*. Costruisce le coppie da `MaintenanceRule.is_active` × `Asset` della
categoria della regola, e scarta quelle che hanno già un `AssetMaintenanceRuleState`.

**Il rischio che ne discende è strutturale, non di formato:** le 379 coppie del foglio sono
state generate dalla **semantica legacy** (regola × categoria), mentre l'importatore le
risolve contro la **semantica nuova** (`build_plan_resolutions`, cioè
`MaintenancePlanAssignment` per asset / gruppo / categoria, con specificità e esclusioni).
Le due non coincidono per costruzione. Le righe che il vecchio motore riteneva applicabili
e il nuovo no verranno respinte con *«Il piano non si applica a questo asset: applicalo
prima di importare lo storico»* (`maintenance_history_import.py:290`). Quante siano non è
determinabile senza il DB: è la prima cosa che dirà l'anteprima.

Le due metà **non sono lo stesso giro**: sono l'esportatore legacy di una sessione e
l'importatore del dominio nuovo.

### 5.2 Il match avviene sulle **stringhe** — sì, ed è un rischio

Confermato, in due punti distinti di `maintenance_history_import.py:analyze`:

**Asset** (`:234-239`) — nessun id. Confronto su `asset_tag` normalizzato da `_normalize`
(`:62`: `strip().lower()`, NFKD, rimozione dei segni diacritici). Un `asset_tag` cambiato,
con spazi diversi o assente fa fallire la riga con *«Asset non trovato»*. Non c'è fallback
su `name`, mentre lo script di export scriveva `asset_tag or name` — **una coppia esportata
per un asset senza tag non sarà mai reimportabile.**

**Piano** (`:240-243`) — nessun id, e per giunta **un unico spazio di nomi per due campi**:

```python
for plan in MaintenanceInterventionTemplate.objects.all():
    plans_by_key.setdefault(_normalize(plan.code), plan)
    plans_by_key.setdefault(_normalize(plan.label), plan)
```

`code` e `label` finiscono nello stesso dizionario. Se il `code` di un piano coincide, una
volta normalizzato, con il `label` di un altro, `setdefault` fa vincere **quello che arriva
prima nell'ordinamento di default del queryset** — e la riga viene attribuita al piano
sbagliato **senza alcun errore**, perché il match è formalmente riuscito. È l'unico modo,
in tutta la catena, in cui una riga può essere importata su un piano diverso da quello
inteso e nessuno se ne accorge.

Il piano è inoltre cercato solo tra i `MaintenanceInterventionTemplate`: le 19 etichette
del foglio provengono da `MaintenanceRule.intervention_template_id`, quindi su questo campo
il vocabolario è lo stesso. È la *coppia* piano/asset a non esserlo (§5.1).

### 5.3 Il percorso di codice, passo per passo

Percorso completo per una riga con data compilata:

1. `views_maintenance.py:1514` → `history_import.read_table(file)`
2. `views_maintenance.py:1519` → `analyze(table)` — anteprima, **nessuna scrittura**
3. dentro `analyze`, per ogni riga (`maintenance_history_import.py:256-306`), in quest'ordine:
   - asset non trovato → errore (`:262`)
   - piano non trovato → errore (`:265`)
   - data illeggibile o mancante → errore (`:268`)
   - **data futura → errore** (`:274`) — l'unica guardia temporale esistente
   - risoluzione in conflitto → errore (`:283`)
   - asset escluso dal piano → errore (`:286`)
   - piano non applicabile → errore (`:290`)
   - terna (piano, asset, data) già presente → `DUPLICATE`, riga saltata (`:294`)
   - altrimenti `:302`:
     ```python
     row.next_due = compute_next_due(
         assignment,
         anchor=assignment.effective_schedule_anchor,
         previous_due=row.last_execution,
         completion_date=row.last_execution,
     )
     ```
     **Entrambe le basi sono la data dichiarata nel foglio.** Qualunque sia l'ancoraggio,
     `compute_next_due` (`recurrence.py:185`) prende quella data e ci somma **una** volta
     la ricorrenza (`recurrence.py:204`). `first_due_date_for`, che avanzerebbe fino a
     oggi, **non è su questo percorso**.
4. conferma utente → `views_maintenance.py:1495` → `apply_report()` (`:319`), tutto in
   `@transaction.atomic`. Per ogni riga valida:
   - `:337` crea l'occorrenza **storica**: `status=DONE`, `due_date = completed_on =` data
     dichiarata, `source=IMPORT`;
   - `:359` se esiste già un'occorrenza `OPEN` per la coppia, **non la sposta**: incrementa
     `kept_open` e passa oltre;
   - `:367` altrimenti crea l'occorrenza **prossima**: `status=OPEN`, `due_date = next_due`,
     `previous_due_date =` data dichiarata, `source=IMPORT`.

**Non c'è alcun punto, in tutta la catena, in cui una `next_due` nel passato venga
riportata avanti o segnalata.** La sola guardia temporale rifiuta le date *future*
(`:274`), che è il caso opposto.

### 5.4 Cosa producono le 152 date — numeri

Simulazione della catena `analyze → compute_next_due → apply_report` sul file compilato
(`storico_compilato_20260907.xlsx`: 379 righe, 37 asset, 19 piani, **152 date compilate**,
227 vuote, minima 18-06-2021, massima 24-08-2026, nessuna futura), con le periodicità reali
dei piani ricavate dalla colonna `note` del foglio del 04-09 (`periodicita' N giorni`,
lette da `MaintenanceRule.threshold_value`).

> **Assunzione dichiarata:** che `migrate_maintenance_to_plans` abbia riportato quelle
> soglie come ricorrenze `DAYS/N` sulle applicazioni. Se una periodicità è stata
> ridefinita in fase di migrazione, il numero cambia per quel piano. L'anteprima
> dell'import mostra la ricorrenza risolta riga per riga (`row.recurrence_label`,
> `maintenance_history_import.py:301`) ed è la verifica definitiva.

**Scritture prodotte: 304 occorrenze** — 152 `DONE` (storiche) + 152 `OPEN` (prossime),
tutte con `source=IMPORT`.

> **Verificato: l'import è stato eseguito, e i numeri coincidono.** `manut_audit --sorgenti`
> in produzione il 2026-09-07 riporta `Importata DONE 152` (dal 18-06-2021 al 24-08-2026) e
> `Importata OPEN 152` (dal 18-06-2024 al 30-03-2029), con **5 aperte già scadute, la più
> vecchia al 18-06-2024** — cioè esattamente le 5 righe della tabella qui sotto, a partire
> da `CNC-ELT-007003`. La previsione fatta sul codice corrisponde al risultato reale.

Delle 152 aperte:

| Esito | N |
|---|---:|
| scadenza futura | 147 |
| **nate già scadute** | **5** |

Ritardo alla nascita delle 5: minimo 16 giorni, mediana 146, **massimo 811 giorni**.

| Asset | Piano | Ultima esecuzione | Nasce con scadenza | Ritardo |
|---|---|---|---|---:|
| CNC-ELT-007003 | Sostituzione batterie tampone (1096 gg) | 18-06-2021 | 18-06-2024 | −811 gg |
| CNC-MZ5153592 | Filtro Aria (182 gg) | 19-09-2025 | 20-03-2026 | −171 gg |
| CNC-SIP-8000 | Cambio Olio (182 gg) | 14-10-2025 | 14-04-2026 | −146 gg |
| CNC-DM8-330002291 | Controllo Cinghie (274 gg) | 23-09-2025 | 24-06-2026 | −75 gg |
| CNC-MZ5153592 | Filtro Emulsione (122 gg) | 22-04-2026 | 22-08-2026 | −16 gg |

**Le 8 date oltre l'anno e le 25 oltre i 180 giorni non si traducono in 8 e 25 scadenze
arretrate.** Sono in gran parte date vecchie di piani a periodicità lunga (365 o 1096
giorni), per i quali una sola addizione basta a superare oggi. Il caso peggiore è l'unico
in cui neanche 1096 giorni bastano: una data del 2021 su un piano triennale, che nasce
scaduta di oltre due anni.

Il fenomeno è reale ma **molto più piccolo di quanto la distribuzione delle date faccia
temere**. Non richiede di rifare il motore prima di importare; richiede di sapere che
quelle 5 righe nasceranno arretrate, e di decidere se correggerne a mano la data prima
dell'import o registrarle subito dopo.

### 5.5 Le 4 equivalenze di nome: non generano conflitti, generano un pile-up permanente

L'ipotesi da modellare era che i piani alimentati per equivalenza, avendo la stessa data,
producessero conflitti se le periodicità differiscono. **Nel senso che il codice dà a
«conflitto», questo non accade**, ed è bene chiarirlo perché il termine è ambiguo.

`RESOLUTION_CONFLICT` (`maintenance_domain.py:212-220`) si verifica quando **più
applicazioni dello stesso piano** insistono sullo stesso asset con la stessa specificità
massima e firme di ricorrenza diverse (`_recurrence_signature`, `:113`). È un conflitto
*dentro un piano*. Piani **diversi** che scadono lo stesso giorno sono semplicemente piani
diversi: nessun conflitto, due occorrenze regolari.

Quello che si produce è un effetto differente e più duraturo. Nel foglio, 45 gruppi di
righe condividono la data sullo stesso asset; dopo l'import restano **41 gruppi di
scadenze simultanee, per 101 delle 152 righe** — due terzi. I raggruppamenti ricalcano
esattamente le equivalenze descritte:

- **gruppo filtri** — `Controllo Filtri`, `Filtro Aria`, `Filtri Esterni`: tutti **182 giorni**;
- **gruppo raffreddamento** — `CONTROLLO PERDITA FREON`, `Refrigerante`, `Liquido Raffreddamento`: tutti **365 giorni**.

Poiché **dentro ciascun gruppo la periodicità è identica**, le scadenze non divergono mai:

| | Gruppi |
|---|---:|
| restano allineati per sempre (stessa periodicità) | **40** |
| si separano al giro successivo | **1** |

L'unico che si separa è `CNC-DM10-12280008793` al 16-01-2027, dove il gruppo filtri (182)
e il gruppo raffreddamento (365) cadono per coincidenza lo stesso giorno.

**La conseguenza operativa non è un errore, è un carico.** Su 24 asset arriveranno 2-3
manutenzioni filtri lo stesso giorno, su 14 asset 2 manutenzioni raffreddamento lo stesso
giorno, e questo **si ripeterà identico a ogni ciclo**, perché il motore ancorato a
`FROM_COMPLETION` riparte dalla data di chiusura: chiudendole insieme, restano insieme
per sempre. Esempi già visibili nella simulazione: `CNC-DIXI80-06` il 02-10-2026 con 4
piani, `CNC-DM10-12280008793` il 16-01-2027 con 4, `CNC-MZ6168782` il 18-09-2026 con 4,
`CNC-KMV16-2200220` il 04-06-2027 con 3.

Questo è un argomento **a favore** dell'import così com'è, non contro: raggruppare
manutenzioni simultanee in un unico ordine di lavoro è esattamente ciò che la pagina «Da
fare» esiste per fare, ed è la ragione dichiarata per cui il motore nuovo non apre più un
OdL per asset (`generate_maintenance_occurrences.py:3-6`). Va però saputo in anticipo,
perché è il regime permanente, non un transitorio dell'import.

---

## 6. Certificazione storica del blocco Codex (§C del mandato)

L'audit `codex/audit-manutenzioni` (`4f9bc7e3`, 2026-09-04) segnalava come blocco critico
che `automazioni/schedules.py:403` schedulava `run_generate_scheduled_workorders`. La
verifica sulla storia dei commit:

| Fatto | Commit | Data | In `main` | In `release/prod` |
|---|---|---|---|---|
| Aggancio iniziale del job legacy allo scheduler | `2d971dee` — *feat(automazioni): aggancio scheduler per scadenze assets/dpi/rentri/tickets* | 2026-07-09 09:24 | sì | sì |
| Passaggio al motore nuovo (`run_generate_maintenance_occurrences`, job rinominato) | `a7d76223` — *feat(assets): fase F — promemoria sulle occorrenze, scheduler e import storico* | **2026-09-04 19:44** | sì | sì |
| Rimozione del file `generate_scheduled_workorders.py` | `70e3889f` — *refactor(assets): fase G2 — ritirato il vecchio motore a regole* | **2026-09-05 12:12** | sì | sì |

**L'audit era corretto al momento in cui è stato scritto.** È datato 2026-09-04 sul branch
`feature/assets-manutenzione-refactor` (`97d712b3`); il passaggio allo scheduler nuovo è
delle 19:44 dello stesso giorno e la rimozione del generatore legacy è del giorno dopo.
L'audit ha fotografato lo stato reale poche ore prima che cambiasse.

**Il rilievo è oggi superato quanto al codice** — entrambi i commit sono in `main` e in
`release/prod`, e il pacchetto installato in produzione li contiene.

**Ma è superato solo a metà quanto alla sostanza.** La preoccupazione di fondo — *«due
motori con semantiche e dedup differenti»* — non era infondata: si è semplicemente
spostata dal codice al database. Il motore vecchio non esiste più in `tasks.py`, però il
suo job resta plausibilmente registrato in `django_q_schedule` e nessuno lo ha rimosso,
perché il passo che lo rimuoverebbe non è nel percorso di promote (§2.2). Il modo in cui
il rilievo si è chiuso lascia aperto il difetto che lo aveva motivato.

---

## 7. Raccomandazione

### 7.1 Quale motore tenere

**Tenere il motore a occorrenze** (`generate_maintenance_occurrences` →
`maintenance_domain.generate_occurrences`). Non è una preferenza di merito: è già l'unico
presente nel codice installato, l'unico con dedup garantita da un vincolo DB, l'unico che
riconosce esclusioni e conflitti di periodicità, e l'unico che tiene traccia della propria
sorgente sui record che produce. La decisione è stata presa e applicata; qui si certifica
che è coerente.

**Dismettere formalmente il motore a regole.** La generazione è già dismessa; resta la
lettura (`assets/maintenance.py`, viste di anteprima e scadenzario). Non c'è urgenza a
rimuoverla, ma finché è visibile mostra numeri calcolati con una semantica che non genera
più nulla. Va marcata come vista storica o rimossa, non lasciata ambigua.

**Rimuovere `WorkMachine.next_maintenance_date`**, che la misura in Appendice A mostra
essere **vuoto su tutti gli asset**: nessuna migrazione dati, nessun rischio, solo la
rimozione dal form (`forms.py:1561`) e dai cinque template che lo espongono.

### 7.2 Azioni, in ordine

1. ~~Verificare lo scheduler in produzione~~ — **fatto il 07-09, esito allineato** (§2.3).
   Nessuna azione richiesta. Il comando resta utile a ogni release che tocca i job:
   ```powershell
   C:\PortaleNovicrom\prod\venv\Scripts\python.exe manage.py manut_audit `
       --runtime --sorgenti --fonti-parallele --settings=config.settings.prod
   ```
   Se «PUNTO 7» segnalasse schedule orfane o job non registrati, il rimedio è una riga
   (idempotente: rimuove i ritirati e registra i nuovi), oppure il pulsante «📅 Registra
   schedule» della Centrale di comando:
   ```powershell
   C:\PortaleNovicrom\prod\venv\Scripts\python.exe manage.py setup_q_schedules `
       --settings=config.settings.prod
   ```

2. **Controllare la prima corsa** del motore nuovo, il 2026-09-08 dopo le 06:00: è la prima
   volta in assoluto che gira in produzione. `manut_audit --sorgenti` dice quante
   occorrenze `SCHEDULER` sono nate e se qualcuna è nata già scaduta.

3. **Chiudere il difetto di processo**, che resta aperto anche se stavolta non ha fatto
   danni: aggiungere lo step `setup_q_schedules` al flusso di promote del Setup Wizard
   (`setup_wizard.py`, dopo lo step 6 «Attivazione release» a `:5722`), com'è già in
   `deploy-release.ps1:607`. Finché dipende da un pulsante premuto a mano, il prossimo
   rename di un job può passare inosservato.

4. **Importare lo storico** — non c'è più un vincolo di sequenza, lo scheduler è a posto.
   Usare l'anteprima come strumento di verifica, non come formalità: dice quante righe
   cadono per asset o piano non trovato (rischio §5.2) e quante per «il piano non si
   applica» (rischio §5.1), che è la misura diretta dello scarto tra la semantica legacy
   del foglio e quella nuova dell'importatore.

5. **Correggere prima dell'import le 5 righe** che nascerebbero scadute (tabella §5.4), o
   accettarle sapendo che compariranno subito nel pool «Da fare» — in particolare
   `CNC-ELT-007003`, arretrata di oltre due anni.

6. **Mettere in conto il pile-up permanente** di §5.5: 41 gruppi di scadenze simultanee,
   40 dei quali resteranno allineati per sempre.

### 7.3 Fuori perimetro, da decidere separatamente

`compute_next_due` non ha guardia contro le scadenze nel passato, mentre
`first_due_date_for` ce l'ha. Uniformare i due comportamenti è una modifica al dominio:
non è stata fatta qui e non va fatta insieme all'import, perché cambierebbe anche
l'avanzamento dopo ogni chiusura. Va valutata come punto a sé.

---

## Appendice A — Fonti di scadenza parallele

Oltre alle occorrenze, tre modelli affermano indipendentemente che un asset ha una
scadenza. Nessuno dei tre conosce gli altri.

| Fonte | Modello / campo | Dove nasce la data | Dove si vede |
|---|---|---|---|
| Verifica periodica | `PeriodicVerification.next_verification_date` (`models.py`), `frequency_months` | `save()` la deriva da `last_verification_date + frequency_months` | scheda asset, scadenzario; può generare OdL (`views.py:2788`) |
| Scadenza amministrativa | `AssetAdministrativeDeadline.due_date`, `warning_days` | inserita a mano | scadenzario amministrativo |
| Data denormalizzata macchina | `WorkMachine.next_maintenance_date` (`models.py:1574`, `db_index=True`) | inserita a mano dal form (`forms.py:1561`) | `maintenance_hub.html:112-115`, `maintenance_todo.html:349,357`, `plant_layout_map.html:265`, `reports_dashboard.html:416`, `work_machine_dashboard.html:252` |

**Chi prevale nella UI:** nessuno — e questo è il punto. Non esiste una funzione di
precedenza. Le fonti sono presentate in **pannelli diversi della stessa pagina**: la
pagina hub manutenzione mostra un riquadro «Macchine — manutenzione in scadenza» alimentato
da `next_maintenance_date` **accanto** ai riquadri alimentati dalle occorrenze. Due
riquadri della stessa schermata possono dire cose diverse sullo stesso asset senza che nulla
lo segnali.

**Una nota che le distingue.** `PeriodicVerification` e `AssetAdministrativeDeadline` sono
sottodomini autonomi con semantica propria (verifiche di legge, scadenze documentali): la
loro esistenza separata è legittima. `WorkMachine.next_maintenance_date` no: è una
*duplicazione* della stessa informazione che ora vive nelle occorrenze. Il codice lo ha già
riconosciuto a metà — `models.py:2545` documenta che la chiusura di un OdL **non scrive
più** quel campo — e il risultato è il peggiore dei due mondi: un campo ancora esposto in
cinque template, ancora modificabile a mano, e non più aggiornato da nulla. **Congela il
valore che aveva l'ultima volta che qualcuno lo ha toccato.** È la fonte parallela da
dismettere per prima.

**Conteggio delle sovrapposizioni — misurato il 2026-09-07** con
`manut_audit --fonti-parallele`:

| Fonte | Asset distinti |
|---|---:|
| occorrenza aperta | **64** |
| scadenza amministrativa | **27** |
| verifica periodica | **0** |
| `WorkMachine.next_maintenance_date` | **0** |

**Asset con scadenza attiva in più di una fonte: 27**, tutti nella stessa combinazione
*occorrenza aperta + scadenza amministrativa* (carroponti `APS-CRP-*`, gru `APS-GRU-*`,
magneti, pinze, sottotrave, i due Kardex, un chiller HVAC).

Questo **corregge in meglio** la valutazione qui sopra, su due punti:

1. **`WorkMachine.next_maintenance_date` non è un campo congelato con dati dentro: è
   vuoto.** Nessun asset lo ha valorizzato. Non c'è nulla da migrare e nessun dato da
   perdere: la rimozione dai cinque template e dal form è pura pulizia, e va fatta proprio
   perché un campo vuoto esposto in pagina è peggio di un campo assente — mostra una colonna
   che non si riempirà mai.
2. **Le verifiche periodiche attive con una prossima data sono zero.** Il sottodominio
   esiste nel modello ma non è in uso.

**Resta un solo caso reale da chiarire**, ed è quello dei 27 asset: il piano di
manutenzione supporta il tipo *scadenza amministrativa*, quindi la stessa scadenza può
essere tracciata **due volte** — una come `AssetAdministrativeDeadline`, una come
occorrenza di un piano amministrativo. Va guardato asset per asset se sono la stessa cosa
in doppio o due scadenze legittimamente distinte (per un carroponte: verifica di legge
*e* manutenzione ordinaria). Se sono in doppio, è l'unica sovrapposizione da risolvere
davvero.

---

## Appendice B — Matrice a tre colonne (§B del mandato)

| | `main` | `release/prod` | Pacchetto installato |
|---|---|---|---|
| Commit | `da17aa03` | `9fc8e3a6` | `9fc8e3a6` |
| Versione | 1.4.0 | 1.4.0 | **1.4.0** |
| Data | — | 2026-09-06 19:16 | build 2026-09-06 19:29, attivato **2026-09-07 09:01** |
| `generate_maintenance_occurrences` | sì | sì | **sì** |
| `generate_scheduled_workorders` | no | no | **no** |
| Job schedulato nel codice | `assets_generate_occurrences` | idem | idem |
| Fase F `a7d76223` | sì | sì | **sì** |
| Fase G2 `70e3889f` | sì | sì | **sì** |
| Migration `assets.0098`/`0099` | sì | sì | **applicate** il 07-09 |
| Migration `assets.0100` | **sì** | **no** | **no** |

`release/prod` è indietro rispetto a `main` di 4 commit — `da17aa03`, `eaa516f6`,
`b716bca3`, `f35f5bad` (registrazione massiva OdL; sidebar manutenzione con filtro e
blocchi «Da fare» apribili), più la migration `assets/0100_sidebar_manutenzione_riordino`.
Sono funzionalità di UI: **non toccano i motori di generazione**, e la loro assenza in
produzione non incide su nulla di quanto documentato qui. Il loro rilascio resta una
decisione separata, fuori dal perimetro di questo documento.

Per il dominio della generazione, quindi, **le tre colonne coincidono**. La divergenza
non è tra i tre stati del codice: è tra il codice installato e ciò che è registrato nel
database dello scheduler (§2.2).

---

## Appendice C — Metodo e limiti

**Cosa è stato letto:** il codice di `main` (`da17aa03`) nel worktree dedicato; i file
`BUILD_INFO.json`, i log di promote, il log del cluster e gli alberi delle release sotto
`Y:\` (sola lettura); la storia dei commit; i due file Excel.

**Cosa NON è stato fatto:** nessuna connessione al database di produzione, nessuna
scrittura di alcun tipo, nessuna esecuzione di comandi applicativi in produzione, nessun
`checkout` o allineamento di `release/prod`.

**Dai log di produzione sono stati estratti esclusivamente fatti tecnici** — nomi di job,
timestamp, versioni, nomi di migrazioni. Nessun contenuto applicativo, nessun dato
personale, nessuna credenziale è stato letto o riportato.

**Limite dichiarato in prima stesura, e come si è chiuso.** Le conclusioni su *cosa è
registrato nello scheduler* erano inferite dal codice e dagli artefatti di deploy, non
osservate a DB, e la prima stesura avvertiva: *«se la verifica smentisce §2.2 — per esempio
perché `setup_q_schedules` è stato eseguito a mano dopo il deploy — cade la conclusione
operativa più importante di questo documento»*.

**È andata esattamente così.** La verifica del 2026-09-07 (§2.3) mostra la tabella
allineata: `setup_q_schedules` era stato lanciato dalla Centrale di comando. La previsione
di guasto era sbagliata ed è stata riscritta in §2.2, §2.3, §2.4, nell'esito esecutivo e
in §7.2. Sopravvive il rilievo di processo — il promote non registra gli schedule — che
resta valido perché riguarda il percorso automatico, non l'esito di questa singola release.

Gli altri limiti restano: la prima corsa del motore nuovo (08-09) non è ancora osservata, e
i conteggi di §4 e dell'Appendice A richiedono il DB di produzione.

**Assunzione dichiarata in §5.4:** le periodicità usate nella simulazione provengono da
`MaintenanceRule.threshold_value` (colonna `note` del foglio del 04-09) e si assume siano
state migrate come ricorrenze `DAYS/N`. L'anteprima dell'import mostra la ricorrenza
effettivamente risolta per ogni riga: è quella a fare fede.
