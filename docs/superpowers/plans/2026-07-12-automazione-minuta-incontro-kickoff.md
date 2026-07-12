# Automazione invio email minuta incontro KICK-OFF — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creare una regola di automazione, gestibile da *automazioni → regole*, che invia ai partecipanti l'email con la minuta/verbale di un incontro di kickoff (`tasks.KickoffMeeting`).

**Architecture:** Si replica il pattern esistente delle mail-action dinamiche di `anomalie`: una nuova *source* per `KickoffMeeting`, un *trigger SQL* che alimenta `automation_event_queue`, un'*azione custom* `send_meeting_minute` nell'engine che carica il record via ORM e usa `get_all_attendee_emails()` + un helper che compone la minuta, e un *package JSON* seed che rende la regola visibile e gestibile nel designer (importata come bozza).

**Tech Stack:** Django 5.2, Python 3.11+, SQL Server (trigger), `mssql-django`. Test con `manage.py test ... --settings=config.settings.test`.

## Global Constraints

- Rispondere/commit in italiano; branch corrente `feature/skill-matrix-mod187` (NON main).
- Solo l'automazione: **nessun** pulsante/UI, **nessun** nuovo campo su `KickoffMeeting`, **nessun** job django-q, nessun PDF/allegato.
- Nome tabella ORM del modello incontro: `tasks_kickoffmeeting`. PK: `id`.
- Test scoped con venv: `python django_app\manage.py test django_app.<app> --settings=config.settings.test --keepdb`. Bash è rifiutato dai permessi → usare PowerShell per i comandi.
- I trigger SQL non scattano su SQLite (dev): l'azione si verifica via test diretto su `execute_action`.
- Aggiornare CHANGELOG.md (obbligatorio) e README.md a fine lavoro.
- Numero package libero: usare `au52` (max attuale = au51).

---

### Task 1: Helper composizione+invio minuta — `tasks/minute_email.py`

**Files:**
- Create: `django_app/tasks/minute_email.py`
- Test: `django_app/tasks/tests/test_minute_email.py` (creare anche `django_app/tasks/tests/__init__.py` se manca il package di test; se esiste già `tests.py` come modulo, aggiungere invece il test lì — vedi Step 0)

**Interfaces:**
- Consumes: `core.email_utils.send_hub_mail(subject, body_text, recipients, *, body_html_fragment=...)`; `KickoffMeeting.get_all_attendee_emails() -> list[str]`; campi `numero, titolo, data, ora, luogo, ordine_del_giorno, note, problemi_aperti, next_steps, agenda_items, project`.
- Produces: `send_meeting_minute(meeting, *, sent_by=None) -> dict` con chiavi `{"sent": bool, "recipients": list[str], "reason": str}`; `build_minute_email(meeting) -> tuple[str, str, str]` = `(subject, body_text, body_html_fragment)`.

- [ ] **Step 0: Determinare la struttura test dell'app tasks**

Run: `python -c "import os; print(os.path.isdir('django_app/tasks/tests'))"`
Se stampa `True` → esiste il package `tests/`: creare `django_app/tasks/tests/test_minute_email.py`.
Se stampa `False` → verificare `django_app/tasks/tests.py`: in tal caso aggiungere la classe di test in un nuovo file `django_app/tasks/tests_minute_email.py` e assicurarsi che il test runner lo scopra (i file `test*.py` nella dir dell'app sono raccolti). Per semplicità e coerimento, preferire creare la dir package `tests/` con `__init__.py` se non esiste alcun `tests.py`.

- [ ] **Step 1: Write the failing test**

```python
# django_app/tasks/tests/test_minute_email.py
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from tasks.models import KickoffMeeting, Project
from tasks.minute_email import build_minute_email, send_meeting_minute

User = get_user_model()


class MinuteEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pm", email="pm@example.com", password="x")
        self.project = Project.objects.create(name="", created_by=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-07-15",
            titolo="Avvio commessa",
            luogo="Sala A",
            ordine_del_giorno="1. Presentazione\n2. Rischi",
            note="Riunione conclusa, tutti allineati.",
            next_steps="Inviare offerta entro venerdì.",
            partecipanti_email_extra="mario@example.com\nlucia@example.com",
        )

    def test_build_minute_email_contains_verbale_and_subject(self):
        subject, body_text, body_html = build_minute_email(self.meeting)
        self.assertIn("Minuta", subject)
        self.assertIn(str(self.meeting.project.kickoff_number), subject)
        self.assertIn("Riunione conclusa", body_html)
        self.assertIn("Inviare offerta", body_html)

    def test_send_meeting_minute_sends_to_all_attendees(self):
        result = send_meeting_minute(self.meeting)
        self.assertTrue(result["sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(
            mail.outbox[0].to, ["mario@example.com", "lucia@example.com"]
        )

    def test_send_meeting_minute_skips_without_recipients(self):
        self.meeting.partecipanti_email_extra = ""
        self.meeting.save(update_fields=["partecipanti_email_extra"])
        result = send_meeting_minute(self.meeting)
        self.assertFalse(result["sent"])
        self.assertEqual(result["reason"], "no_recipients")
        self.assertEqual(len(mail.outbox), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.tasks.tests.test_minute_email --settings=config.settings.test --keepdb`
Expected: FAIL con `ModuleNotFoundError: No module named 'tasks.minute_email'` (o `ImportError`).

- [ ] **Step 3: Write minimal implementation**

```python
# django_app/tasks/minute_email.py
from __future__ import annotations

from core.email_utils import (
    email_cta,
    email_facts_table,
    text_to_html,
)


def _fmt_data(meeting) -> str:
    parts = [meeting.data.strftime("%d/%m/%Y") if meeting.data else ""]
    if meeting.ora:
        parts.append(meeting.ora.strftime("%H:%M"))
    return " ".join(p for p in parts if p).strip()


def build_minute_email(meeting) -> tuple[str, str, str]:
    """Compone (subject, body_text, body_html_fragment) della minuta incontro."""
    kickoff = getattr(meeting.project, "kickoff_number", "") or ""
    titolo = (meeting.titolo or "").strip()
    subject = f"Minuta incontro — KICK-OFF {kickoff}"
    if titolo:
        subject += f": {titolo}"

    facts = [
        ("KICK-OFF", str(kickoff)),
        ("Incontro n.", str(meeting.numero)),
        ("Titolo", titolo or "—"),
        ("Data", _fmt_data(meeting) or "—"),
        ("Luogo", (meeting.luogo or "—").strip() or "—"),
    ]

    sections: list[tuple[str, str]] = [
        ("Ordine del giorno", meeting.ordine_del_giorno),
        ("Verbale / Note", meeting.note),
        ("Problemi aperti", meeting.problemi_aperti),
        ("Next steps", meeting.next_steps),
    ]

    html_parts = [email_facts_table(facts)]
    text_parts = [f"{k}: {v}" for k, v in facts]
    for label, value in sections:
        value = (value or "").strip()
        if not value:
            continue
        html_parts.append(f"<h3 style='margin:18px 0 6px'>{label}</h3>")
        html_parts.append(text_to_html(value))
        text_parts.append(f"\n{label}\n{value}")

    html_parts.append(
        email_cta("Apri incontro sul portale", "#", note="Accedi al portale per i dettagli.")
    )

    body_html = "".join(html_parts)
    body_text = "\n".join(text_parts)
    return subject, body_text, body_html


def send_meeting_minute(meeting, *, sent_by=None) -> dict:
    """Invia la minuta a tutti i partecipanti. Ritorna esito senza sollevare per casi previsti."""
    recipients = meeting.get_all_attendee_emails()
    if not recipients:
        return {"sent": False, "recipients": [], "reason": "no_recipients"}

    from core.email_utils import send_hub_mail

    subject, body_text, body_html = build_minute_email(meeting)
    sent_count = send_hub_mail(
        subject,
        body_text,
        recipients,
        title=f"Minuta incontro KICK-OFF {getattr(meeting.project, 'kickoff_number', '') or ''}",
        email_type="VRF - KICK-OFF",
        body_html_fragment=body_html,
        fail_silently=False,
    )
    if not sent_count:
        return {"sent": False, "recipients": recipients, "reason": "send_error"}
    return {"sent": True, "recipients": recipients, "reason": ""}
```

> Nota: verificare che `email_cta`, `email_facts_table`, `text_to_html` siano esportati da `core/email_utils.py` (lo sono a `:45/:85/:114`). La CTA usa `"#"` come URL segnaposto: la minuta non richiede un link assoluto autenticato; se serve un URL reale in futuro si aggancerà a `settings.SITE_URL`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.tasks.tests.test_minute_email --settings=config.settings.test --keepdb`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/tasks/minute_email.py django_app/tasks/tests/
git commit -m "feat(tasks): helper minuta incontro KICK-OFF (build+send email)"
```

---

### Task 2: Source `tasks_kickoff` nel registro automazioni

**Files:**
- Modify: `django_app/automazioni/source_registry.py` (aggiungere una voce a `_SOURCE_REGISTRY`, dopo il blocco `"tasks"` a `:163-211`)
- Test: `django_app/automazioni/tests/test_source_kickoff.py` (o file test coerente con la struttura esistente dell'app automazioni — verificare come al Task 1 Step 0)

**Interfaces:**
- Consumes: helper `_field(...)` (`source_registry.py:17`), `get_source_definition(code)` (`:1630`).
- Produces: chiave `"tasks_kickoff"` in `_SOURCE_REGISTRY` con `table_name="tasks_kickoffmeeting"`, `pk_field="id"`, `supported_operations=["insert","update"]`, e i field `id, numero, titolo, data, note, project_id, old_note`.

- [ ] **Step 1: Write the failing test**

```python
# django_app/automazioni/tests/test_source_kickoff.py
from django.test import SimpleTestCase

from automazioni.source_registry import get_source_definition


class KickoffSourceTests(SimpleTestCase):
    def test_kickoff_source_registered(self):
        definition = get_source_definition("tasks_kickoff")
        self.assertIsNotNone(definition)
        self.assertEqual(definition["table_name"], "tasks_kickoffmeeting")
        self.assertEqual(definition["pk_field"], "id")
        field_names = {f["name"] for f in definition["fields"]}
        self.assertTrue({"id", "numero", "note", "project_id"} <= field_names)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.automazioni.tests.test_source_kickoff --settings=config.settings.test --keepdb`
Expected: FAIL (`definition` è `None` → `assertIsNotNone` fallisce).

- [ ] **Step 3: Write minimal implementation**

Aggiungere in `_SOURCE_REGISTRY`, subito dopo la chiusura del blocco `"tasks": {...}` (riga ~211), prima di `"assets"`:

```python
    "tasks_kickoff": {
        "code": "tasks_kickoff",
        "label": "Incontri KICK-OFF",
        "source_app": "tasks",
        "table_name": "tasks_kickoffmeeting",
        "pk_field": "id",
        "supported_operations": ["insert", "update"],
        "description": (
            "Incontri di avvio commessa (KickoffMeeting). I destinatari della minuta sono "
            "risolti in Python via get_all_attendee_emails() (M2M + email extra), non da colonna."
        ),
        "fields": [
            _field(name="id", label="ID", data_type="int", description="Chiave primaria incontro.", aliases=["meeting_id"]),
            _field(name="numero", label="Numero incontro", data_type="int", description="Numero progressivo incontro nel kickoff."),
            _field(name="titolo", label="Titolo", data_type="string", description="Titolo dell'incontro.", aliases=["title"]),
            _field(name="data", label="Data", data_type="date", description="Data dell'incontro.", aliases=["date"]),
            _field(
                name="note",
                label="Verbale / Note",
                data_type="string",
                description="Testo del verbale/minuta dell'incontro.",
                aliases=["verbale", "minuta"],
            ),
            _field(
                name="old_note",
                label="Verbale precedente",
                data_type="string",
                description="Valore precedente di `note` nel payload update del trigger kickoff.",
                is_virtual=True,
                aliases=["previous_note"],
            ),
            _field(name="project_id", label="Progetto (ID)", data_type="int", description="Kickoff/progetto collegato.", aliases=["project", "kickoff_id"]),
        ],
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.automazioni.tests.test_source_kickoff --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/automazioni/source_registry.py django_app/automazioni/tests/test_source_kickoff.py
git commit -m "feat(automazioni): source tasks_kickoff (incontri KICK-OFF)"
```

---

### Task 3: Trigger SQL su `tasks_kickoffmeeting`

**Files:**
- Create: `django_app/automazioni/migrations/trg_tasks_kickoff_automation.sql`
- Test: `django_app/automazioni/tests/test_trigger_kickoff_sql.py`

**Interfaces:**
- Consumes: nessuno (file SQL applicato da `apply_sql_triggers`).
- Produces: trigger `trg_tasks_kickoff_automation` che, su INSERT/UPDATE, inserisce in `dbo.automation_event_queue` righe con `source_code='tasks_kickoff'`, `source_table='tasks_kickoffmeeting'`, e `payload_json` con (per l'update) `old_note`. Il file è auto-scoperto da `apply_sql_triggers` (pattern `trg_*.sql`).

- [ ] **Step 1: Write the failing test**

```python
# django_app/automazioni/tests/test_trigger_kickoff_sql.py
from pathlib import Path

from django.test import SimpleTestCase


class KickoffTriggerSqlTests(SimpleTestCase):
    def test_trigger_file_targets_kickoff_table(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "migrations"
            / "trg_tasks_kickoff_automation.sql"
        )
        self.assertTrue(path.exists(), "File trigger mancante")
        sql = path.read_text(encoding="utf-8")
        self.assertIn("tasks_kickoffmeeting", sql)
        self.assertIn("automation_event_queue", sql)
        self.assertIn("tasks_kickoff", sql)  # source_code
        self.assertIn("old_note", sql)       # valore precedente nell'update
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.automazioni.tests.test_trigger_kickoff_sql --settings=config.settings.test --keepdb`
Expected: FAIL (`File trigger mancante`).

- [ ] **Step 3: Write minimal implementation**

Creare `django_app/automazioni/migrations/trg_tasks_kickoff_automation.sql` (modellato su `trg_tasks_automation.sql`):

```sql
CREATE TRIGGER [dbo].[trg_tasks_kickoff_automation]
ON [dbo].[tasks_kickoffmeeting]
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF OBJECT_ID(N'dbo.automation_event_queue', N'U') IS NULL
        RETURN;

    -- INSERT (nuovo incontro creato)
    IF EXISTS (SELECT * FROM inserted) AND NOT EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code], [source_table], [source_pk], [operation_type],
            [event_code], [watched_field], [payload_json], [old_payload_json],
            [status], [created_at]
        )
        SELECT
            N'tasks_kickoff',
            N'tasks_kickoffmeeting',
            CAST(i.id AS NVARCHAR(100)),
            N'insert',
            N'tasks_kickoff_insert',
            NULL,
            (SELECT * FROM inserted i2 WHERE i2.id = i.id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            NULL,
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i;
    END

    -- UPDATE (verbale compilato/aggiornato) — solo se cambia `note`
    IF EXISTS (SELECT * FROM inserted) AND EXISTS (SELECT * FROM deleted)
    BEGIN
        INSERT INTO [dbo].[automation_event_queue] (
            [source_code], [source_table], [source_pk], [operation_type],
            [event_code], [watched_field], [payload_json], [old_payload_json],
            [status], [created_at]
        )
        SELECT
            N'tasks_kickoff',
            N'tasks_kickoffmeeting',
            CAST(i.id AS NVARCHAR(100)),
            N'update',
            N'tasks_kickoff_update',
            N'note',
            (
                SELECT i.*, d.note AS old_note
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ),
            (SELECT d.* FOR JSON PATH, WITHOUT_ARRAY_WRAPPER),
            N'pending',
            SYSUTCDATETIME()
        FROM inserted i
        JOIN deleted d ON i.id = d.id
        WHERE ISNULL(i.note, N'') <> ISNULL(d.note, N'');
    END
END
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.automazioni.tests.test_trigger_kickoff_sql --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add django_app/automazioni/migrations/trg_tasks_kickoff_automation.sql django_app/automazioni/tests/test_trigger_kickoff_sql.py
git commit -m "feat(automazioni): trigger SQL su tasks_kickoffmeeting (coda eventi)"
```

---

### Task 4: Azione custom `send_meeting_minute` nell'engine

**Files:**
- Modify: `django_app/automazioni/models.py:76-94` (aggiungere valore a `AutomationActionType`)
- Create: migrazione enum `django_app/automazioni/migrations/00XX_action_send_meeting_minute.py` (via `makemigrations automazioni`)
- Modify: `django_app/automazioni/services.py` (nuovo branch in `execute_action`, accanto a `SEND_ANOMALIE_MAIL_ACTION_BY_OP` a `:4341`)
- Test: `django_app/automazioni/tests/test_action_send_meeting_minute.py`

**Interfaces:**
- Consumes: `execute_action(action, payload, ...)` (`services.py:3716`); `_create_action_log(run_log, action, status, result_message)`; `AutomationActionLogStatus`; `source_definition` (dict con `pk_field`); `tasks.minute_email.send_meeting_minute` (Task 1).
- Produces: valore enum `SEND_MEETING_MINUTE = "send_meeting_minute"`; branch che, dato il payload con l'id incontro, invia la minuta e ritorna `{"status": ..., "result_message": ..., "action_log": ...}`.

- [ ] **Step 1: Write the failing test**

```python
# django_app/automazioni/tests/test_action_send_meeting_minute.py
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from automazioni.models import (
    AutomationAction,
    AutomationActionType,
    AutomationRule,
    AutomationRuleOperationType,
)
from automazioni.services import execute_action
from tasks.models import KickoffMeeting, Project

User = get_user_model()


class SendMeetingMinuteActionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pm", email="pm@example.com", password="x")
        self.project = Project.objects.create(name="", created_by=self.user)
        self.meeting = KickoffMeeting.objects.create(
            project=self.project,
            data="2026-07-15",
            titolo="Avvio",
            note="Verbale ok.",
            partecipanti_email_extra="a@example.com",
        )
        self.rule = AutomationRule.objects.create(
            code="au52-kickoff-minuta",
            name="Minuta incontro",
            source_code="tasks_kickoff",
            operation_type=AutomationRuleOperationType.UPDATE,
        )
        self.action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.SEND_MEETING_MINUTE,
            config_json={},
        )

    def test_action_sends_minute(self):
        result = execute_action(
            self.action,
            payload={"id": self.meeting.id, "note": "Verbale ok."},
            queue_event={"source_code": "tasks_kickoff"},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["a@example.com"])

    def test_action_missing_meeting_does_not_raise(self):
        result = execute_action(
            self.action,
            payload={"id": 999999},
            queue_event={"source_code": "tasks_kickoff"},
        )
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn(result["status"], ("error", "skipped"))
```

> Verificare i nomi esatti: `AutomationRuleOperationType` e i suoi membri (`UPDATE`) sono in `automazioni/models.py` — se il membro si chiama diversamente, adeguare l'import. `AutomationAction` richiede `order` (vedi `models.py:245-257`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.automazioni.tests.test_action_send_meeting_minute --settings=config.settings.test --keepdb`
Expected: FAIL (`AttributeError: SEND_MEETING_MINUTE` non esiste su `AutomationActionType`).

- [ ] **Step 3a: Aggiungere il valore enum**

In `django_app/automazioni/models.py`, dentro `AutomationActionType` (dopo la riga `SEND_ANOMALIE_MAIL_ACTION_BY_OP = ...` a `:88`):

```python
    SEND_MEETING_MINUTE = "send_meeting_minute", "Invia minuta incontro KICK-OFF ai partecipanti"
```

- [ ] **Step 3b: Generare la migrazione enum**

Run: `python django_app\manage.py makemigrations automazioni --settings=config.settings.dev`
Expected: crea `django_app/automazioni/migrations/00XX_...py` con `AlterField` su `action_type`.

- [ ] **Step 3c: Aggiungere il branch nell'engine**

In `django_app/automazioni/services.py`, subito prima del branch `if action.action_type == AutomationActionType.TEAMS_WEBHOOK:` (a `:4444`), inserire:

```python
        if action.action_type == AutomationActionType.SEND_MEETING_MINUTE:
            from tasks.minute_email import send_meeting_minute
            from tasks.models import KickoffMeeting

            pk_field = str((source_definition or {}).get("pk_field") or "id")
            meeting_id = payload_context.get(pk_field)
            if meeting_id is None:
                raise ValueError("send_meeting_minute: ID incontro non trovato nel payload.")

            meeting = KickoffMeeting.objects.filter(pk=meeting_id).first()
            if meeting is None:
                result_message = f"send_meeting_minute: incontro id={meeting_id} inesistente."
                action_log = _create_action_log(
                    run_log=run_log,
                    action=action,
                    status=AutomationActionLogStatus.SKIPPED,
                    result_message=result_message,
                )
                return {"status": AutomationActionLogStatus.SKIPPED, "result_message": result_message, "action_log": action_log}

            outcome = send_meeting_minute(meeting)
            if outcome["sent"]:
                result_message = (
                    f"Minuta incontro {meeting.numero} (KICK-OFF "
                    f"{getattr(meeting.project, 'kickoff_number', '')}) inviata a "
                    f"{', '.join(outcome['recipients'])}."
                )
                status = AutomationActionLogStatus.SUCCESS
            else:
                result_message = f"Minuta non inviata (motivo: {outcome['reason']})."
                status = AutomationActionLogStatus.SKIPPED

            action_log = _create_action_log(
                run_log=run_log,
                action=action,
                status=status,
                result_message=result_message,
            )
            return {"status": status, "result_message": result_message, "action_log": action_log}
```

> Il branch va inserito **dentro** il blocco `try:` di `execute_action`, allo stesso livello di indentazione degli altri `if action.action_type == ...`. Gli import locali `KickoffMeeting`/`send_meeting_minute` evitano import circolari (stesso stile del branch anomalie).

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.automazioni.tests.test_action_send_meeting_minute --settings=config.settings.test --keepdb`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```powershell
git add django_app/automazioni/models.py django_app/automazioni/migrations/ django_app/automazioni/services.py django_app/automazioni/tests/test_action_send_meeting_minute.py
git commit -m "feat(automazioni): azione send_meeting_minute (invio minuta incontro)"
```

---

### Task 5: Package seed della regola (visibile in *automazioni → regole*)

**Files:**
- Create: `django_app/automazioni/packages/au52_kickoff_minuta_incontro.automation_package.json`
- Test: `django_app/automazioni/tests/test_package_kickoff_minuta.py`

**Interfaces:**
- Consumes: `package_importer` (funzione di import package — individuare la funzione pubblica in `django_app/automazioni/package_importer.py`, es. `import_automation_package(data)` o simile, seguendo `docs/ai/AUTOMATION_PACKAGE_REFERENCE.md`).
- Produces: file JSON con `proposed_rules[0]` → `source_code="tasks_kickoff"`, `operation_type="update"`, `trigger_scope="specific_field"`, `watched_field="note"`, action `send_meeting_minute`; importato crea `AutomationRule` con `code="au52-kickoff-minuta-incontro"`.

- [ ] **Step 1: Write the failing test**

```python
# django_app/automazioni/tests/test_package_kickoff_minuta.py
import json
from pathlib import Path

from django.test import SimpleTestCase


class KickoffMinutaPackageTests(SimpleTestCase):
    def test_package_shape(self):
        path = (
            Path(__file__).resolve().parent.parent
            / "packages"
            / "au52_kickoff_minuta_incontro.automation_package.json"
        )
        self.assertTrue(path.exists(), "Package mancante")
        data = json.loads(path.read_text(encoding="utf-8"))
        rule = data["proposed_rules"][0]
        self.assertEqual(rule["source_code"], "tasks_kickoff")
        self.assertEqual(rule["operation_type"], "update")
        self.assertEqual(rule["watched_field"], "note")
        self.assertEqual(rule["actions"][0]["action_type"], "send_meeting_minute")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python django_app\manage.py test django_app.automazioni.tests.test_package_kickoff_minuta --settings=config.settings.test --keepdb`
Expected: FAIL (`Package mancante`).

- [ ] **Step 3: Write minimal implementation**

Creare `django_app/automazioni/packages/au52_kickoff_minuta_incontro.automation_package.json` (modellato su `au25_ticket_chiuso_kpi_live.automation_package.json`, importato come **bozza** così l'utente lo attiva/rifinisce nel designer):

```json
{
  "package_version": "2026.07",
  "input": {
    "flow_name": "AU52 - Minuta incontro KICK-OFF ai partecipanti"
  },
  "source_candidate": {
    "source_code": "tasks_kickoff",
    "label": "Incontri KICK-OFF"
  },
  "compatibility": {
    "compatible": true,
    "status": "ok"
  },
  "issues": [],
  "target_context": {
    "module": "automazioni",
    "source": "tasks_kickoff"
  },
  "proposed_rules": [
    {
      "code": "au52-kickoff-minuta-incontro",
      "name": "AU52 - Minuta incontro KICK-OFF ai partecipanti",
      "description": "Quando il verbale/nota (`note`) di un incontro di kickoff viene compilato o aggiornato, invia via email la minuta dell'incontro a tutti i partecipanti (utenti portale + email extra), risolti automaticamente. Importata come bozza: rivedere ed attivare dal designer; eventuale debounce/cooldown configurabile per evitare invii ripetuti su modifiche successive del verbale.",
      "source_code": "tasks_kickoff",
      "operation_type": "update",
      "trigger_scope": "specific_field",
      "watched_field": "note",
      "is_active": false,
      "is_draft": true,
      "stop_on_first_failure": false,
      "conditions": [
        {
          "field": "note",
          "operator": "changed",
          "value": "",
          "value_type": "string"
        }
      ],
      "actions": [
        {
          "action_type": "send_meeting_minute",
          "description": "Invia la minuta dell'incontro ai partecipanti"
        }
      ]
    }
  ]
}
```

> Verificare che l'operatore `"changed"` esista nel set operatori condizione (in `automazioni/models.py`/`services.py`). Se il nome esatto differisce (es. `any_change`), adeguare `operator` di conseguenza. In alternativa, poiché `trigger_scope="specific_field"` + `watched_field="note"` già limita il trigger al cambio di `note`, la condizione può essere omessa (lista `conditions` vuota).

- [ ] **Step 4: Run test to verify it passes**

Run: `python django_app\manage.py test django_app.automazioni.tests.test_package_kickoff_minuta --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: (Facoltativo) Test di import end-to-end**

Se `package_importer` espone una funzione pubblica semplice, aggiungere un test che importa il package e verifica la creazione della regola. Individuare la firma reale:

Run: `python -c "import django_app.automazioni.package_importer as m; print([n for n in dir(m) if 'import' in n.lower()])"` (adeguare il path Python al progetto).

Poi, se disponibile `import_automation_package(data, ...)`:

```python
# aggiunta in test_package_kickoff_minuta.py (TestCase, non SimpleTestCase, se tocca il DB)
# from automazioni.package_importer import import_automation_package
# from automazioni.models import AutomationRule
# def test_import_creates_rule(self):
#     import_automation_package(data)   # firma da confermare
#     self.assertTrue(AutomationRule.objects.filter(code="au52-kickoff-minuta-incontro").exists())
```

Se la firma non è banale o richiede contesto (utente/request), NON forzare: lasciare il solo test di forma (Step 1) e documentare l'import manuale nel deploy (Task 6). Non inventare una firma.

- [ ] **Step 6: Commit**

```powershell
git add django_app/automazioni/packages/au52_kickoff_minuta_incontro.automation_package.json django_app/automazioni/tests/test_package_kickoff_minuta.py
git commit -m "feat(automazioni): package regola minuta incontro KICK-OFF (AU52, bozza)"
```

---

### Task 6: Documentazione (CHANGELOG + README) e note deploy

**Files:**
- Modify: `CHANGELOG.md` (sezione `[Unreleased]`)
- Modify: `README.md` (sezione modulo `automazioni` e/o `tasks`)

**Interfaces:** nessuna (documentazione).

- [ ] **Step 1: Aggiornare CHANGELOG.md**

Sotto `## [Unreleased]`, aggiungere una voce che elenca i file toccati e la descrizione:

```markdown
### Added
- **VRF – KICK-OFF / Automazioni:** nuova automazione "AU52 – Minuta incontro KICK-OFF ai partecipanti".
  Quando il verbale (`note`) di un `KickoffMeeting` viene compilato/aggiornato, invia la minuta via
  email a tutti i partecipanti (risolti da `get_all_attendee_emails()`). Gestibile da *automazioni → regole*.
  - `django_app/tasks/minute_email.py` (nuovo): `build_minute_email`, `send_meeting_minute`.
  - `django_app/automazioni/source_registry.py`: source `tasks_kickoff`.
  - `django_app/automazioni/migrations/trg_tasks_kickoff_automation.sql` (nuovo): trigger coda eventi.
  - `django_app/automazioni/models.py` + migrazione: action type `send_meeting_minute`.
  - `django_app/automazioni/services.py`: dispatch azione `send_meeting_minute`.
  - `django_app/automazioni/packages/au52_kickoff_minuta_incontro.automation_package.json` (nuovo): regola seed (bozza).
  - Deploy test/prod: `apply_sql_triggers` + import package + `migrate`.
```

- [ ] **Step 2: Aggiornare README.md**

Nella descrizione del modulo `automazioni` (o `tasks`) menzionare l'automazione minuta incontro come capacità disponibile. Una riga nella tabella/`<details>` pertinente.

- [ ] **Step 3: Commit**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs: changelog+readme automazione minuta incontro KICK-OFF (AU52)"
```

- [ ] **Step 4: Esecuzione test complessiva delle app toccate**

Run: `python django_app\manage.py test django_app.tasks django_app.automazioni --settings=config.settings.test --keepdb`
Expected: tutti i test verdi (inclusi i nuovi). Se emergono fallimenti preesistenti non correlati, annotarli senza tentare fix fuori scope.

---

## Note di deploy (test/prod SQL Server)

1. `python django_app\manage.py migrate --settings=config.settings.<env>` (migrazione enum action_type).
2. `python django_app\manage.py apply_sql_triggers --settings=config.settings.<env>` (applica `trg_tasks_kickoff_automation.sql`).
3. Importare il package `au52_kickoff_minuta_incontro` dal designer automazioni (viene creato come **bozza**: rivedere condizioni/cooldown e **attivare**).
4. Verificare che il cluster django-q (`QCluster_PROD`) stia elaborando la coda (`run_automation_queue`).

## Self-Review (eseguito)

- **Copertura spec:** source ✓ (T2), trigger ✓ (T3), azione custom ✓ (T4), helper minuta ✓ (T1), package/seed ✓ (T5), test ✓ (per task), docs/deploy ✓ (T6). Fuori scope (UI/campi/job) esplicitamente non implementato.
- **Placeholder:** nessun TBD; ogni step ha codice/comando concreto. Punti di verifica dei nomi reali (struttura test app, membri enum operazione, operatore condizione, firma importer) sono segnalati con istruzione esplicita su come confermarli — non sono placeholder ma guardrail anti-allucinazione.
- **Coerenza tipi:** `send_meeting_minute(meeting) -> dict{sent,recipients,reason}` usato identico in T1 e T4; `build_minute_email -> (subject, body_text, body_html)` coerente; `SEND_MEETING_MINUTE`/`"send_meeting_minute"` coerente tra models/services/package.
