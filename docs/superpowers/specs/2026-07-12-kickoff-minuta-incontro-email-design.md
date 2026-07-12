# Design — VRF/KICK-OFF: invio email minuta incontro (manuale + regola visual designer)

- **Data:** 2026-07-12
- **Modulo:** `tasks` (VRF – KICK-OFF) + `automazioni`
- **Stato:** approvato per il piano di implementazione

## Obiettivo

Consentire l'invio ai partecipanti di una email con la **minuta/verbale** di un incontro di
kickoff (`tasks.KickoffMeeting`), in due modalità:

1. **Manuale** — pulsante "Invia minuta" nel dettaglio incontro (funziona anche in dev/SQLite).
2. **Automatica** — una **regola gestibile dal visual designer** delle automazioni, event-driven,
   che scatta quando l'incontro viene marcato come **concluso** (gira su SQL Server test/prod).

Oggi non esiste alcun invio della minuta: gli incontri hanno solo l'invito calendario Outlook
(`tasks/meeting_outlook.py`). Tutti i mattoni (dati minuta, destinatari, helper email) esistono già;
manca il "collante" più l'integrazione col motore automazioni.

## Contesto codice esistente (riferimenti)

- Modello incontro: `django_app/tasks/models.py:910` (`KickoffMeeting`). Campi minuta:
  `note` ("Note / Verbale", `:940`), `ordine_del_giorno`, `problemi_aperti`, `next_steps`,
  `agenda_items` (JSON) `:939-949`. Destinatari: `get_all_attendee_emails()` `:989`.
- Dettaglio/edit incontro: view `project_meeting_detail` `django_app/tasks/views.py:6299`,
  `project_meeting_edit` `:6339`; template `django_app/tasks/templates/tasks/project_meeting_detail.html`.
- Helper email portale: `django_app/core/email_utils.py` — `send_hub_mail` `:202`,
  blocchi `email_facts_table` `:85`, `email_item_cards` `:143`, `email_cta` `:114`,
  `text_to_html` `:45`. Layout base `core/templates/core/email/base_email.html`.
- Motore automazioni:
  - Source registry: `django_app/automazioni/source_registry.py:56` (`_SOURCE_REGISTRY`).
  - Trigger SQL modello: `django_app/automazioni/migrations/trg_tasks_automation.sql`,
    applicati da `apply_sql_triggers` (`django_app/automazioni/management/commands/apply_sql_triggers.py`).
  - Enum azioni: `django_app/automazioni/models.py:76` (`AutomationActionType`); dispatch
    hardcoded in `execute_action` (`django_app/automazioni/services.py:3716`).
  - **Pattern di riferimento per azione custom con destinatari dinamici:**
    `SEND_ANOMALIE_MAIL_ACTION_BY_OP` in `services.py:4341` (usa `_resolve_op_recipients`
    `:1115` e delega a `anomalie/mail_action_service.py`).
  - Seeding regole via package JSON: `django_app/automazioni/packages/*.automation_package.json`
    (es. `au25_ticket_chiuso_kpi_live.automation_package.json`); import via
    `package_importer.py`. Formato in `docs/ai/AUTOMATION_PACKAGE_REFERENCE.md`.

## Architettura

### A) Nucleo riusabile — `django_app/tasks/minute_email.py` (nuovo)

Unico punto di verità per comporre e inviare la minuta. Usato da manuale, azione automazioni e test.

- `build_minute_email(meeting) -> (subject, body_text, body_html_fragment)`
  - `subject`: `"Minuta incontro — KICK-OFF {n}: {titolo}"` (fallback se titolo vuoto).
  - Corpo: testata con fatti (KICK-OFF n., titolo, data/ora, luogo) via `email_facts_table`;
    Ordine del giorno / agenda (itera `agenda_items` se presente, altrimenti `ordine_del_giorno`);
    **Verbale / Note** (`note`); Problemi aperti; Next steps; CTA "Apri incontro sul portale".
  - Frammento HTML email-safe (verrà wrappato in `base_email.html` da `send_hub_mail`); versione
    testo semplice per `body_text`.
- `send_meeting_minute(meeting, *, sent_by=None, is_auto=False, force=False) -> dict`
  - Destinatari da `meeting.get_all_attendee_emails()`. Se vuoto → ritorna `{"sent": False,
    "reason": "no_recipients"}` e **non** imposta `minuta_inviata_at`.
  - Idempotenza: se `is_auto` e `minuta_inviata_at` già valorizzato e non `force` → skip
    (`{"sent": False, "reason": "already_sent"}`).
  - Invio con `send_hub_mail(subject, body_text, recipients, body_html_fragment=...)`.
  - Su successo: imposta `minuta_inviata_at = now`, salva (update_fields), scrive log; ritorna
    `{"sent": True, "recipients": [...]}`. Errore invio → log e ritorno `{"sent": False,
    "reason": "send_error"}` senza marcare inviata.

### B) Modello `KickoffMeeting` (+ migrazione)

Nuovi campi:

- `concluso = BooleanField(default=False)` — l'update a `True` è l'evento che innesca la regola.
- `concluso_at = DateTimeField(null=True, blank=True)`.
- `invia_minuta_auto = BooleanField(default=True)` — gate per-incontro usato come condizione della regola.
- `minuta_inviata_at = DateTimeField(null=True, blank=True)` — anti-doppioni + indicatore UI.

Nessun altro campo modificato. M2M `partecipanti_utenti` invariata.

### C) Invio manuale + conclusione incontro (funziona anche in dev/SQLite)

- View `project_meeting_send_minute(request, pk)` (POST) in `views.py`, gated come le altre view
  incontro; chiama `send_meeting_minute(meeting, sent_by=request.user, force=True)`; messaggio di
  esito (successo / nessun destinatario / errore); redirect al dettaglio.
- View `project_meeting_conclude(request, pk)` (POST): imposta `concluso=True`, `concluso_at=now`,
  salva. Su SQL Server questo `UPDATE` alimenta la coda automazioni; in dev non scatta la regola
  (comportamento coerente con tutte le automazioni).
- URL in `django_app/tasks/urls.py` (namespace `tasks:project_meeting_send_minute`,
  `tasks:project_meeting_conclude`).
- Template `project_meeting_detail.html`: pulsante "Invia minuta" (con stato "Inviata il …" se
  `minuta_inviata_at`), pulsante/badge "Concludi incontro".
- Form incontro (`forms.py` + `project_meeting_form.html`): checkbox `invia_minuta_auto`.

### D) Regola nel visual designer (event-driven, SQL Server test/prod)

1. **Source** `tasks_kickoff` in `_SOURCE_REGISTRY` (`source_registry.py`): `table_name`
   `tasks_kickoffmeeting`, `pk_field="id"`, `supported_operations` insert/update, `fields` con le
   colonne fisiche utili (`id`, `numero`, `titolo`, `data`, `concluso`, `invia_minuta_auto`,
   `project_id`, `minuta_inviata_at`).
2. **Trigger SQL** `django_app/automazioni/migrations/trg_tasks_kickoff_automation.sql` modellato su
   `trg_tasks_automation.sql`: INSERT + UPDATE su `tasks_kickoffmeeting`, `payload_json` con
   `inserted FOR JSON PATH` e, per l'UPDATE, il valore precedente `old_concluso`; scrive in
   `dbo.automation_event_queue`. Applicato da `apply_sql_triggers` (auto-discovery `trg_*.sql`).
3. **Azione custom** `SEND_MEETING_MINUTE` in `AutomationActionType` (`models.py`) + migrazione enum;
   branch in `execute_action` (`services.py`) che legge l'id dal payload,
   `KickoffMeeting.objects.get(pk=...)`, chiama `tasks.minute_email.send_meeting_minute(meeting,
   is_auto=True)`, gestisce record mancante/errore senza rompere la coda, scrive
   `AutomationActionLog`. Config opzionale in `AutomationActionForm` (override oggetto/intro; non
   necessaria per il funzionamento base).
4. **Package regola** `django_app/automazioni/packages/auXX_kickoff_minuta_incontro.automation_package.json`
   (numero progressivo libero): `source_code=tasks_kickoff`, `operation_type=update`,
   `trigger_scope=specific_field`, `watched_field=concluso`, condizioni `concluso changed_to True`
   AND `invia_minuta_auto == True`, azione `SEND_MEETING_MINUTE`. Importabile dal designer → la
   regola diventa visibile e gestibile (on/off, condizioni, log esecuzioni).

Il job django-q time-based **non** viene creato: l'auto-invio è interamente gestito dalla regola
event-driven, per evitare doppioni e mantenere un solo motore.

## Flusso dati

```
[Utente concludi incontro] --UPDATE concluso=True--> tasks_kickoffmeeting
        |                                                   |
   (manuale) pulsante "Invia minuta"                 trigger SQL --> automation_event_queue
        |                                                   |
        v                                        run_automation_queue (django-q)
 send_meeting_minute(force=True)                            |
        |                                    find_matching_rules -> regola tasks_kickoff
        |                                                   |
        |                                   execute_action SEND_MEETING_MINUTE
        |                                                   |
        +---------------------> send_meeting_minute(is_auto=True) <--+
                                          |
                            get_all_attendee_emails() + build_minute_email
                                          |
                                  send_hub_mail  --> partecipanti
                                          |
                              set minuta_inviata_at (idempotenza)
```

## Gestione errori / casi limite

- Nessun destinatario → skip, nessun invio, `minuta_inviata_at` invariato; messaggio all'utente (manuale).
- Auto già inviata (`minuta_inviata_at` valorizzato) → skip (no doppioni). Manuale con `force=True`
  può re-inviare (aggiorna timestamp).
- Minuta vuota → l'invio è comunque tecnicamente possibile; il pulsante manuale è sotto controllo
  umano. La regola auto invia solo su `concluso=True` (conclusione esplicita), quindi si presume
  minuta compilata.
- Record mancante / eccezione nell'azione automazioni → catturata, log, la coda prosegue.
- Timezone: usare `django.utils.timezone` per `concluso_at`/`minuta_inviata_at` (aware).
- SQLite/dev: i trigger SQL non scattano → auto-invio non attivo in dev; coperto da test diretti.

## Test

- App `tasks`:
  - `build_minute_email` produce oggetto e frammento con verbale/agenda/next steps.
  - `send_meeting_minute`: invia (verifica `mail.outbox`), imposta `minuta_inviata_at`;
    idempotente in modalità auto (secondo giro non invia); `force=True` re-invia;
    nessun destinatario → skip.
- App `automazioni`:
  - `source_registry` espone `tasks_kickoff` con i campi attesi.
  - dispatch azione `SEND_MEETING_MINUTE`: dato un payload con id valido invia la minuta;
    id inesistente non solleva.
  - import del package crea `AutomationRule`/`AutomationCondition`/`AutomationAction` coerenti.

Esecuzione mirata:
`python django_app\manage.py test django_app.tasks django_app.automazioni --settings=config.settings.test --keepdb`

## Documentazione e deploy

- **CHANGELOG.md** (obbligatorio): tutti i file toccati + descrizione sotto `[Unreleased]`.
- **README.md**: nuova funzionalità/URL nel catalogo modulo `tasks` e/o sezione automazioni.
- Nota AI: `django_app/ai_assistant/knowledge/07_tasks_automazioni.md`.
- Deploy: eseguire `migrate`, `apply_sql_triggers` (test/prod SQL Server), e importare il package
  regola una tantum. Documentare questi step.

## Fuori scope (YAGNI)

- PDF/allegato della minuta.
- Override testo mail via `ScheduledMailText`.
- Job django-q time-based (sostituito dalla regola event-driven).
