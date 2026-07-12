# Design — Automazione invio email minuta incontro KICK-OFF

- **Data:** 2026-07-12
- **Modulo:** `automazioni` (+ helper minimale in `tasks`)
- **Stato:** approvato per il piano di implementazione
- **Scope:** SOLO un'automazione, gestibile da *automazioni → regole*. Niente UI, niente
  pulsanti, niente nuovi campi sul modello, niente job pianificato.

## Obiettivo

Creare **una regola di automazione** che invii ai partecipanti una email con la **minuta/verbale**
di un incontro di kickoff (`tasks.KickoffMeeting`). La regola deve comparire e restare gestibile in
*automazioni → regole* (on/off, condizioni, log), come le altre regole del portale.

Nessun altro intervento: nessun pulsante "Invia minuta", nessun campo `concluso`/`minuta_inviata_at`,
nessuna modifica ai form/template incontro.

## Perché serve del codice a supporto (non basta il designer)

Verificato sul motore: l'azione `send_email` generica prende i destinatari solo da colonne del
payload e non può chiamare `get_all_attendee_emails()` (partecipanti in M2M/testo) né comporre la
minuta ricca. Esiste però il precedente esatto: `SEND_ANOMALIE_MAIL_ACTION_BY_OP`
(`django_app/automazioni/services.py:4341`) risolve destinatari dinamici in Python e delega a un
service. Replichiamo quel pattern. Il minimo indispensabile perché la regola **funzioni davvero** ed
**appaia in regole** è quindi: una source, un trigger SQL, un'azione custom, un package seed.

## Componenti (il minimo per un'automazione funzionante)

### 1. Source `tasks_kickoff` — `django_app/automazioni/source_registry.py`
Nuova voce in `_SOURCE_REGISTRY` (`:56`): `table_name="tasks_kickoffmeeting"`, `pk_field="id"`,
operazioni insert/update, `fields` con le colonne fisiche utili (`id`, `numero`, `titolo`, `data`,
`note`, `project_id`). Serve perché la regola possa selezionare questa sorgente nel designer.

### 2. Trigger SQL — `django_app/automazioni/migrations/trg_tasks_kickoff_automation.sql`
Modellato su `trg_tasks_automation.sql`: INSERT + UPDATE su `tasks_kickoffmeeting`, scrive in
`dbo.automation_event_queue` con `payload_json` (`inserted FOR JSON PATH`) e, per l'UPDATE, il valore
precedente `old_note`. Applicato da `apply_sql_triggers` (auto-discovery `trg_*.sql`). Serve perché
un cambiamento sul record entri nella coda che il motore valuta.

### 3. Azione custom `SEND_MEETING_MINUTE`
- Valore in `AutomationActionType` (`django_app/automazioni/models.py:76`) + migrazione enum.
- Branch in `execute_action` (`services.py`) sul modello di `SEND_ANOMALIE_MAIL_ACTION_BY_OP`
  (`:4341`): legge l'id dal payload, `KickoffMeeting.objects.get(pk=...)`, compone la minuta e la
  invia a `meeting.get_all_attendee_emails()`; gestisce record mancante/errore senza rompere la coda;
  scrive `AutomationActionLog`.
- Composizione+invio in un helper minimale `django_app/tasks/minute_email.py`
  (`send_meeting_minute(meeting)`): usa `core.email_utils.send_hub_mail` con i blocchi
  `email_facts_table`/`email_item_cards`/`email_cta`; corpo = testata KICK-OFF (numero, titolo,
  data/ora, luogo) + agenda/ODG + **Verbale/Note** + problemi aperti + next steps + CTA portale.
  Se `get_all_attendee_emails()` è vuoto → non invia.

### 4. Package regola (seed) — `django_app/automazioni/packages/auXX_kickoff_minuta_incontro.automation_package.json`
Modellato su `au25_ticket_chiuso_kpi_live.automation_package.json`. Contenuto:
`source_code=tasks_kickoff`, `operation_type=update`, `trigger_scope=specific_field`,
`watched_field=note` (verbale compilato/aggiornato), azione `SEND_MEETING_MINUTE`, `cooldown_group`
per evitare invii ripetuti sullo stesso incontro. Import via `package_importer` → la regola compare
in *automazioni → regole*, dove l'utente la gestisce e può ritoccare trigger/condizioni.

> Trigger di default: **update del verbale (`note`)**. È il momento naturale "minuta pronta". Una
> volta importata, la regola è modificabile dall'utente nel designer (può cambiarlo, es. in insert o
> aggiungere condizioni), senza altro codice.

## Idempotenza / casi limite

- Doppioni: gestiti dal `cooldown_group` della regola (debounce sullo stesso record), non da campi
  sul modello.
- Nessun destinatario → l'azione non invia e logga; la coda prosegue.
- Record mancante/eccezione → catturati nell'azione, log, coda non interrotta.
- SQLite/dev: i trigger SQL non scattano → la regola è attiva su test/prod; in dev l'azione si
  verifica via test diretti.

## Test

- `automazioni`: source `tasks_kickoff` presente con i campi attesi; dispatch azione
  `SEND_MEETING_MINUTE` (payload con id valido → invia; id inesistente → non solleva); import package
  crea regola/condizioni/azione coerenti.
- `tasks`: `send_meeting_minute` invia (verifica `mail.outbox`) e salta senza destinatari.

Esecuzione: `python django_app\manage.py test django_app.automazioni django_app.tasks --settings=config.settings.test --keepdb`

## Documentazione e deploy

- **CHANGELOG.md** (obbligatorio) con i file toccati.
- **README.md**: menzione della nuova automazione nel modulo automazioni.
- Deploy test/prod: `migrate`, `apply_sql_triggers`, import del package una tantum.

## Fuori scope (esplicito)

- Nessun pulsante/UI di invio manuale, nessun "Concludi incontro".
- Nessun nuovo campo sul modello `KickoffMeeting`.
- Nessun job django-q, nessun PDF/allegato, nessun override `ScheduledMailText`.
