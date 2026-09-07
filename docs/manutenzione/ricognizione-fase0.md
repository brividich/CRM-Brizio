# Ricognizione Fase 0 — modello degli stati della manutenzione

Documento di sola lettura, preparatorio al refactoring del modello degli stati.
Nessun file applicativo è stato modificato. I due deliverable sono questo report e
`django_app/assets/management/commands/manut_audit.py`.

**Regola seguita:** nessun nome di modello, campo o funzione è stato assunto; tutti
sono ricavati dal codice, con riferimento `file:riga`. Dove il codice non dà una
risposta certa è scritto **non determinato**, con l'indicazione di cosa servirebbe
per determinarla.

---

## 0. Provenienza dei riferimenti e stato del checkout

### 0.1 Snapshot

I riferimenti `file:riga` provengono da uno **snapshot** dei file preso all'inizio
della sessione, non dal checkout condiviso (che può cambiare sotto). Lo snapshot è
in `…\scratchpad\snapshot\` con le impronte sha1 in `snapshot_hashes.txt`.

La lettura è avvenuta sul worktree dedicato `C:\Dev\pn-manut-ricognizione`, branch
`docs/manut-ricognizione-fase0` creato da `origin/main` (`da17aa03`), **dopo aver
verificato che worktree e snapshot coincidono byte per byte** (unica differenza:
i terminatori di riga della migration `0100`, vedi §0.4).

### 0.2 `git status` del checkout condiviso `C:\Dev\Portale Novicrom`

HEAD: `9fc8e3a6` su `release/prod` — *Merge branch 'main' into release/prod*, 2026-09-06 19:16.

```
 M CHANGELOG.md
 M README.md
 M django_app/assets/forms_maintenance.py
 M django_app/assets/templates/assets/base_shell.html
 M django_app/assets/templates/assets/components/_workorder_occurrences.html
 M django_app/assets/templates/assets/components/maintenance_domain_styles.html
 M django_app/assets/templates/assets/pages/asset_list.html
 M django_app/assets/templates/assets/pages/maintenance_da_fare.html
 M django_app/assets/tests_maintenance_ui.py
 M django_app/assets/urls.py
 M django_app/assets/views.py
 M django_app/assets/views_maintenance.py
?? django_app/assets/migrations/0100_sidebar_manutenzione_riordino.py
```

`git diff --cached --stat` è vuoto: **niente è staged**.

### 0.3 `git diff --stat` dello snapshot

```
 CHANGELOG.md                                       |  13 ++
 README.md                                          |   4 +-
 django_app/assets/forms_maintenance.py             |  35 +++++
 django_app/assets/templates/assets/base_shell.html | 161 +++++++++++++++++---
 .../assets/components/_workorder_occurrences.html  | 137 +++++++++++++++--
 .../components/maintenance_domain_styles.html      |  16 ++
 .../assets/templates/assets/pages/asset_list.html  | 100 +++++++++++-
 .../assets/pages/maintenance_da_fare.html          | 118 ++++++++++---
 django_app/assets/tests_maintenance_ui.py          | 167 +++++++++++++++++++++
 django_app/assets/urls.py                          |   5 +
 django_app/assets/views.py                         |  94 ++++++++++--
 django_app/assets/views_maintenance.py             |  82 ++++++++++
 12 files changed, 861 insertions(+), 71 deletions(-)
```

### 0.4 Provenienza della migration `0100` non tracciata — **non è orfana**

`django_app/assets/migrations/0100_sidebar_manutenzione_riordino.py` è committata in:

- **`f35f5bad`** — *feat(assets): sidebar manutenzione completa con filtro, blocchi
  «Da fare» apribili e selezionabili*, 2026-09-07 11:37:48 +0200, autore `brividich`.

Il commit è contenuto in `main`, `origin/main`,
`feature/assets-sidebar-manutenzione-ui`, `feature/assets-odl-registrazione-massiva`.
**Non** è antenato di `HEAD` (`release/prod`): è per questo che `git status` mostra il
file come non tracciato — esiste su disco ma il branch corrente non lo conosce.

Contenuto identico a quello committato; unica differenza rispetto al checkout di `main`
sono i terminatori di riga (3700 B con LF nel checkout condiviso, 3780 B con CRLF nel
worktree: 80 righe, 80 CR di differenza).

### 0.5 Conseguenza sulla segregazione `[COMMITTED]` / `[WIP-NON-COMMITTATO]`

Confronto byte per byte dello snapshot contro un checkout pulito di `main` (`da17aa03`,
allineato a `origin/main`):

| file | esito |
|---|---|
| `CHANGELOG.md`, `README.md`, `forms_maintenance.py`, `base_shell.html`, `_workorder_occurrences.html`, `maintenance_domain_styles.html`, `asset_list.html`, `maintenance_da_fare.html`, `tests_maintenance_ui.py`, `urls.py`, `views.py`, `views_maintenance.py` | **identico a `main`** |
| `0100_sidebar_manutenzione_riordino.py` | identico salvo line endings |

**Tutti i file "sporchi" sono contenuto già committato e già pushato su `origin/main`.**
Non esiste lavoro non salvato. Il checkout condiviso ha semplicemente `HEAD` su
`release/prod` e albero di lavoro su `main`: `release/prod` è indietro di quei commit e
il delta si presenta come modifiche locali.

Perciò **ogni riferimento in questo documento è `[COMMITTED]`**, sul commit `da17aa03`
(`main` = `origin/main`) salvo dove indicato diversamente. Il marcatore
`[WIP-NON-COMMITTATO]` non ricorre perché nel repository non c'è nulla che lo meriti.
Nota operativa, fuori scope: quel contenuto **non è in `release/prod`**, quindi non è
in produzione.

I file sporchi non sono cambiati durante la ricognizione (impronte sha1 invariate).

### 0.6 Nota di contesto

Sul repository sono attivi altri worktree: `pn-manut-refactor`
(`feature/assets-manutenzione-refactor`), `pn-manutenzione-ux`, `pn-merge`, e
`temp/codex-manut-audit` su branch `codex/audit-manutenzioni` **dentro** il checkout
condiviso. Quest'ultimo, dal nome, sembra un lavoro di audit manutenzioni già in corso
altrove; non è stato aperto né considerato.

---

## 1. Scheduling — come si calcola la scadenza successiva

**Priorità massima. Risposta netta: dipende dall'ancoraggio, e in nessun caso da oggi.**

### 1.1 La funzione di calcolo

Sono due funzioni in cascata.

**(a) `compute_next_due`** — `django_app/assets/services/recurrence.py:185-204` `[COMMITTED]`

```python
def compute_next_due(
    spec_source,
    *,
    anchor: str,
    previous_due: date | None,
    completion_date: date | None,
) -> date | None:
    """Prossima scadenza dopo il completamento di un'occorrenza.

    ``FROM_COMPLETION`` parte dalla data reale di esecuzione, ``FIXED_CALENDAR``
    dalla scadenza teorica. Se manca la base di partenza dell'ancoraggio scelto si
    ripiega sull'altra: meglio una scadenza approssimata che nessuna scadenza.
    """
    if anchor == ANCHOR_FIXED_CALENDAR:
        base = previous_due or completion_date
    else:
        base = completion_date or previous_due
    if base is None:
        return None
    return add_recurrence(spec_source, base)
```

**(b) `complete_occurrence`** — `django_app/assets/services/maintenance_domain.py:412-491` `[COMMITTED]`.
Estratto integrale della parte che calcola e crea la scadenza successiva
(righe 452-491):

```python
    if not create_next:
        return None
    assignment = occurrence.assignment
    if assignment is None or not assignment.is_active or assignment.is_excluded or not assignment.auto_generate:
        return None

    next_due = compute_next_due(
        assignment,
        anchor=occurrence.schedule_anchor or assignment.effective_schedule_anchor,
        previous_due=occurrence.due_date,
        completion_date=occurrence.completed_on,
    )
    if next_due is None:
        return None

    # Un'amministrativa chiusa con molto ritardo puo' avere la "prossima" gia'
    # passata: si avanza fino alla prima scadenza non ancora superata, senza
    # inventare occorrenze intermedie che nessuno eseguira'.
    if occurrence.schedule_anchor == ANCHOR_FIXED_CALENDAR:
        guard = 0
        while next_due < occurrence.completed_on and guard < 500:
            next_due = add_recurrence(assignment, next_due)
            guard += 1

    try:
        return MaintenanceOccurrence.objects.create(
            plan=occurrence.plan,
            assignment=assignment,
            asset=occurrence.asset,
            due_date=next_due,
            warning_days=occurrence.warning_days,
            schedule_anchor=occurrence.schedule_anchor,
            previous_due_date=occurrence.due_date,
            supplier=assignment.effective_supplier,
            source=MaintenanceOccurrence.SOURCE_SCHEDULER,
        )
    except IntegrityError:
        return MaintenanceOccurrence.objects.filter(
            plan=occurrence.plan, asset=occurrence.asset, due_date=next_due
        ).first()
```

Dove `completed_on` viene fissato poco sopra, `maintenance_domain.py:435`:

```python
    occurrence.completed_on = completed_on or timezone.localdate()
```

`add_recurrence` è a `recurrence.py:158-182`; i due ancoraggi sono definiti a
`recurrence.py:36-37` e sui modelli a `models.py:3340-3346`
(`MaintenancePlanAssignment.ANCHOR_FROM_COMPLETION` / `ANCHOR_FIXED_CALENDAR`).

### 1.2 Da quale data si calcola: risposta senza ambiguità

| ancoraggio | base del calcolo | riferimento |
|---|---|---|
| `FROM_COMPLETION` (default) | **data di esecuzione inserita dall'utente** (`completed_on`); se assente, la scadenza teorica dell'occorrenza chiusa | `recurrence.py:201` |
| `FIXED_CALENDAR` | **data pianificata dell'occorrenza chiusa** (`due_date`); se assente, la data di esecuzione | `recurrence.py:199` |

**La data odierna non entra mai nel calcolo della scadenza successiva.** `timezone.localdate()`
compare solo come *default* di `completed_on` quando l'utente non ne indica una
(`maintenance_domain.py:435`), e come `initial` del campo del form
(`forms_maintenance.py:467` e `:517`). Se l'utente scrive una data, è quella a comandare.

La data di esecuzione è inserita dall'utente in due punti:

- singola: `OccurrenceCompletionForm.completed_on` — `forms_maintenance.py:449-452`,
  usata dalla view `occurrence_complete` — `views_maintenance.py:1271`;
- in blocco su un OdL: `OccurrenceBulkCompletionForm.completed_on` —
  `forms_maintenance.py:501-504`, usata da `workorder_occurrences_complete` —
  `views_maintenance.py:1195` e `:1212`.

Unico vincolo di validazione su quella data: **non può essere nel futuro**
(`forms_maintenance.py:487-488` e `:520-524`). **Nessun vincolo verso il passato.**

### 1.3 Sonda eseguibile (eseguita su dev, in rollback garantito)

La sonda ha girato dentro `transaction.atomic()` uscendo dal blocco con un'eccezione
dedicata, quindi con rollback garantito anche in caso di errore; una verifica
indipendente dopo il rollback ha contato **0** oggetti sonda rimasti a DB.
DB: SQL Server locale `PORTALE NOVICROM` su `localhost\SQLEXPRESS`
(`config.settings.dev`). Asset di prova: il primo asset in uso (`#1 IT-000001`).
Ricorrenza: ogni 30 giorni. Data di riferimento: 07-09-2026.

| caso | scadenza chiusa | eseguita il | **prossima generata** | atteso se `esecuzione + 30` |
|---|---|---|---|---|
| 1. esecuzione = oggi, `FROM_COMPLETION` | 02-09-2026 | 07-09-2026 | **07-10-2026** | 07-10-2026 ✓ |
| 2. esecuzione = 60 gg fa, `FROM_COMPLETION` | 04-07-2026 | 09-07-2026 | **08-08-2026** ← già scaduta da 30 gg | 08-08-2026 ✓ |
| 2bis. stesso caso, `FIXED_CALENDAR` | 04-07-2026 | 09-07-2026 | **03-08-2026** ← già scaduta da 35 gg | (guardia attiva, non applicata) |
| 3. esecuzione anteriore alla precedente, `FROM_COMPLETION` | 27-09-2026 | 09-06-2026 | **09-07-2026** ← già scaduta da 60 gg | 09-07-2026 ✓ |

Percorso di codice attraversato, identico nei quattro casi:
`views_maintenance.occurrence_complete` → `domain.complete_occurrence`
(`maintenance_domain.py:412`) → `compute_next_due` (`recurrence.py:185`) →
`add_recurrence` (`recurrence.py:158`, ramo `FREQ_DAYS`, `recurrence.py:163-164`) →
`MaintenanceOccurrence.objects.create` (`maintenance_domain.py:477`).
Nel caso 2bis è stato valutato anche il `while` di `maintenance_domain.py:472`, che
**non ha eseguito nessuna iterazione** (vedi §1.5).

### 1.4 Cosa succede se la data di esecuzione è anteriore alla precedente esecuzione

**Nulla la impedisce, e nulla la segnala.** Non esiste alcun confronto fra `completed_on`
e l'ultima esecuzione registrata: né nei form (`forms_maintenance.py:486-489`, `:520-524`,
che controllano solo il futuro), né in `complete_occurrence`
(`maintenance_domain.py:427-450`, che verifica solo `status == DONE` e l'allegato
obbligatorio).

Esito osservato nella sonda 3: chiusa un'occorrenza il 28-08-2026 (prossima → 27-09-2026),
la registrazione successiva con data 09-06-2026 ha prodotto una scadenza al **09-07-2026**,
cioè **precedente alla scadenza appena chiusa** e già nel passato di 60 giorni. Lo storico
del piano è rimasto con esecuzioni in ordine `['2026-06-09', '2026-08-28']`: la
manutenzione risulta "regredita".

Effetto collaterale rilevato per lettura: `generate_occurrences` sceglie come "ultima
esecuzione" della coppia (piano, asset) **l'ultima riga letta** ordinando per
`completed_on, due_date, id` (`maintenance_domain.py:325-328`), quindi la data massima —
mentre `complete_occurrence` lavora sull'occorrenza che si sta chiudendo. Le due
funzioni possono partire da basi diverse quando le esecuzioni non sono in ordine
cronologico. **Non determinato** l'impatto pratico: dipende da quante coppie abbiano
esecuzioni fuori ordine, misurabile solo sui dati di produzione.

### 1.5 Protezione contro scadenze generate già nel passato

**Non esiste una protezione rispetto a oggi. Esiste una sola guardia, parziale, e solo
per `FIXED_CALENDAR`.**

- **`FROM_COMPLETION`**: nessuna guardia. `next_due = completed_on + ricorrenza`. Se
  l'esecuzione è più vecchia della ricorrenza, la scadenza nasce già scaduta
  (sonde 2 e 3).
- **`FIXED_CALENDAR`**: la guardia di `maintenance_domain.py:470-474` è
  `while next_due < occurrence.completed_on`. Avanza finché la prossima scadenza non
  supera la **data di esecuzione**, non la data odierna. Nella sonda 2bis la condizione
  era già falsa alla prima valutazione (03-08-2026 > 09-07-2026) e il ciclo non è mai
  entrato: la scadenza è nata comunque nel passato di 35 giorni.

Esiste invece una protezione **diversa e su un altro percorso**: `first_due_date_for`
(`recurrence.py:207-221`) avanza di ricorrenza in ricorrenza fino a raggiungere `today`,
ma serve solo alla **prima** scadenza quando non c'è storico, ed è chiamata da
`compute_due_date_for` (`maintenance_domain.py:281`) con `today=start` — cioè con la
data di partenza al posto di oggi, il che ne annulla di fatto l'effetto di avanzamento.

**Discrepanza da segnalare al refactoring:** riga 460 risolve l'ancoraggio con
`occurrence.schedule_anchor or assignment.effective_schedule_anchor` (fallback
sull'applicazione), mentre la guardia di riga 470 confronta **solo**
`occurrence.schedule_anchor`. Se il campo persistito fosse stringa vuota, il calcolo
userebbe l'ancoraggio dell'applicazione ma la guardia verrebbe saltata. Il campo ha
`default=ANCHOR_FROM_COMPLETION` e non è nullable (`models.py:3621-3625`), quindi il
caso richiede una valorizzazione esplicita a `""`: **non determinato** se esista a DB,
verificabile con un conteggio in produzione.

---

## 2. Modello degli stati

### 2.1 Occorrenza — `MaintenanceOccurrence` (`models.py:3565`)

**Stati persistiti**, campo `status` (`models.py:3632`, `max_length=12`, `db_index=True`,
default `OPEN`) — definiti a `models.py:3573-3581`:

| valore | etichetta |
|---|---|
| `OPEN` | Aperta |
| `DONE` | Eseguita |
| `CANCELED` | Annullata |

**Stati visuali derivati, NON persistiti** — costanti a `models.py:3594-3603`, funzione
di calcolo `occurrence_view_state` a `maintenance_domain.py:549-577`:

| stato derivato | da cosa è calcolato | riga |
|---|---|---|
| `canceled` | `status == CANCELED` | `:551-552` |
| `report_missing` | `status == DONE` e (allegato obbligatorio mancante) oppure (occorrenza esterna senza `report_received_at` né allegati) | `:558-561` |
| `completed` | `status == DONE` e nessuna delle due condizioni sopra | `:562` |
| `waiting` | occorrenza legata a un OdL `OPEN` con `work_order.is_waiting` | `:566-568` |
| `in_progress` | OdL `OPEN` con `started_at` valorizzato | `:569-570` |
| `planned` | OdL `OPEN`, non in attesa, non iniziato | `:571` |
| `overdue` | nessun OdL aperto e `due_date < oggi` | `:573-574` |
| `due_soon` | `warning_date <= oggi` (dove `warning_date = due_date - warning_days`, proprietà a `models.py:3704-3707`) | `:575-576` |
| `to_plan` | tutto il resto | `:577` |

Etichette, classi badge e ordine operativo: `maintenance_domain.py:508-546`.
Payload per i template: `occurrence_state_payload`, `:580-588`.

**Punti che scrivono `MaintenanceOccurrence.status`** — l'elenco è chiuso, sono due:

| punto | operazione | riga |
|---|---|---|
| `complete_occurrence` | `status = DONE` | `maintenance_domain.py:434` |
| `cancel_occurrence` | `status = CANCELED` | `maintenance_domain.py:495` |

Nessuna view, nessun signal, nessun task e nessun comando assegna direttamente
`occurrence.status`: tutti passano da queste due funzioni. In `views_maintenance.py`
non esiste alcuna assegnazione a `.status` (verificato per grep).

**Punti che creano occorrenze con uno stato iniziale** (non transizioni, ma vanno
inventariati perché fissano lo stato di partenza):

| punto | stato creato | riga |
|---|---|---|
| `generate_occurrences` (scheduler) | `OPEN` (default) | `maintenance_domain.py:376` |
| `complete_occurrence` (occorrenza successiva) | `OPEN` (default) | `maintenance_domain.py:477` |
| `maintenance_history_import.apply_report` | `DONE` e `OPEN` | `services/maintenance_history_import.py:337`, `:344`, `:359` |
| `migrate_maintenance_to_plans` (storico) | `DONE` | `management/commands/migrate_maintenance_to_plans.py:276-286` |
| `migrate_maintenance_to_plans` (scadenze amministrative) | `DONE` e `OPEN` | idem `:350-362`, `:367-375` |

**Non esiste un `ModelAdmin` registrato per `MaintenanceOccurrence`** (verificato in
`admin.py`): lo stato dell'occorrenza non è modificabile dall'admin Django.

### 2.2 Ordine di lavoro — `WorkOrder` (`models.py:2155`)

**Stati persistiti**, campo `status` (`models.py:2306`, `max_length=20`, default `OPEN`) —
definiti a `models.py:2175-2182`:

| valore | etichetta |
|---|---|
| `OPEN` | Aperta |
| `DONE` | Chiusa |
| `CANCELED` | Annullata |

**Sotto-stato operativo dentro `OPEN`, NON persistito** — `operational_state`,
proprietà calcolata a `models.py:2619-2631`, costanti a `models.py:2211-2220`:

| valore | condizione | riga |
|---|---|---|
| `None` | `status != OPEN` | `:2613-2614` |
| `waiting` | `is_waiting == True` | `:2615-2616` |
| `in_progress` | `started_at` valorizzato | `:2617-2618` |
| `assigned` | `assigned_to_id` valorizzato | `:2619-2620` |
| `unassigned` | nessuna delle precedenti | `:2621` |

Il commento del codice dichiara la scelta: evitare un secondo campo di stato da tenere
in sync (`models.py:2616-2618`). Altre proprietà derivate: `operational_state_label`
(`:2634-2637`), `is_overdue` (`:2639-2641`, `status == OPEN and due_at < now`).

**Campi ortogonali allo stato**, persistiti, che il refactoring deve considerare parte
del modello degli stati di fatto:

- `is_waiting` + `wait_reason` + `wait_note` + `waiting_since` (`models.py:2381-2390`).
  Il commento dichiara esplicitamente che non cambiano `status` per non alterare i
  filtri esistenti su `STATUS_OPEN`.
- `outcome` (`models.py:2391-2399`): `RESOLVED` / `RESOLVED_TEMP` / `NOT_RESOLVED`,
  vuoto per aperti e annullati.
- `priority` (`:2289-2295`), `started_at` (`:2301-2305`), `due_at` (`:2296-2300`).

**Mappa completa dei punti che scrivono `WorkOrder.status`:**

| # | punto | operazione | riga |
|---|---|---|---|
| 1 | `WorkOrder.close()` — metodo unico di chiusura/annullamento/riapertura | `self.status = status` (parametro, default `DONE`); imposta `closed_at`, e `started_at` se manca | `models.py:2498` |
| 2 | `views.workorder_close` | unica chiamata a `close()` nel codice applicativo | `views.py:15502` |
| 3 | `views._build_execution_workorder` | crea con `OPEN` (`:2794`) e subito dopo assegna `status = DONE` senza passare da `close()` | `views.py:2788` e `views.py:2800` |
| 4 | `views.workorder_create` | `workorder.status = WorkOrder.STATUS_OPEN` sulla creazione da form | `views.py:14800` |
| 5 | `domain.create_workorder_from_occurrences` | crea con `status=WorkOrder.STATUS_OPEN` | `maintenance_domain.py:641` |
| 6 | `services/__init__.generate_workorders_for_rule` | crea con `STATUS_OPEN` | `services/__init__.py:214` |
| 7 | `maintenance.py` (generazione da regola) | crea con `STATUS_OPEN` | `maintenance.py:530` |
| 8 | `management/commands/import_assets_excel` | crea con `STATUS_DONE` | `:867`, `:875` |
| 9 | `management/commands/import_collaudo_history` | crea con `STATUS_DONE` | `:213` |
| 10 | `services/periodic_migration` | crea con `STATUS_DONE` | `:170` |
| 11 | **Django admin** — `WorkOrderAdmin` (`admin.py:347-352`) è un `ModelAdmin` senza `readonly_fields` e senza `fields`: **`status` è modificabile a mano dall'admin**, fuori da ogni transizione | `admin.py:347` |

Nessun signal e nessun task periodico scrive `status`: `tasks.py` (45 righe) si limita a
invocare `generate_maintenance_occurrences` e `send_maintenance_reminders`.

**Da segnalare (#3):** `_build_execution_workorder` bypassa `close()`. Non passando dal
metodo, non esegue né la logica di `started_at` né gli `update_fields` di `close()`;
imposta a mano `closed_at`, `status`, `resolution`, `intervention_duration_minutes`,
`cost_eur` e chiama `full_clean()` + `save()` (`views.py:2799-2807`).

**Da segnalare (#2):** in `workorder_close` esiste una transizione "fantasma": la
richiesta `DONE` con esito `NOT_RESOLVED` viene convertita in `OPEN` prima di chiamare
`close()` (`views.py:15494-15500`), con la motivazione esplicita di non far avanzare la
scadenza. È una regola di stato scritta nella view, non nel modello.

### 2.3 Relazione fra i due stati

**Non c'è propagazione automatica.** Chiudere un OdL non registra le occorrenze che
raccoglie: `workorder_close` conta le occorrenze rimaste `OPEN` e mostra soltanto un
avviso (`views.py:15618-15637`). Il commento a `views.py:15613-15617` lo dichiara come
scelta. È l'origine del debito storico del §3.

Al contrario, registrare un'occorrenza non chiude l'OdL:
`workorder_occurrences_complete` conta le occorrenze rimaste e suggerisce la chiusura
con un `messages.info` (`views_maintenance.py:1232-1241`).

---

## 3. Debito storico — OdL chiusi con occorrenze non registrate

**Da eseguire in produzione.**

**Definizione operativa adottata** (dal codice, §2.3): `WorkOrder.status in (DONE,
CANCELED)` con almeno una `MaintenanceOccurrence` collegata in `status = OPEN`.
"Giorni di scoperto" = giorni fra `closed_at` e la data di esecuzione del comando;
`n.d.` quando `closed_at` è nullo (possibile: il campo è `null=True`, `models.py:2337`).

I conteggi si producono con:

```powershell
python django_app\manage.py manut_audit
```

Il comando stampa: totale OdL, totale occorrenze rimaste aperte, il dettaglio riga per
riga (id, stato, data di chiusura, aperte/totali, giorni di scoperto, asset capofila e
piani coinvolti) e la distribuzione per mese di chiusura.

Il valore su dev è privo di significato statistico (vedi §8).

---

## 4. Uso reale — ultimi 12 mesi

**Da eseguire in produzione.** `python django_app\manage.py manut_audit --months 12`.

Due delle quattro domande **non sono pienamente ricostruibili dal DB**, e il comando lo
dichiara nel proprio output invece di stimarle:

1. **OdL creati per mese** — ricostruibile solo per approssimazione. `WorkOrder` **non
   ha alcun campo di creazione**: né `created_at` né `created_by` (verificato sull'intera
   definizione della classe, `models.py:2155-2445`). L'unico riferimento temporale è
   `opened_at` (`models.py:2336`, `default=timezone.now`), che però viene
   deliberatamente retrodatato dalle registrazioni storiche
   (`views.py:2788`: `opened_at=executed_at_dt`). Il conteggio per mese usa `opened_at`
   con questa avvertenza.

2. **Utenti distinti che hanno creato almeno un OdL** — **non determinato.** Non esiste
   il dato. Per determinarlo servirebbe un campo `created_by` su `WorkOrder`,
   valorizzato alla creazione in tutti i percorsi elencati al §2.2 (#3-#10). Il comando
   stampa una **prossima esplicitamente etichettata come tale**: gli autori distinti dei
   `WorkOrderLog` (`models.py:2738-2748`, campo `author`, `null=True`) collegati agli OdL
   della finestra. È un **limite inferiore**: esiste solo per gli OdL nati da un percorso
   che scrive un log, e l'autore può essere nullo.

3. **Occorrenze registrate dentro un OdL contro registrate senza OdL** — ricostruibile.
   `MaintenanceOccurrence.status = DONE` con `work_order_id` non nullo / nullo
   (`models.py:3633-3640`). Il comando lo produce sia per origine (`source`) sia per mese.

4. **Utenti distinti che hanno registrato** — ricostruibile. `completed_by`
   (`models.py:3649-3655`), popolato da `complete_occurrence`
   (`maintenance_domain.py:436`) solo se l'utente è autenticato. Le occorrenze create
   dagli import e dalle migrazioni hanno `completed_by` nullo: sono registrazioni senza
   autore, e il comando le conta a parte (colonna `con autore`).

---

## 5. Filtri della pagina «Da fare»

### 5.1 Filtri implementati

Form condiviso `OccurrenceFilterForm` — `forms_maintenance.py:581-638`, applicato da
`_apply_occurrence_filters` — `views_maintenance.py:174-228`. La pagina è
`maintenance_da_fare` — `views_maintenance.py:281-385`.

| parametro | tipo | effetto | riga di applicazione |
|---|---|---|---|
| `q` | testo | `icontains` su `plan__label`, `asset__asset_tag`, `asset__name`, `asset__internal_number` | `:180-187` |
| `plan` | FK piano | uguaglianza su `plan` | `:188-189` |
| `group` | FK gruppo | `asset__group_memberships__group` | `:190-191` |
| `asset` | FK asset | uguaglianza | `:192-193` |
| `reparto` | scelta da valori distinti di `Asset.reparto` | uguaglianza | `:194-195` |
| `assignee` | FK utente | `work_order__assigned_to` | `:196-197` |
| `supplier` | FK fornitore | uguaglianza | `:198-199` |
| `plan_type` | `ordinary` / `administrative` | include/esclude `plan__maintenance_type = ADMINISTRATIVE` | `:201-205` |
| `execution_mode` | `INTERNAL` / `EXTERNAL` | modalità effettiva: applicazione se valorizzata, altrimenti piano | `:207-215` |
| `planning` | `unplanned` / `planned` | `work_order` nullo (+ `status=OPEN`) / non nullo | `:217-221` |
| `window` | `overdue` / `7` / `30` / `90` | scadute, oppure `due_date <= oggi + N` | `:223-227` |
| `report_missing` | booleano | **non applicato in `_apply_occurrence_filters`** — vedi sotto | — |
| `by` | `plan` / `group` / `asset` | non è un filtro: cambia il raggruppamento della vista | `:342-345` |

Oltre ai filtri espliciti, la pagina applica uno **scope automatico per reparto**:
`_apply_caporeparto_scope` (`views_maintenance.py:154-172`) preimposta il filtro sui
reparti di cui l'utente risulta caporeparto (`Reparto.caporeparto_legacy_id`,
`views_maintenance.py:123-152`), **solo se** `reparto` non è già presente in query
string, e lo disattiva se azzererebbe la pagina. Non è una barriera di sicurezza: la
pagina lo dichiara e basta un click per toglierlo.

Due osservazioni per il refactoring:

- **`report_missing` è dichiarato nel form ma non applicato in
  `_apply_occurrence_filters`.** È applicato solo nella pagina «Scadenze»
  (`views_maintenance.py:399-400`) e nel quadro responsabile (`:450`). Su «Da fare» il
  parametro non ha effetto. Riferimenti: dichiarazione `forms_maintenance.py:618`,
  applicazione altrove `views_maintenance.py:399`.
- I **blocchi** della pagina (`Scadute`, `Da fare entro 7 giorni`, `Programmate`,
  `In attesa`, `Esterne` — `views_maintenance.py:295-341`) sono calcolati **in Python
  sulle righe già caricate**, non in SQL, e la lista è troncata a 1000 righe
  (`views_maintenance.py:293`). Oltre quella soglia i conteggi dei blocchi e il totale
  sono silenziosamente parziali.

### 5.2 Esiste logging delle query string?

**No.** Verificato:

- `core/audit_middleware.py` non contiene alcun riferimento a `request.GET`,
  `QUERY_STRING`, `get_full_path` o `full_path`;
- `core.models.AuditLog` (`core/models.py:567-592`) registra `azione`, `modulo`,
  `dettaglio` (JSON), `ip_address`, `oggetto_tipo`, `oggetto_id`: nessun campo
  contiene l'URL o i parametri della richiesta, e nessuna delle view di manutenzione
  scrive un `AuditLog` di consultazione;
- le view di §5.1 non emettono alcun log applicativo dei parametri.

**Conclusione: l'uso reale dei filtri non è misurabile con i dati attualmente raccolti.**
Nessuna stima è possibile a posteriori: il dato non è mai stato prodotto.

### 5.3 Modo meno invasivo di misurarlo — proposta

Il criterio è: nessuna modifica alle view, nessuna query in più sul percorso di lettura,
nessun dato personale oltre a quelli già trattati dall'audit esistente.

**Proposta minima** — un middleware di sola scrittura, campionato, limitato a una
allowlist di percorsi:

1. Un middleware nuovo (nessuna riga toccata in `views_maintenance.py`) che, per i soli
   path in una costante `MAINTENANCE_USAGE_PATHS` (`/assets/manutenzione/da-fare/`,
   `/scadenze/`, `/quadro/`), su risposte `200` `GET`, scrive **un `AuditLog`** con
   `azione="filtro_manutenzione"`, `modulo="assets"` e in `dettaglio` **solo i nomi dei
   parametri valorizzati**, non i valori: `{"filtri": ["window", "plan_type"], "by": "plan"}`.
   Salvare i nomi e non i valori evita del tutto la questione dei dati personali
   (`assignee`, `asset`, `reparto` sono identificativi) e risponde comunque alla domanda
   "quali filtri vengono usati".
2. Riuso del modello `AuditLog` esistente: nessuna migrazione, nessuna tabella nuova.
3. Campionamento e interruttore: una `SiteConfig` o una variabile d'ambiente
   `MAINTENANCE_USAGE_SAMPLING` (0 = spento) per accendere la misura per una finestra di
   due o quattro settimane e poi spegnerla, evitando di far crescere `AuditLog` per
   sempre.
4. Lettura: una query aggregata su `dettaglio`, oppure — più semplice su SQL Server, che
   sui JSON è scomodo — una riga per filtro usato, così il conteggio è un `GROUP BY`
   banale.

Costo: un file nuovo, una voce in `MIDDLEWARE`, zero modifiche al dominio. Alternativa
ancora meno invasiva ma meno affidabile: leggere i `Referer` dai log IIS, che però non
sono strutturati e non distinguono i redirect.

---

## 6. Concetti non definiti

### 6.1 «Follow-up»

**Non è un modello.** È un `WorkOrder` collegato a un altro, tramite quattro campi
dedicati su `WorkOrder`:

| campo | tipo | significato | riga |
|---|---|---|---|
| `follow_up_date` | `DateField` null | data entro cui verificare un intervento chiuso come «Risolto temporaneamente» | `models.py:2399-2403` |
| `follow_up_of` | FK a `self`, `related_name="follow_ups"` | intervento originale | `models.py:2404-2412` |
| `follow_up_occurrence` | FK a `MaintenanceOccurrence` | occorrenza durante la quale è emerso il problema | `models.py:2414-2421` |
| `follow_up_checklist_item` | FK a `WorkOrderChecklist` | step KO / fuori range che l'ha originato | `models.py:2422-2429` |
| `follow_up_reason` | `TextField` | anomalia rilevata | `models.py:2430-2434` |

**Regola esatta — esistono due sorgenti distinte, e nessun flag unico le unifica:**

1. **Da esito di chiusura.** In `workorder_close`, se l'esito è `RESOLVED_TEMP`, il form
   **impone** una `follow_up_date` non anteriore alla chiusura (`forms.py:3104-3108`),
   la scrive sul padre e crea un `WorkOrder` figlio con `follow_up_of` valorizzato,
   `origin=MANUAL`, titolo `"Follow-up: <titolo padre>"`
   (`views.py:15541-15572`). `follow_up_occurrence` resta nullo.
2. **Da anomalia su una singola occorrenza.** `occurrence_followup_create`
   (`views_maintenance.py:1307-1341`) crea un `WorkOrder` con `follow_up_of` = OdL
   dell'occorrenza, `follow_up_occurrence` = l'occorrenza, `follow_up_checklist_item`
   opzionale e `follow_up_reason` obbligatorio (form `FollowUpForm`,
   `forms_maintenance.py:559`). Il commento a `models.py:2412-2413` motiva la scelta: un
   problema trovato durante una manutenzione massiva riguarda **un** asset, non il lotto.

Dove viene letto: il quadro responsabile conta e mostra i «Follow-up aperti» filtrando
`status=OPEN, follow_up_occurrence__isnull=False` (`views_maintenance.py:459-461`,
`:503`, `:520`) — cioè **conta solo la sorgente 2 e ignora la sorgente 1**. Il dettaglio
OdL mostra entrambe le direzioni del legame
(`templates/assets/pages/workorder_detail.html:212-213`).

**Numero di record attualmente presenti: da eseguire in produzione**,
`python django_app\manage.py manut_audit` (sezione punto 6). Il comando conta i
follow-up per stato e per sorgente, e in più i casi «risolto temporaneamente con data di
verifica già scaduta e nessun figlio», cioè le verifiche promesse e mai aperte.

### 6.2 «Conflitti di periodicità»

**Non sono persistiti da nessuna parte.** Sono uno stato calcolato a ogni lettura da
`build_plan_resolutions` — `maintenance_domain.py:142-238`.

**Regola esatta:**

1. Per ogni coppia (piano, asset) si raccolgono le applicazioni candidate — su asset,
   su gruppo (via `AssetGroupMembership`), su categoria (`maintenance_domain.py:176-190`).
2. Vince la **specificità** più alta: `ASSET`(3) > `GRUPPO`(2) > `CATEGORIA`(1)
   (`models.py:3503-3505`, `maintenance_domain.py:194-195`).
3. Se fra le vincitrici pari merito ce n'è una con `is_excluded`, l'esito è `excluded`
   (`maintenance_domain.py:203-213`).
4. Altrimenti si confronta la **firma di ricorrenza** di ciascuna vincitrice —
   `_recurrence_signature`, `maintenance_domain.py:113-130`: la tupla
   `(frequency, interval, weekday, week_of_month, day_of_month, month_of_year,
   warning_days, effective_schedule_anchor)`. **Se le firme distinte sono più di una,
   l'esito è `conflict`** (`maintenance_domain.py:215-224`). Due applicazioni che dicono
   la stessa cosa sui tempi non generano conflitto, anche se sono due.
5. Altrimenti vince l'applicazione con `id` più basso (`maintenance_domain.py:226`).

**Conseguenza operativa, che il refactoring deve tenere presente:** un conflitto
**sospende la generazione**. In `generate_occurrences` la coppia in conflitto viene
contata e saltata (`maintenance_domain.py:338-340`): per quell'asset e quel piano
**non nasce nessuna occorrenza**, e quindi non compare nessuna scadenza in nessuna
pagina. Un conflitto è un silenzio, non un allarme.

**Numero di casi attualmente presenti: da eseguire in produzione**, stesso comando
(`manut_audit`, sezione punto 6), che riporta coppie risolte / applicate / escluse /
in conflitto e il dettaglio delle applicazioni in competizione.

---

## 7. Matrice dei permessi

### 7.1 Dove vivono le rotte

Su 125 `path()` in `django_app/assets/urls.py`, **69 appartengono al modulo
manutenzione**:

| file | rotte |
|---|---|
| `django_app/assets/views.py` | **42** |
| `django_app/assets/views_maintenance.py` | **27** |

Delle 42 in `views.py`, **9 sono ritirate**: view di 3 righe che fanno solo `redirect`
verso la superficie nuova (`maintenance_rule_list` `views.py:11497`,
`maintenance_rule_create` `:11503`, `maintenance_rule_impact_preview` `:11509`,
`maintenance_rule_edit` `:11515`, `asset_maintenance_rule_list` `:11529`,
`maintenance_schedule` `:11844`, `maintenance_scadenzario` `:16352`,
`maintenance_coverage_matrix` `:16667`, `maintenance_todo` `:16731`).

### 7.2 I tre permessi ACL granulari

Definiti in `views_maintenance.py:73-91`, in cascata (chi può di più può anche di meno):

| funzione | permesso ACL | riga |
|---|---|---|
| `can_manage_maintenance_plans` | `_is_assets_admin` **oppure** `assets/admin_assets` | `:73-77` |
| `can_plan_maintenance` | quanto sopra **oppure** `assets/maintenance_planning` | `:80-84` |
| `can_execute_maintenance` | quanto sopra **oppure** `assets/maintenance_execute` | `:87-91` |

`_is_assets_admin` è definita a `views.py:3239-3241`:
`request.user.is_superuser or is_legacy_admin(legacy_user)` — è **esattamente** il gate
"superuser o admin legacy".

**Rilievo:** `maintenance_planning` e `maintenance_execute` sono dichiarati fra i
pulsanti ACL in `assets/acl_bootstrap.py:74-75`, quindi concedibili dal pannello Accessi.
**`admin_assets` non compare in `assets/acl_bootstrap.py`**: è dichiarato in
`admin_portale/views.py:274`. Le tre funzioni sopra dipendono da un'azione che il
bootstrap del modulo assets non registra: **non determinato** se sia effettivamente
concedibile e concessa in produzione, verificabile con `acl_diagnose` sui dati reali.

### 7.3 Matrice — `views_maintenance.py` (27 rotte, 24 view)

Tutte hanno `@login_required`. La colonna «gate» è il controllo dentro il corpo.

| view | azione | gate | riga |
|---|---|---|---|
| `maintenance_da_fare` | consultare le manutenzioni da fare | **nessuno** (solo login); `can_plan` / `can_execute` passati al template per mostrare i bottoni | `:281`, `:367-368` |
| `maintenance_scadenze` | consultare le scadenze | **nessuno**; `can_plan` al template | `:388`, `:415` |
| `maintenance_responsabile` | quadro responsabile | **nessuno**; `can_plan` al template | `:427`, `:522` |
| `maintenance_plan_list` | elenco piani | **nessuno**; `can_manage` al template | `:532`, `:586` |
| `maintenance_plan_detail` | dettaglio piano | **nessuno**; `can_manage` al template | `:592`, `:656` |
| `maintenance_plan_form` | creare/modificare un piano | `can_manage_maintenance_plans` | `:663` |
| `maintenance_assignment_form` | creare/modificare un'applicazione | `can_manage_maintenance_plans` | `:698` |
| `maintenance_assignment_delete` | rimuovere un'applicazione (`@require_POST`) | `can_manage_maintenance_plans` | `:732` |
| `maintenance_assignment_preview` | anteprima prima scadenza (API JSON) | `can_manage_maintenance_plans` | `:846` |
| `asset_group_list` | elenco gruppi | **nessuno**; `can_manage` al template | `:900`, `:914` |
| `asset_group_form` | creare/modificare un gruppo | `can_manage_maintenance_plans` | `:921` |
| `asset_maintenance_plans` | piani di un asset | **nessuno**; `can_manage` al template | `:951`, `:990` |
| `asset_plan_customize` | personalizzare un piano su un asset | `can_manage_maintenance_plans` | `:997` |
| `maintenance_coverage` | matrice di copertura | `can_manage_maintenance_plans` | `:1391` |
| `maintenance_history_import` | importare lo storico | `can_manage_maintenance_plans` | `:1485` |
| `maintenance_history_template` | scaricare il modello di import | `can_manage_maintenance_plans` | `:1539` |
| `occurrence_create_workorder` | creare un OdL dalle occorrenze (`@require_POST`) | `can_plan_maintenance` | `:1070` |
| `workorder_occurrence_add` | aggiungere occorrenze a un OdL (`@require_POST`) | `can_plan_maintenance` | `:1106` |
| `workorder_occurrence_remove` | togliere un'occorrenza (`@require_POST`) | `can_plan_maintenance` | `:1121` |
| `workorder_distribute_day` | distribuire le giornate (`@require_POST`) | `can_plan_maintenance` | `:1141` |
| `occurrence_complete` | registrare l'esecuzione | `can_execute_maintenance` | `:1251` |
| `workorder_occurrences_complete` | registrazione massiva (`@require_POST`) | `can_execute_maintenance` | `:1176` |
| `occurrence_followup_create` | aprire un follow-up | `can_execute_maintenance` | `:1316` |
| `occurrence_attachment_download` | scaricare il rapporto di un'occorrenza | **nessuno** | `:1364` |

### 7.4 Matrice — `views.py` (rotte di manutenzione attive)

| view | azione | gate | riga |
|---|---|---|---|
| `maintenance_hub` | hub manutenzione | nessun blocco; `_is_assets_admin` usato solo per il flag `is_admin` | `:16014`, `:16029` |
| `maintenance_impostazioni` | impostazioni | nessun blocco; `is_admin` al template | `:16476`, `:16497` |
| `maintenance_suppliers` | fornitori | nessun blocco; `is_admin` al template | `:16673`, `:16684` |
| `maintenance_history` | storico | **nessuno** | `:15897` |
| `maintenance_worksheet` | scheda intervento stampabile | **nessuno** | `:16694` |
| `periodic_verification_list` | verifiche periodiche | nessun blocco; `_is_assets_admin` per `can_manage_periodic_verifications` | `:13137`, `:13139` |
| `assistance_contract_list` | contratti assistenza | nessun blocco; `_is_assets_admin` per `can_manage_contracts` | `:11850`, `:11854` |
| `il_mio_turno` | il mio turno | **nessuno** | `:14667` |
| `work_machine_maintenance_month_pdf` | PDF manutenzione mensile | **nessuno** | `:17220` |
| `maintenance_template_list` | elenco template | **`_is_assets_admin`** | `:11358` |
| `maintenance_template_create` | nuovo template | **`_is_assets_admin`** | `:11397` |
| `maintenance_template_edit` | modifica template | **`_is_assets_admin`** | `:11448` |
| `asset_maintenance_rule_override_create` | nuovo override regola asset | **`_is_assets_admin`** | `:11537` |
| `asset_maintenance_rule_override_edit` | modifica override | **`_is_assets_admin`** | `:11604` |
| `asset_maintenance_rule_override_reset` | ripristino override | **`_is_assets_admin`** | `:11673` |
| `workorder_campaign_create` | campagna di OdL | **`_is_assets_admin`** | `:14558` |
| `workorder_list` | elenco OdL | **nessuno** | `:14416` |
| `workorder_list_export` | export elenco OdL | **nessuno** | `:12788` |
| `workorder_create` | creare un OdL | **nessuno** | `:14740` |
| `workorder_detail` | dettaglio OdL | **nessuno** | `:14964` |
| `workorder_close` | **chiudere un OdL** | **nessuno** | `:15452` |
| `workorder_claim` | prendere in carico | **nessuno** | `:15368` |
| `workorder_set_state` | cambiare stato operativo (attesa/inizio) | **nessuno** | `:15409` |
| `workorder_attachment_download` | scaricare un allegato OdL | **nessuno** | `:2612` |
| `workorder_checklist_*` (6 view) | operare sulla checklist | solo `HttpResponseForbidden` se l'OdL non è aperto o il metodo non è POST — **nessun controllo di permesso** | `:15267`, `:15291`, `:15303`, `:15314`, `:15335`, `:15351` |

### 7.5 Punti dove il gate è ancora «superuser o admin legacy»

**Otto view usano `_is_assets_admin` come blocco**, cioè `is_superuser or is_legacy_admin`
senza alcuna alternativa ACL granulare — chi ha un permesso dal pannello Accessi resta
fuori:

1. `maintenance_template_list` — `views.py:11358`
2. `maintenance_template_create` — `views.py:11397`
3. `maintenance_template_edit` — `views.py:11448`
4. `asset_maintenance_rule_override_create` — `views.py:11537`
5. `asset_maintenance_rule_override_edit` — `views.py:11604`
6. `asset_maintenance_rule_override_reset` — `views.py:11673`
7. `workorder_campaign_create` — `views.py:14558`

Più tre view che usano `_is_assets_admin` **non come blocco ma come flag** passato al
template, con lo stesso limite sulla platea: `maintenance_hub` (`:16029`),
`maintenance_impostazioni` (`:16497`), `maintenance_suppliers` (`:16684`),
`periodic_verification_list` (`:13139`), `assistance_contract_list` (`:11854`).

`views_maintenance.py` non ha questo problema: usa `_is_assets_admin` solo **dentro**
`can_manage_maintenance_plans` (`:76`), che poi ammette anche `admin_assets`. Il commento
a `views_maintenance.py:69-71` dichiara la scelta.

### 7.6 Avvertenza necessaria sulla lettura della matrice

**«Nessun gate nella view» non significa «rotta non protetta».** Esiste un middleware
ACL (`core/middleware.py`) che, con `ACL_STRICT_CANONICAL=True` — **attivo in
produzione** — nega l'accesso alle rotte senza `RoutePermissionBinding`
(`core/middleware.py:158-180`). I pulsanti ACL delle superfici di manutenzione sono
dichiarati in `assets/acl_bootstrap.py:25-75`.

Quale utente arrivi effettivamente a quale rotta dipende quindi anche dai binding e
dalle concessioni **a DB**, che questo documento non ha letto: **non determinato**.
Per determinarlo servono, sui dati di produzione, `acl_fallback_report --only-unbound`,
`acl_coverage_report` e `acl_diagnose` sulle 69 rotte elencate al §7.1. Quello che la
matrice sopra stabilisce con certezza è **cosa il codice applicativo decide da sé**,
che è il livello su cui il refactoring interviene.

---

## 8. Storia dei dati: le due migrazioni di origine

Lettura di `django_app/assets/management/commands/migrate_maintenance_to_plans.py` e
`migrate_periodic_to_rules.py`. Servono a capire da dove arrivano le incoerenze che il
nuovo modello si trova in casa.

### 8.1 Le forme dati precedenti

Sono esistiti **tre** motori sovrapposti, non due:

1. **`PeriodicVerification`** (`models.py:1596`) — il più vecchio. Periodicità in
   **mesi** (`frequency_months`), con un flag `is_legacy` per marcare le voci assorbite.
2. **`MaintenanceRule`** (`models.py:1118`) + **`MaintenanceRuleAssetOverride`**
   (`models.py:1258`) + **`AssetMaintenanceRuleState`** (`models.py:2875`) — il secondo
   motore. Periodicità come **soglia**: `threshold_type` ∈ {`DAYS`, `HOURS`, `KM`,
   `CYCLES`} + `threshold_value` (`models.py:1119-1128`, `:1167-1168`). Ambito
   `CATEGORY` o `ASSETS` (`models.py:1137-1142`). L'ultima esecuzione viveva in
   `AssetMaintenanceRuleState.last_execution_date`.
3. **`AssetAdministrativeDeadline`** (`models.py:778`) + `…Completion` (`:836`) — le
   scadenze amministrative, gestite fuori dal flusso manutentivo.

Il modello attuale — `MaintenanceInterventionTemplate` (il «Piano»,
`models.py:919`) → `MaintenancePlanAssignment` (l'«Applicazione», `models.py:3311`) →
`MaintenanceOccurrence` (`models.py:3565`) → `WorkOrder` (`models.py:2155`) — è il
quarto, e i primi tre **sono ancora presenti nello schema**.

### 8.2 `migrate_periodic_to_rules.py` — da verifiche periodiche a regole

Converte `PeriodicVerification` → `MaintenanceInterventionTemplate` +
`MaintenanceRule`, poi marca `is_legacy=True` (docstring `:1-24`).

Incoerenze residue che possono avere origine qui:

- **`frequency_months × 30`** (`:39-40`, e `services/periodic_migration.py:36-37`).
  Un semestrale diventa 180 giorni, un annuale 360: una scadenza annuale migrata
  **anticipa di cinque giorni ogni anno**. Su piani migrati anni fa la deriva è
  cumulativa.
- **Piani saltati per categorie miste** (`:17-18`): se gli asset di una verifica non
  appartengono tutti alla stessa `AssetCategory`, il piano non viene migrato e la
  verifica resta `is_legacy=False`, cioè in un limbo — né vecchio motore dismesso né
  nuovo.
- Converte verso il **secondo** motore (`MaintenanceRule`), non verso il quarto: il suo
  output è a sua volta input di `migrate_maintenance_to_plans`. Una verifica periodica
  arriva al modello attuale solo dopo **due** conversioni in sequenza.

### 8.3 `migrate_maintenance_to_plans.py` — da regole al dominio attuale

Incoerenze residue che possono avere origine qui:

- **Regole a ore/km/cicli non convertite** (`:113-121`): vengono contate in
  `skipped_meter_rules` e segnalate a video, ma restano solo nel vecchio motore. Gli
  asset coperti **solo** da quelle regole non hanno oggi nessuna scadenza nel nuovo
  modello. Il commento del `MaintenanceRule.threshold_type` (`models.py:1166`) già
  dichiarava che quei threshold erano «modellati ma non ancora pienamente operativi».
- **Scadenza teorica e data di esecuzione confuse nello storico** (`:276-286`):
  l'occorrenza migrata viene creata con `due_date = state.last_execution_date` **e**
  `completed_on = state.last_execution_date`. La scadenza teorica originale è persa; per
  quelle righe `due_date` **non è** una scadenza, è un'esecuzione. Stesso schema per le
  scadenze amministrative (`:350-362`: `due_date = completion.completed_on`). Con
  ancoraggio `FIXED_CALENDAR`, che parte proprio da `previous_due`, il calcolo della
  scadenza successiva riparte da un dato che significa un'altra cosa.
- **`assignment` non valorizzato sulle occorrenze storiche** (`:276-286`): il campo non
  è passato, resta nullo. Conseguenza diretta e verificabile nel codice: chiudere una di
  quelle occorrenze **non genera la successiva** — `complete_occurrence` esce subito se
  `assignment is None` (`maintenance_domain.py:454-456`).
- **`schedule_anchor` non valorizzato** né sulle applicazioni migrate dalle regole
  (`:127-140`) né sulle occorrenze storiche: resta il default (`FROM_COMPLETION` per
  l'occorrenza, stringa vuota sull'applicazione, che eredita dal piano). L'ancoraggio
  effettivo dei piani migrati **non è mai stato scelto da nessuno**.
- **Periodicità annuale inventata per le amministrative** (`:331-342`): il vecchio
  modello non registrava la periodicità, quindi la migrazione mette `YEARS/1` con
  `auto_generate=False` e la nota «Periodicita' da confermare». È la scelta prudente
  giusta, ma lascia dietro di sé applicazioni **spente**, che non generano nulla finché
  un responsabile non le conferma. **Non determinato** quante siano ancora in quello
  stato: misurabile in produzione con un conteggio su
  `MaintenancePlanAssignment.auto_generate=False`.
- **Gruppi sintetici** (`:161-180`): ogni regola ad ambito `ASSETS` genera un
  `AssetGroup` chiamato `regola-<id>`, etichettato «<piano> — asset selezionati». Sono
  gruppi tecnici, non organizzativi, e oggi compaiono nel filtro «Gruppo» della pagina
  «Da fare» accanto ai gruppi veri.
- **Idempotenza per esistenza, non per identità** (`:122-124`, `:206-210`, `:268-272`,
  `:346-349`): il comando salta se «esiste già qualcosa di simile». Rieseguirlo dopo che
  qualcuno ha modificato a mano un'applicazione non riallinea nulla, e non lo segnala.

### 8.4 Conseguenza per il refactoring degli stati

Il dato storico non distingue tra `due_date` come *scadenza* e `due_date` come
*esecuzione* (§8.2). Qualunque nuovo modello di stati che dia significato semantico
diverso a quei due campi va progettato sapendo che **su una parte dello storico i due
significati sono già collassati** e non sono più separabili a posteriori.

---

## 9. Rischi per la Fase 1

Ordinati per gravità.

**R1 — La scadenza successiva può nascere già scaduta, e non è un caso limite.**
Dimostrato dalla sonda (§1.3): tre casi su quattro hanno prodotto una scadenza nel
passato. Non esiste alcuna guardia rispetto a oggi; l'unica esistente
(`maintenance_domain.py:470-474`) guarda alla data di esecuzione e nella sonda non è mai
entrata. Se il refactoring introduce uno stato calcolato «scaduta» più severo, o una
notifica, il volume di falsi allarmi generati da questa meccanica va misurato **prima**.
Decidere consapevolmente la regola («la prossima scadenza non può mai essere anteriore a
oggi» oppure «può, e lo dichiariamo») è un prerequisito, non un dettaglio.

**R2 — Registrare un'esecuzione con data arbitraria nel passato fa regredire il piano.**
Nessuna validazione confronta la data inserita con l'ultima esecuzione (§1.4). Una
digitazione sbagliata dell'anno riscrive la pianificazione di un asset senza che nulla
lo segnali, e `generate_occurrences` e `complete_occurrence` possono poi partire da basi
diverse. Un vincolo `completed_on >= ultima esecuzione` è a costo quasi nullo e va
valutato in Fase 1.

**R3 — Lo stato è sparso su cinque campi che non si parlano.**
Per l'OdL: `status`, `is_waiting` (+3 campi di corredo), `started_at`, `outcome`,
`assigned_to`. Il sotto-stato `operational_state` li ricompone in lettura
(`models.py:2619-2631`), ma **ogni filtro del portale scritto su `status=OPEN` continua
a vedere insieme cose molto diverse** — è esattamente la motivazione dichiarata a
`models.py:2384-2386` per non toccare `status`. Consolidare gli stati significa toccare
quei filtri: il loro censimento è lavoro di Fase 1 e non è contenuto in questo documento.

**R4 — Undici punti scrivono `WorkOrder.status`, e due aggirano `close()`.**
`_build_execution_workorder` (`views.py:2800`) assegna direttamente `DONE`, e il
`WorkOrderAdmin` (`admin.py:347`) espone `status` come campo libero. Qualunque invariante
di transizione introdotta nel modello va difesa in tutti e undici i punti, oppure quei
punti vanno fatti convergere su un unico metodo prima di introdurla.

**R5 — La transizione «non risolto» vive nella view.**
`views.py:15494-15500` converte una richiesta di chiusura in una permanenza in `OPEN`.
È una regola di dominio in un file di presentazione: spostarla nel modello è
un'occasione della Fase 1, ma finché resta lì qualunque altro percorso di chiusura (per
esempio una futura API) la salta.

**R6 — I conflitti di periodicità sono un silenzio.**
Una coppia (piano, asset) in conflitto non genera occorrenze
(`maintenance_domain.py:338-340`): l'asset semplicemente non compare da nessuna parte.
Non esiste un contatore visibile né un alert. Prima di toccare gli stati va misurato
quanti sono in produzione (`manut_audit`), altrimenti si rischia di costruire il nuovo
modello su un perimetro che ignora silenziosamente una parte del parco.

**R7 — Chiusura dell'OdL e registrazione delle occorrenze sono disaccoppiate per
scelta, ma il disaccoppiamento produce debito.**
`workorder_close` avvisa e basta (`views.py:15618-15637`). Il debito accumulato è
esattamente ciò che misura il §3, ed è **da eseguire in produzione** prima di decidere
se la Fase 1 debba rendere quel disaccoppiamento più esplicito (per esempio bloccando la
chiusura) o più automatico.

**R8 — Il perimetro dei permessi non è omogeneo fra i due file.**
`views_maintenance.py` ha gate ACL granulari e coerenti; `views.py` ha sette blocchi
ancora su «superuser o admin legacy» (§7.5) e un'ampia superficie di OdL — creazione,
dettaglio, **chiusura**, checklist — senza alcun controllo di permesso a livello di view,
affidata interamente al middleware ACL. Se la Fase 1 tocca le transizioni di stato
dell'OdL, tocca codice il cui gate applicativo non esiste: la verifica dei binding a DB
(§7.6) va fatta **prima**, non dopo.

**R9 — Lo storico migrato ha `due_date` che significa due cose diverse.**
Vedi §8.4. Più le occorrenze storiche senza `assignment`, che non generano mai la
successiva (`maintenance_domain.py:454-456`). Il refactoring degli stati va progettato
sapendo che una parte del parco è ferma per questa ragione, non per una scelta.

**R10 — L'uso reale delle superfici non è misurato, e in parte non è più misurabile.**
Nessun logging dei filtri (§5.2); nessun `created_by`/`created_at` su `WorkOrder`
(§4). Le decisioni di Fase 1 su cosa semplificare o rimuovere si prenderanno senza dati
di utilizzo, a meno di introdurre prima la misura minima proposta al §5.3 e attendere
una finestra di osservazione.

**R11 — La pagina «Da fare» tronca a 1000 righe e conta in Python.**
`views_maintenance.py:293`. Se la Fase 1 aumenta il numero di occorrenze aperte — per
esempio sbloccando i conflitti di R6 o le applicazioni spente di §8.3 — i conteggi dei
blocchi diventano silenziosamente falsi.

---

## Appendice — come rieseguire le misure

```powershell
# Punti 3, 4 e 6, sul database su cui gira il comando
python django_app\manage.py manut_audit

# Solo le query, senza toccare il DB
python django_app\manage.py manut_audit --explain

# Finestra diversa per il punto 4 / tutte le righe di dettaglio del punto 3
python django_app\manage.py manut_audit --months 24 --limit 0
```

Il comando è di sola lettura: nessun `save`, `create`, `update` o `delete`, nessun invio
mail, nessun file prodotto, output esclusivamente su stdout. Le query sono stampate
prima di essere eseguite; con `--explain` sono stampate e basta.

**Validazione tecnica eseguita** su `config.settings.dev` (SQL Server locale
`PORTALE NOVICROM` su `localhost\SQLEXPRESS`), 07-09-2026: il comando gira senza errori
in entrambe le modalità. I numeri che ha prodotto sono
**VALIDAZIONE TECNICA — DATI NON RAPPRESENTATIVI** e non compaiono in questo documento:
le sezioni 3, 4 e 6 restano da eseguire in produzione.
