from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import SiteConfig, UserOnboarding
from tasks.models import Task

from .forms import AutomationActionForm
from .models import (
    ApprovalDeliveryMode,
    AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
    AutomationAction,
    AutomationActionLog,
    AutomationActionLogStatus,
    AutomationActionType,
    AutomationCondition,
    AutomationApproval,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AutomationDeliveryEndpoint,
    AutomationDeliveryEndpointType,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
    AutomationRunLogStatus,
    AutomationTableConfig,
    DashboardMetricValue,
    TeamsWebhookPreset,
)
from .services import (
    execute_action,
    execute_safe_insert,
    execute_safe_update,
    enrich_payload_for_source,
    fetch_pending_queue_events,
    fetch_pending_queue_event_snapshots,
    find_matching_rules,
    evaluate_condition,
    process_approval_decision,
    process_pending_queue_events,
    process_queue_event,
    render_template_string,
    run_rule,
    safe_get_payload_value,
)
from . import package_importer
from .package_importer import analyze_package_dict, build_example_payload, import_analyzed_package
from .source_registry import (
    AUTOMAZIONI_ACL_ACTIONS,
    build_placeholder_examples,
    get_action_mapping_fields,
    get_condition_fields,
    get_registered_sources,
    get_source_choices,
    get_source_definition,
    get_source_fields,
    get_template_fields,
    get_trigger_fields,
)

User = get_user_model()


class SourceRegistryTests(SimpleTestCase):
    def test_registered_sources_include_expected_codes(self):
        sources = get_registered_sources()
        self.assertEqual(
            [source["code"] for source in sources],
            [
                "assenze",
                "tasks",
                "assets",
                "tickets",
                "anomalie",
                "notizie",
                "diario_preposto",
                "rilevazione_incidenti",
                "rentri",
                "dpi",
                "procedure_campagne",
                "procedure_assegnazioni",
            ],
        )

    def test_get_source_definition_by_code(self):
        source = get_source_definition("tickets")
        self.assertIsNotNone(source)
        self.assertEqual(source["table_name"], "tickets_ticket")
        self.assertIsNone(get_source_definition("missing"))

    def test_get_source_choices(self):
        self.assertEqual(
            get_source_choices(),
            [
                ("assenze", "Assenze"),
                ("tasks", "Tasks (KICK-OFF)"),
                ("assets", "Assets"),
                ("tickets", "Tickets"),
                ("anomalie", "Anomalie"),
                ("notizie", "Notizie"),
                ("diario_preposto", "Diario Preposto"),
                ("rilevazione_incidenti", "Incidenti / Sicurezza"),
                ("rentri", "RENTRI / Rifiuti"),
                ("dpi", "DPI"),
                ("procedure_campagne", "Procedure - Campagne"),
                ("procedure_assegnazioni", "Procedure - Assegnazioni"),
            ],
        )

    def test_acl_action_contract_is_declared(self):
        self.assertEqual(
            AUTOMAZIONI_ACL_ACTIONS,
            ("automazioni_view", "automazioni_manage", "automazioni_logs", "automazioni_execute"),
        )

    def test_registered_sources_expose_consistent_field_metadata(self):
        for source in get_registered_sources():
            self.assertTrue(source["fields"])
            for field in source["fields"]:
                self.assertIn("db_column", field)
                self.assertIn("is_virtual", field)
                self.assertIn("aliases", field)
                self.assertIsInstance(field["aliases"], list)
                if field["is_virtual"]:
                    self.assertIsNone(field["db_column"])
                else:
                    self.assertTrue(field["db_column"])

    def test_assenze_tipo_assenza_exposes_known_values_metadata(self):
        source = get_source_definition("assenze")
        self.assertIsNotNone(source)
        tipo_field = next(field for field in source["fields"] if field["name"] == "tipo_assenza")

        self.assertEqual(tipo_field["ui_control"], "select")
        self.assertEqual(
            tipo_field["allowed_values"],
            ["Ferie", "Permesso", "Malattia", "Flessibilità", "Certifica presenza", "Altro"],
        )
        self.assertIn("Tipo assenza", tipo_field["value_source_label"])


class ApplySqlTriggersCommandTests(SimpleTestCase):
    def test_trigger_name_from_sql_supports_create_or_alter(self):
        from .management.commands import apply_sql_triggers as command_module

        sql = """
CREATE OR ALTER TRIGGER dbo.trg_assenze_automation_after_insert
ON dbo.assenze
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;
END;
GO
"""

        self.assertEqual(
            command_module._trigger_name_from_sql(sql),
            "trg_assenze_automation_after_insert",
        )

    def test_trigger_target_table_from_sql_supports_schema_and_brackets(self):
        from .management.commands import apply_sql_triggers as command_module

        self.assertEqual(
            command_module._trigger_target_table_from_sql(
                "CREATE TRIGGER [dbo].[trg_tasks_automation]\nON [dbo].[tasks_task]\nAFTER INSERT AS SELECT 1"
            ),
            "dbo.tasks_task",
        )
        self.assertEqual(
            command_module._trigger_target_table_from_sql(
                "CREATE OR ALTER TRIGGER dbo.trg_assenze_automation_after_insert\nON dbo.assenze\nAFTER INSERT AS SELECT 1"
            ),
            "dbo.assenze",
        )

    def test_apply_trigger_skips_when_target_table_is_missing(self):
        from .management.commands import apply_sql_triggers as command_module

        class _FakeSqlPath:
            name = "trg_assenze_automation_after_insert.sql"

            def read_text(self, encoding="utf-8"):
                return """
CREATE OR ALTER TRIGGER dbo.trg_assenze_automation_after_insert
ON dbo.assenze
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;
END;
GO
"""

        with patch.object(command_module, "_sql_table_exists", return_value=False):
            result = command_module.apply_trigger(_FakeSqlPath())

        self.assertEqual(result["status"], "skip")
        self.assertEqual(result["trigger"], "trg_assenze_automation_after_insert")
        self.assertEqual(result["target_table"], "dbo.assenze")
        self.assertIn("Tabella target assente", result["message"])

    def test_missing_target_sql_error_is_treated_as_skip(self):
        from .management.commands import apply_sql_triggers as command_module

        exc = Exception(
            "('42000', \"[42000] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
            "L'oggetto 'dbo.assenze' non esiste o non e valido per questa operazione. (8197)\")"
        )

        self.assertTrue(command_module._is_missing_trigger_target_error(exc))

    def test_assenze_trigger_scripts_are_self_guarded(self):
        repo_root = Path(__file__).resolve().parents[2]
        for filename in (
            "trg_assenze_automation_after_insert.sql",
            "trg_assenze_automation_after_update.sql",
        ):
            sql = (repo_root / "sql" / filename).read_text(encoding="utf-8")

            self.assertIn("IF OBJECT_ID(N'dbo.assenze', N'U') IS NULL", sql)
            self.assertIn("EXEC sys.sp_executesql N'", sql)
            self.assertIn("N''pending''", sql)

    def test_discover_trigger_files_includes_migrations_and_root_sql_dirs(self):
        from .management.commands import apply_sql_triggers as command_module

        class _FakePath:
            def __init__(self, name: str):
                self.name = name

            def resolve(self):
                return self

            def __str__(self):
                return self.name

        class _FakeDir:
            def __init__(self, files: list[str]):
                self._files = [_FakePath(name) for name in files]

            def exists(self):
                return True

            def glob(self, pattern: str):
                if pattern != "trg_*.sql":
                    raise AssertionError(f"Pattern inatteso: {pattern}")
                return list(self._files)

        migrations_dir = _FakeDir(["trg_tasks_automation.sql"])
        sql_dir = _FakeDir(["trg_assenze_automation_after_insert.sql"])

        with patch.object(command_module, "_TRIGGER_SEARCH_DIRS", (migrations_dir, sql_dir)):
            files = command_module.discover_trigger_files()

        self.assertEqual([path.name for path in files], ["trg_tasks_automation.sql", "trg_assenze_automation_after_insert.sql"])

    def test_discover_trigger_files_respects_filename_filter(self):
        from .management.commands import apply_sql_triggers as command_module

        class _FakePath:
            def __init__(self, name: str):
                self.name = name

            def resolve(self):
                return self

            def __str__(self):
                return self.name

        class _FakeDir:
            def __init__(self, files: list[str]):
                self._files = [_FakePath(name) for name in files]

            def exists(self):
                return True

            def glob(self, pattern: str):
                if pattern != "trg_*.sql":
                    raise AssertionError(f"Pattern inatteso: {pattern}")
                return list(self._files)

        migrations_dir = _FakeDir(["trg_tasks_automation.sql"])
        sql_dir = _FakeDir(["trg_assenze_automation_after_update.sql"])

        with patch.object(command_module, "_TRIGGER_SEARCH_DIRS", (migrations_dir, sql_dir)):
            files = command_module.discover_trigger_files(
                filter_files=["trg_assenze_automation_after_update.sql"],
            )

        self.assertEqual([path.name for path in files], ["trg_assenze_automation_after_update.sql"])


@override_settings(AUTOMAZIONI_TRIGGER_DB_APPLY_ENABLED=True)
class TriggerGeneratorAuditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="trigger.audit",
            email="trigger.audit@example.com",
            password="pass12345",
        )
        UserOnboarding.objects.update_or_create(
            user=self.admin,
            defaults={"completed": True, "skipped": False, "completed_at": timezone.now()},
        )

    def _source(self):
        return {
            "code": "audit_source",
            "label": "Audit Source",
            "table_name": "audit_table",
            "pk_field": "id",
            "supported_operations": ["insert"],
            "fields": [{"name": "id", "db_column": "id", "label": "ID"}],
        }

    def test_trigger_generator_preview_does_not_create_apply_audit(self):
        from core.models import AuditLog

        self.client.force_login(self.admin)
        with (
            patch("automazioni.views._get_trigger_sources", return_value=[self._source()]),
            patch("automazioni.views._generate_trigger_sql", return_value={"insert": "CREATE TRIGGER dbo.trg_audit ON dbo.audit_table AFTER INSERT AS SELECT 1"}),
            patch("automazioni.views._apply_trigger_sql") as mocked_apply,
        ):
            response = self.client.post(
                reverse("automazioni:automazioni_trigger_generator"),
                {
                    "action": "generate",
                    "source_code": "audit_source",
                    "op_insert": "on",
                    "fields": ["id"],
                },
            )

        self.assertEqual(response.status_code, 200)
        mocked_apply.assert_not_called()
        self.assertFalse(AuditLog.objects.filter(azione="apply_sql_trigger", modulo="automazioni").exists())

    def test_trigger_generator_apply_writes_sanitized_operational_audit(self):
        from core.models import AuditLog

        self.client.force_login(self.admin)
        with (
            patch("automazioni.views._get_trigger_sources", return_value=[self._source()]),
            patch("automazioni.views._generate_trigger_sql", return_value={"insert": "CREATE TRIGGER dbo.trg_audit ON dbo.audit_table AFTER INSERT AS SELECT 1"}),
            patch(
                "automazioni.views._apply_trigger_sql",
                return_value={"ok": True, "trigger_name": "trg_audit", "target_table": "dbo.audit_table"},
            ) as mocked_apply,
        ):
            response = self.client.post(
                reverse("automazioni:automazioni_trigger_generator"),
                {
                    "action": "apply",
                    "source_code": "audit_source",
                    "op_insert": "on",
                    "fields": ["id"],
                },
            )

        self.assertEqual(response.status_code, 200)
        mocked_apply.assert_called_once()
        entry = AuditLog.objects.filter(azione="apply_sql_trigger", modulo="automazioni").last()
        self.assertIsNotNone(entry)
        detail = entry.dettaglio
        self.assertEqual(detail["actor"], "trigger.audit@example.com")
        self.assertEqual(detail["mode"], "apply")
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["trigger_name"], "trg_audit")
        self.assertEqual(detail["target_table"], "dbo.audit_table")
        serialized = json.dumps(detail)
        self.assertNotIn("CREATE TRIGGER", serialized)
        self.assertNotIn("connection", serialized.lower())

    def test_trigger_generator_apply_failure_writes_error_without_sql(self):
        from core.models import AuditLog

        self.client.force_login(self.admin)
        with (
            patch("automazioni.views._get_trigger_sources", return_value=[self._source()]),
            patch("automazioni.views._generate_trigger_sql", return_value={"insert": "CREATE TRIGGER dbo.trg_audit ON dbo.audit_table AFTER INSERT AS SELECT 1"}),
            patch(
                "automazioni.views._apply_trigger_sql",
                return_value={"ok": False, "message": "permesso negato"},
            ),
        ):
            response = self.client.post(
                reverse("automazioni:automazioni_trigger_generator"),
                {
                    "action": "apply",
                    "source_code": "audit_source",
                    "op_insert": "on",
                    "fields": ["id"],
                },
            )

        self.assertEqual(response.status_code, 200)
        entry = AuditLog.objects.filter(azione="apply_sql_trigger", modulo="automazioni").last()
        self.assertIsNotNone(entry)
        self.assertFalse(entry.dettaglio["ok"])
        self.assertEqual(entry.dettaglio["error"], "permesso negato")
        self.assertNotIn("CREATE TRIGGER", json.dumps(entry.dettaglio))


class SourceRegistryFieldFilterTests(SimpleTestCase):
    def test_trigger_condition_template_and_action_fields_are_filtered(self):
        source_fields = get_source_fields("assenze")
        trigger_fields = get_trigger_fields("assenze")
        condition_fields = get_condition_fields("assenze")
        template_fields = get_template_fields("assenze")
        action_mapping_fields = get_action_mapping_fields("assenze")

        self.assertEqual(len(source_fields), 12)
        self.assertEqual([field["name"] for field in trigger_fields], [field["name"] for field in source_fields])
        self.assertEqual([field["name"] for field in condition_fields], [field["name"] for field in source_fields])
        self.assertEqual([field["name"] for field in template_fields], [field["name"] for field in source_fields])
        self.assertEqual([field["name"] for field in action_mapping_fields], [field["name"] for field in source_fields])
        self.assertIn("dipendente_nome", [field["name"] for field in template_fields])
        self.assertIn("capo_email", [field["name"] for field in template_fields])
        self.assertIn("dipendente_email", [field["name"] for field in template_fields])
        self.assertIn("salta_approvazione", [field["name"] for field in template_fields])
        capo_email_field = next(field for field in source_fields if field["name"] == "capo_email")
        self.assertTrue(capo_email_field["is_virtual"])
        self.assertIsNone(capo_email_field["db_column"])

    def test_unknown_source_returns_empty_field_sets(self):
        self.assertEqual(get_source_fields("missing"), [])
        self.assertEqual(get_trigger_fields("missing"), [])
        self.assertEqual(get_condition_fields("missing"), [])
        self.assertEqual(get_template_fields("missing"), [])
        self.assertEqual(get_action_mapping_fields("missing"), [])

    def test_placeholder_examples_are_generated_from_template_fields(self):
        task_placeholders = build_placeholder_examples("tasks")
        self.assertIn("{id}", task_placeholders)
        self.assertIn("{title}", task_placeholders)
        self.assertIn("{status}", task_placeholders)
        self.assertIn("{next_step_text}", task_placeholders)
        self.assertIn("{created_at}", task_placeholders)
        self.assertIn("{dipendente_nome}", build_placeholder_examples("assenze"))
        self.assertIn("{capo_email}", build_placeholder_examples("assenze"))
        self.assertIn("{dipendente_email}", build_placeholder_examples("assenze"))
        self.assertIn("{salta_approvazione}", build_placeholder_examples("assenze"))
        self.assertEqual(build_placeholder_examples("missing"), [])

    def test_package_import_example_payload_uses_realistic_email_and_assenze_values(self):
        payload = build_example_payload("assenze")

        self.assertEqual(payload["dipendente_nome"], "Mario Rossi")
        self.assertEqual(payload["capo_email"], "demo@example.com")
        self.assertEqual(payload["dipendente_email"], "demo@example.com")
        self.assertEqual(payload["tipo_assenza"], "Malattia")
        self.assertEqual(payload["moderation_status"], 0)
        self.assertTrue(payload["salta_approvazione"])

    def test_runtime_old_fields_are_exposed_for_tasks_and_tickets(self):
        ticket_template_fields = [field["name"] for field in get_template_fields("tickets")]
        task_template_fields = [field["name"] for field in get_template_fields("tasks")]

        self.assertIn("old_stato", ticket_template_fields)
        self.assertIn("old_assegnato_a", ticket_template_fields)
        self.assertIn("old_status", task_template_fields)
        self.assertIn("old_assigned_to_id", task_template_fields)


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    NAVIGATION_REGISTRY_ENABLED=False,
    NAVIGATION_LEGACY_FALLBACK_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
)
class AutomazioniAdminPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="automazioni-admin",
            email="automazioni@test.local",
            password="pass12345",
        )
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)
        self.legacy_admin = SimpleNamespace(id=1, ruolo_id=1, nome="Admin Automazioni")

    def _build_queue_poller_health_snapshot(self, **overrides):
        snapshot = {
            "summary_state": "healthy",
            "summary_label": "Attivo",
            "summary_message": "Task registrato e job monitorato nei tempi attesi.",
            "task_name": "Portale Hub Polling Mail",
            "task_state_label": "Pronto",
            "task_last_run_label": "15/04/2026 12:30:00",
            "task_next_run_label": "15/04/2026 12:31:00",
            "task_last_result_label": "0 (ultimo avvio ok)",
            "job_id": 12,
            "job_name": "Processo queue automazioni",
            "job_last_execution_label": "15/04/2026 12:30:00",
            "job_status_label": "Success",
            "job_trigger_type_label": "Scheduler",
            "job_message": "[run] fetched=1 done=1 error=0 rule_runs=1",
            "job_consecutive_failures": 0,
            "job_missing_alert": False,
            "job_missing_detail": "-",
            "job_stuck_alert": False,
            "job_stuck_detail": "-",
            "job_next_expected_label": "15/04/2026 12:35:00",
            "display_timezone_label": "Europe/Rome",
            "log_exists": True,
            "log_path": "C:\\Dev\\Portale Novicrom\\django_app\\logs\\automation_queue.log",
            "log_last_write_label": "15/04/2026 12:30:10",
            "log_size_label": "2.0 KB",
        }
        snapshot.update(overrides)
        return snapshot

    def _build_rule_create_post_data(self, **overrides):
        data = {
            "code": "assenze-approvate-builder",
            "name": "Assenze approvate builder",
            "description": "Regola creata da test SSR",
            "source_code": "assenze",
            "operation_type": "update",
            "trigger_scope": "specific_field",
            "watched_field": "moderation_status",
            "is_draft": "on",
            "stop_on_first_failure": "on",
            "conditions-TOTAL_FORMS": "1",
            "conditions-INITIAL_FORMS": "0",
            "conditions-MIN_NUM_FORMS": "0",
            "conditions-MAX_NUM_FORMS": "1000",
            "conditions-0-order": "1",
            "conditions-0-field_name": "moderation_status",
            "conditions-0-operator": "equals",
            "conditions-0-expected_value": "2",
            "conditions-0-value_type": "int",
            "conditions-0-compare_with_old": "",
            "conditions-0-is_enabled": "on",
            "actions-TOTAL_FORMS": "1",
            "actions-INITIAL_FORMS": "0",
            "actions-MIN_NUM_FORMS": "0",
            "actions-MAX_NUM_FORMS": "1000",
            "actions-0-order": "1",
            "actions-0-action_type": "write_log",
            "actions-0-is_enabled": "on",
            "actions-0-description": "Scrive un log operativo",
            "actions-0-write_log_message_template": "Assenza approvata #{id}",
        }
        data.update(overrides)
        return data

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_sorgenti_page_renders(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.get(reverse("admin_portale:automazioni_sorgenti"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Automazioni - Catalogo Sorgenti")
        self.assertContains(response, "Assenze")
        self.assertContains(response, "tickets_ticket")
        self.assertIn("sources", response.context)
        self.assertEqual(len(response.context["sources"]), 12)

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_contenuti_page_renders(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.get(reverse("admin_portale:automazioni_contenuti"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Automazioni - Contenuti e Colonne")
        self.assertContains(response, "Campi usabili nei trigger")
        self.assertContains(response, "{dipendente_id}")
        self.assertContains(response, "{capo_email}")
        self.assertIn("sources", response.context)
        self.assertEqual(response.context["sources"][0]["code"], "assenze")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_settings_page_renders(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.get(reverse("admin_portale:automazioni_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Impostazioni Automazioni")
        self.assertContains(response, "Polling mailbox approvazioni")
        self.assertContains(response, "Mailbox tecnica globale")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    @patch("automazioni.views.run_approval_imap_poll_now")
    def test_settings_page_can_run_imap_poll(self, mock_run_poll, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_run_poll.return_value = {
            "ok": True,
            "message": "Polling mailbox completato: 1 processate, 1 approvate, 0 rifiutate, 0 ignorate, 0 errori.",
            "output": "[run] Completato - processed=1 approved=1 rejected=0 skipped=0 error=0",
            "stats": {"processed": 1, "approved": 1, "rejected": 0, "skipped": 0, "error": 0},
        }

        response = self.client.post(
            reverse("admin_portale:automazioni_settings"),
            {"action": "run_approval_imap_poll"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Polling mailbox completato")
        mock_run_poll.assert_called_once_with()

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_settings_page_can_save_default_mailbox(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(
            reverse("admin_portale:automazioni_settings"),
            {
                "action": "save_default_approval_mailbox",
                "approval_mailbox": "approvazioni@test.local",
            },
        )

        self.assertRedirects(response, reverse("admin_portale:automazioni_settings"))
        self.assertEqual(SiteConfig.get("automazioni_approval_mailbox"), "approvazioni@test.local")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    @patch("automazioni.views.save_approval_imap_settings")
    def test_settings_page_can_save_imap_config(self, mock_save_imap, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_save_imap.return_value = (
            True,
            "Configurazione IMAP salvata in .env e aggiornata nel runtime corrente.",
        )

        response = self.client.post(
            reverse("admin_portale:automazioni_settings"),
            {
                "action": "save_approval_imap_config",
                "approval_imap_host": "imap.changed.local",
                "approval_imap_port": "995",
                "approval_imap_user": "approvazioni-changed@test.local",
                "approval_imap_password": "nuova-password",
                "approval_imap_folder": "Approvazioni",
                "approval_imap_use_ssl": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configurazione IMAP salvata")
        mock_save_imap.assert_called_once_with(
            host="imap.changed.local",
            port=995,
            user="approvazioni-changed@test.local",
            password="nuova-password",
            use_ssl=True,
            folder="Approvazioni",
        )

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_list_page_renders_and_filters(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        matching_rule = AutomationRule.objects.create(
            code="builder-list-assenze",
            name="Builder list assenze",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_active=True,
            is_draft=False,
        )
        other_rule = AutomationRule.objects.create(
            code="builder-list-tasks",
            name="Builder list tasks",
            source_code="tasks",
            operation_type=AutomationRuleOperationType.INSERT,
            trigger_scope=AutomationRuleTriggerScope.ALL_INSERTS,
            is_active=False,
            is_draft=True,
        )

        response = self.client.get(
            reverse("admin_portale:automazioni_rule_list"),
            {"source_code": "assenze", "operation_type": "update", "is_active": "true", "is_draft": "false"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Automazioni - Regole")
        self.assertContains(response, matching_rule.code)
        self.assertContains(response, reverse("admin_portale:automazioni_rule_designer", args=[matching_rule.id]))
        self.assertContains(response, reverse("admin_portale:automazioni_rule_designer_create"))
        self.assertContains(response, "Nuova regola guidata")
        self.assertContains(response, "Builder classico")
        self.assertNotContains(response, other_rule.code)

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_detail_page_shows_conditions_actions_and_run_logs(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="builder-detail-rule",
            name="Builder detail rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.SPECIFIC_FIELD,
            watched_field="moderation_status",
            is_active=True,
            is_draft=False,
        )
        AutomationCondition.objects.create(
            rule=rule,
            order=1,
            field_name="moderation_status",
            operator=AutomationConditionOperator.EQUALS,
            expected_value="2",
            value_type=AutomationConditionValueType.INT,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            description="Logga il risultato",
            config_json={"message_template": "OK {id}"},
        )
        AutomationRunLog.objects.create(
            rule=rule,
            queue_event_id=501,
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS,
            payload_json={"id": 501},
            result_message="Eseguita",
            is_test=True,
        )

        response = self.client.get(reverse("admin_portale:automazioni_rule_detail", args=[rule.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Builder detail rule")
        self.assertContains(response, "moderation_status")
        self.assertContains(response, "Logga il risultato")
        self.assertContains(response, "Eseguita")
        self.assertContains(response, reverse("admin_portale:automazioni_rule_designer", args=[rule.id]))

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_designer_page_renders_visual_blocks_and_human_summary(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="designer-rule",
            name="Designer Rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.SPECIFIC_FIELD,
            watched_field="moderation_status",
            is_active=True,
            is_draft=False,
            stop_on_first_failure=True,
        )
        AutomationCondition.objects.create(
            rule=rule,
            order=1,
            field_name="moderation_status",
            operator=AutomationConditionOperator.CHANGED_TO,
            expected_value="1",
            value_type=AutomationConditionValueType.INT,
            compare_with_old=True,
            is_enabled=True,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            description="Scrive un log",
            config_json={"message_template": "Cambio stato {id}"},
            is_enabled=True,
        )

        response = self.client.get(reverse("admin_portale:automazioni_rule_designer", args=[rule.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Designer visuale")
        self.assertContains(response, "Trigger")
        self.assertContains(response, "Condizioni")
        self.assertContains(response, "Azioni")
        self.assertContains(response, "Contenuti / Colonne disponibili")
        self.assertContains(response, "QUANDO un record di Assenze viene aggiornato")
        self.assertContains(response, "SE il trigger è")
        self.assertContains(response, "moderation_status changed_to 1")
        self.assertContains(response, "Messaggio: Cambio stato {id}")
        self.assertContains(response, "Campi suggeriti")
        self.assertContains(response, "designer-action-suggestions")
        self.assertContains(response, "Approvazione assenza")
        self.assertContains(response, "Notifica interna dipendente")
        self.assertContains(response, 'data-preset-size="sm"', html=False)
        self.assertContains(response, "Stato passa a 2")
        self.assertContains(response, "Escludi malattia")
        self.assertContains(response, "designer-condition-suggestions")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_designer_create_page_exposes_json_script_contexts_as_dicts(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.get(reverse("admin_portale:automazioni_rule_designer_create"))

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["source_fields_json"], dict)
        self.assertIsInstance(response.context["condition_suggestions_json"], dict)
        self.assertIsInstance(response.context["action_suggestions_json"], dict)
        self.assertIsInstance(response.context["diagram_action_choices"], list)
        self.assertIn("assenze", response.context["source_fields_json"])
        assenze_fields = response.context["source_fields_json"]["assenze"]["all"]
        tipo_field = next(field for field in assenze_fields if field["name"] == "tipo_assenza")
        self.assertEqual(tipo_field["ui_control"], "select")
        self.assertEqual(
            tipo_field["allowed_values"],
            ["Ferie", "Permesso", "Malattia", "Flessibilità", "Certifica presenza", "Altro"],
        )

    @patch("automazioni.views._fetch_source_field_distinct_values")
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_api_source_field_values_returns_known_and_distinct_values(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_fetch_distinct_values,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_fetch_distinct_values.return_value = {
            "queryable": True,
            "values": ["Ferie", "Malattia", "Permesso"],
            "message": "",
        }

        response = self.client.get(
            reverse(
                "admin_portale:automazioni_api_source_field_values",
                kwargs={"source_code": "assenze", "field_name": "tipo_assenza"},
            )
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["field_name"], "tipo_assenza")
        self.assertEqual(payload["ui_control"], "select")
        self.assertEqual(
            payload["allowed_values"],
            ["Ferie", "Permesso", "Malattia", "Flessibilità", "Certifica presenza", "Altro"],
        )
        self.assertEqual(payload["distinct_values"], ["Ferie", "Malattia", "Permesso"])

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_designer_page_updates_rule_via_ssr_forms(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="designer-edit-rule",
            name="Designer edit rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_active=False,
            is_draft=True,
            created_by=self.user,
            updated_by=self.user,
        )
        condition = AutomationCondition.objects.create(
            rule=rule,
            order=1,
            field_name="moderation_status",
            operator=AutomationConditionOperator.EQUALS,
            expected_value="1",
            value_type=AutomationConditionValueType.INT,
            is_enabled=True,
        )
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            description="Vecchio log",
            config_json={"message_template": "Old designer"},
            is_enabled=True,
        )
        post_data = self._build_rule_create_post_data(
            code="designer-edit-rule",
            name="Designer edit rule updated",
            description="Aggiornata da designer",
            trigger_scope="specific_field",
            watched_field="moderation_status",
            is_active="on",
            is_draft="",
            **{
                "conditions-TOTAL_FORMS": "1",
                "conditions-INITIAL_FORMS": "1",
                "conditions-0-id": str(condition.id),
                "conditions-0-order": "2",
                "conditions-0-field_name": "tipo_assenza",
                "conditions-0-operator": "not_equals",
                "conditions-0-expected_value": "Malattia",
                "conditions-0-value_type": "string",
                "conditions-0-compare_with_old": "",
                "conditions-0-is_enabled": "on",
                "actions-TOTAL_FORMS": "1",
                "actions-INITIAL_FORMS": "1",
                "actions-0-id": str(action.id),
                "actions-0-order": "3",
                "actions-0-action_type": "write_log",
                "actions-0-is_enabled": "on",
                "actions-0-description": "Nuovo log designer",
                "actions-0-write_log_message_template": "Designer #{id}",
            },
        )

        response = self.client.post(reverse("admin_portale:automazioni_rule_designer", args=[rule.id]), data=post_data)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("admin_portale:automazioni_rule_designer", args=[rule.id]))
        rule.refresh_from_db()
        condition.refresh_from_db()
        action.refresh_from_db()
        self.assertTrue(rule.is_active)
        self.assertFalse(rule.is_draft)
        self.assertEqual(rule.watched_field, "moderation_status")
        self.assertEqual(condition.field_name, "tipo_assenza")
        self.assertEqual(condition.operator, AutomationConditionOperator.NOT_EQUALS)
        self.assertEqual(action.order, 3)
        self.assertEqual(action.config_json["message_template"], "Designer #{id}")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_designer_create_assigns_missing_orders_for_new_cards(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        post_data = self._build_rule_create_post_data(
            code="designer-auto-order",
            name="Designer auto order",
            **{
                "conditions-0-order": "",
                "conditions-0-field_name": "moderation_status",
                "conditions-0-operator": "changed_to",
                "conditions-0-expected_value": "2",
                "conditions-0-value_type": "int",
                "conditions-0-compare_with_old": "on",
                "conditions-0-is_enabled": "on",
                "actions-0-order": "",
                "actions-0-action_type": "write_log",
                "actions-0-is_enabled": "on",
                "actions-0-description": "Log automatico ordine",
                "actions-0-write_log_message_template": "Ordine automatico #{id}",
            },
        )

        response = self.client.post(reverse("admin_portale:automazioni_rule_designer_create"), data=post_data)

        self.assertEqual(response.status_code, 302)
        rule = AutomationRule.objects.get(code="designer-auto-order")
        self.assertEqual(rule.conditions.count(), 1)
        self.assertEqual(rule.actions.count(), 1)
        self.assertEqual(rule.conditions.first().order, 1)
        self.assertEqual(rule.actions.first().order, 1)

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_condition_reorder_view_updates_persisted_order(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="designer-reorder-conditions",
            name="Designer reorder conditions",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_active=True,
            is_draft=False,
        )
        first = AutomationCondition.objects.create(
            rule=rule,
            order=1,
            field_name="moderation_status",
            operator=AutomationConditionOperator.EQUALS,
            expected_value="1",
            value_type=AutomationConditionValueType.INT,
            is_enabled=True,
        )
        second = AutomationCondition.objects.create(
            rule=rule,
            order=2,
            field_name="tipo_assenza",
            operator=AutomationConditionOperator.NOT_EQUALS,
            expected_value="Malattia",
            value_type=AutomationConditionValueType.STRING,
            is_enabled=True,
        )

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_condition_reorder", args=[rule.id]),
            data={"ordered_ids": [str(second.id), str(first.id)]},
        )

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.order, 1)
        self.assertEqual(first.order, 2)
        self.assertEqual(response.json()["ordered_ids"], [second.id, first.id])

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_action_reorder_view_updates_persisted_order(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="designer-reorder-actions",
            name="Designer reorder actions",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_active=True,
            is_draft=False,
        )
        first = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            description="Prima",
            config_json={"message_template": "one"},
            is_enabled=True,
        )
        second = AutomationAction.objects.create(
            rule=rule,
            order=2,
            action_type=AutomationActionType.UPDATE_DASHBOARD_METRIC,
            description="Seconda",
            config_json={"metric_code": "assenze_approvate", "operation": "increment", "value_template": "1"},
            is_enabled=True,
        )

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_action_reorder", args=[rule.id]),
            data={"ordered_ids": [str(second.id), str(first.id)]},
        )

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.order, 1)
        self.assertEqual(first.order, 2)
        self.assertEqual(response.json()["ordered_ids"], [second.id, first.id])

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_create_page_shows_source_catalog_panel(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.get(reverse("admin_portale:automazioni_rule_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contenuti / Colonne disponibili")
        self.assertContains(response, "{dipendente_id}")
        self.assertContains(response, "Campi usabili nei trigger")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_create_page_exposes_source_fields_map_as_dict_for_json_script(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.get(reverse("admin_portale:automazioni_rule_create"))

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context["source_fields_json"], dict)
        self.assertIn("assenze", response.context["source_fields_json"])
        self.assertIn("tickets", response.context["source_fields_json"])
        self.assertIn("trigger", response.context["source_fields_json"]["tickets"])
        self.assertIn("condition", response.context["source_fields_json"]["tickets"])

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_designer_create_page_renders(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.get(reverse("admin_portale:automazioni_rule_designer_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Designer visuale")
        self.assertContains(response, "Nuova regola")
        self.assertContains(response, "Contenuti / Colonne disponibili")
        self.assertContains(response, 'id="diagramActionGrid"', html=False)
        self.assertContains(response, ".diagram-modal-overlay[hidden] { display: none !important; }", html=False)
        self.assertContains(response, 'data-action-type="send_email"', html=False)
        self.assertContains(response, 'data-action-type="send_approval"', html=False)
        self.assertContains(response, 'data-action-type="branch"', html=False)
        self.assertContains(response, "diagram-action-choices")
        self.assertContains(response, 'id="flowNodeEditorPanel"', html=False)
        self.assertContains(response, 'id="flowNodeEditorMount"', html=False)
        self.assertContains(response, 'class="flow-workspace-shell"', html=False)
        self.assertContains(response, 'id="flowWorkspaceEmptyState"', html=False)
        self.assertContains(response, 'name="actions-__prefix__-branch_condition_field"', html=False)
        self.assertContains(response, 'name="actions-__prefix__-loop_check_field"', html=False)
        self.assertContains(response, 'name="actions-__prefix__-each_source_code"', html=False)
        self.assertContains(response, "Corpo loop")
        self.assertContains(response, "Se completato")
        self.assertContains(response, "Se timeout")
        self.assertContains(response, "Azioni per ogni record")
        self.assertContains(response, 'data-inline-json-target="loop_loop_actions_json"', html=False)
        self.assertContains(response, 'data-inline-json-target="loop_on_success_actions_json"', html=False)
        self.assertContains(response, 'data-inline-json-target="loop_on_timeout_actions_json"', html=False)
        self.assertContains(response, 'data-inline-json-target="each_actions_json"', html=False)
        self.assertContains(response, "Se Vero (IF)")
        self.assertContains(response, "Se Falso (ELSE)")
        self.assertContains(response, 'data-inline-json-builder', html=False)
        self.assertContains(response, 'data-inline-json-add="write_log"', html=False)
        self.assertContains(response, 'data-inline-json-add="send_email"', html=False)
        self.assertContains(response, 'data-inline-json-add="delay_schedule"', html=False)
        self.assertContains(response, 'data-inline-json-copy-other', html=False)
        self.assertContains(response, 'data-open-condition-choice-modal', html=False)
        self.assertContains(response, 'id="conditionChoiceModal"', html=False)
        self.assertContains(response, 'id="tableConfigModal"', html=False)
        self.assertContains(response, "openTableConfigModal('insert_record')", html=False)
        self.assertContains(response, "tasks.Project (tasks_project) [da abilitare]")
        self.assertContains(response, "Form richieste assenze - dropdown", html=False)

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_api_table_config_save_accepts_valid_module_table(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(
            reverse("admin_portale:automazioni_api_table_config_save"),
            data=json.dumps(
                {
                    "action_type": "update_record",
                    "table_name": "tasks_project",
                    "allowed_fields": ["name"],
                    "where_fields": ["id"],
                    "notes": "Tabella progetto abilitata da test",
                }
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(
            AutomationTableConfig.objects.filter(action_type="update_record", table_name="tasks_project").exists()
        )

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_api_table_config_save_rejects_invalid_fields_for_module_table(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(
            reverse("admin_portale:automazioni_api_table_config_save"),
            data=json.dumps(
                {
                    "action_type": "update_record",
                    "table_name": "tasks_project",
                    "allowed_fields": ["name", "campo_inesistente"],
                    "where_fields": ["id"],
                }
            ),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("allowed_fields contiene colonne non valide", response.json()["error"])

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_teams_presets_page_renders_legacy_and_flow_sections(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        TeamsWebhookPreset.objects.create(
            name="HR Legacy",
            webhook_url="https://outlook.office.com/webhook/hr",
            description="Canale HR",
            is_active=True,
        )
        AutomationDeliveryEndpoint.objects.create(
            code="teams-flow-hr",
            name="Teams Flow HR",
            endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
            endpoint_url="https://flow.example.com/hr",
            description="Flow HR",
            is_active=True,
        )

        response = self.client.get(reverse("admin_portale:automazioni_teams_presets"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Canali Teams legacy")
        self.assertContains(response, "Endpoint Teams Flow")
        self.assertContains(response, "HR Legacy")
        self.assertContains(response, "Teams Flow HR")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_teams_presets_page_warns_when_flow_endpoint_table_is_unavailable(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        TeamsWebhookPreset.objects.create(
            name="HR Legacy",
            webhook_url="https://outlook.office.com/webhook/hr",
            description="Canale HR",
            is_active=True,
        )

        with patch("automazioni.views.list_teams_flow_endpoints", return_value=([], True)):
            response = self.client.get(reverse("admin_portale:automazioni_teams_presets"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE, html=False)
        self.assertContains(response, "HR Legacy")
        self.assertContains(response, "Canali Teams legacy")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_create_page_creates_rule_with_condition_and_action(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_create"),
            data=self._build_rule_create_post_data(),
        )

        self.assertEqual(response.status_code, 302)
        rule = AutomationRule.objects.get(code="assenze-approvate-builder")
        self.assertEqual(rule.source_code, "assenze")
        self.assertEqual(rule.watched_field, "moderation_status")
        self.assertEqual(rule.conditions.count(), 1)
        self.assertEqual(rule.actions.count(), 1)
        self.assertEqual(rule.actions.first().config_json["message_template"], "Assenza approvata #{id}")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_create_page_rejects_invalid_watched_field(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_create"),
            data=self._build_rule_create_post_data(watched_field="field_missing"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AutomationRule.objects.filter(code="assenze-approvate-builder").exists())
        self.assertIn("watched_field", response.context["rule_form"].errors)

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_edit_page_updates_rule_and_formsets(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="builder-edit-rule",
            name="Builder edit rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.SPECIFIC_FIELD,
            watched_field="moderation_status",
            is_active=False,
            is_draft=True,
            created_by=self.user,
            updated_by=self.user,
        )
        condition = AutomationCondition.objects.create(
            rule=rule,
            order=1,
            field_name="moderation_status",
            operator=AutomationConditionOperator.EQUALS,
            expected_value="1",
            value_type=AutomationConditionValueType.INT,
        )
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            description="Vecchia descrizione",
            config_json={"message_template": "Old"},
        )
        post_data = self._build_rule_create_post_data(
            code="builder-edit-rule",
            name="Builder edit rule updated",
            description="Regola aggiornata",
            is_active="on",
            is_draft="",
            **{
                "conditions-TOTAL_FORMS": "1",
                "conditions-INITIAL_FORMS": "1",
                "conditions-0-id": str(condition.id),
                "conditions-0-order": "5",
                "conditions-0-field_name": "tipo_assenza",
                "conditions-0-operator": "contains",
                "conditions-0-expected_value": "Permesso",
                "conditions-0-value_type": "string",
                "conditions-0-compare_with_old": "on",
                "conditions-0-is_enabled": "on",
                "actions-TOTAL_FORMS": "1",
                "actions-INITIAL_FORMS": "1",
                "actions-0-id": str(action.id),
                "actions-0-order": "2",
                "actions-0-action_type": "write_log",
                "actions-0-is_enabled": "on",
                "actions-0-description": "Nuova descrizione",
                "actions-0-write_log_message_template": "Updated #{id}",
            },
        )

        response = self.client.post(reverse("admin_portale:automazioni_rule_edit", args=[rule.id]), data=post_data)

        self.assertEqual(response.status_code, 302)
        rule.refresh_from_db()
        condition.refresh_from_db()
        action.refresh_from_db()
        self.assertEqual(rule.name, "Builder edit rule updated")
        self.assertTrue(rule.is_active)
        self.assertFalse(rule.is_draft)
        self.assertEqual(condition.field_name, "tipo_assenza")
        self.assertEqual(condition.operator, AutomationConditionOperator.CONTAINS)
        self.assertEqual(action.order, 2)
        self.assertEqual(action.config_json["message_template"], "Updated #{id}")

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_toggle_view_activates_and_clears_draft(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="builder-toggle-rule",
            name="Builder toggle rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_active=False,
            is_draft=True,
        )

        response = self.client.post(reverse("admin_portale:automazioni_rule_toggle", args=[rule.id]))

        self.assertEqual(response.status_code, 302)
        rule.refresh_from_db()
        self.assertTrue(rule.is_active)
        self.assertFalse(rule.is_draft)

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_test_page_executes_manual_test_and_creates_run_log(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="builder-test-rule",
            name="Builder test rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_active=True,
            is_draft=False,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            config_json={"message_template": "Test #{id}"},
        )

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_test", args=[rule.id]),
            data={
                "payload_json": json.dumps({"id": 777, "moderation_status": 2}),
                "old_payload_json": json.dumps({"id": 777, "moderation_status": 1}),
                "is_test": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        run_log = AutomationRunLog.objects.filter(rule=rule, is_test=True).latest("id")
        self.assertContains(response, f"Run log #{run_log.id}")
        self.assertEqual(run_log.payload_json["id"], 777)
        self.assertTrue(run_log.is_test)

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_rule_test_page_prefills_example_payload_and_smart_builder(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="builder-test-page-smart",
            name="Builder test page smart",
            source_code="tickets",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_active=True,
            is_draft=False,
        )

        response = self.client.get(reverse("admin_portale:automazioni_rule_test", args=[rule.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["enable_smart_field_panel"])
        self.assertIn("all", response.context["source_fields_json"]["tickets"])
        self.assertContains(response, "Composer guidato del payload")
        self.assertContains(response, 'data-json-builder="payload_json"', html=False)
        self.assertContains(response, "Ticket di esempio")

    @patch("automazioni.views.count_queue_by_status")
    @patch("automazioni.views.list_queue_events")
    @patch("automazioni.views._build_queue_poller_health_snapshot")
    @patch("automazioni.views._queue_table_exists", return_value=True)
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_list_page_renders_with_filters(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        _mock_queue_table_exists,
        mock_build_queue_poller_health_snapshot,
        mock_list_queue_events,
        mock_count_queue_by_status,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_build_queue_poller_health_snapshot.return_value = self._build_queue_poller_health_snapshot()
        rule = AutomationRule.objects.create(
            code="queue-list-rule",
            name="Queue list rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_draft=False,
        )
        AutomationRunLog.objects.create(
            rule=rule,
            queue_event_id=101,
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS,
            payload_json={"id": 101},
            result_message="done",
        )
        mock_list_queue_events.return_value = [
            {
                "id": 101,
                "source_code": "assenze",
                "source_table": "assenze",
                "source_pk": "101",
                "operation_type": "UPDATE",
                "event_code": "assenze_update",
                "status": "error",
                "retry_count": 2,
                "error_message": "retry failed",
                "created_at": timezone.now(),
                "picked_at": timezone.now(),
                "processed_at": timezone.now(),
            }
        ]
        mock_count_queue_by_status.return_value = {"pending": 2, "processing": 1, "done": 3, "error": 1}

        response = self.client.get(
            reverse("admin_portale:automazioni_queue_list"),
            {"status": "error", "source_code": "assenze", "operation_type": "update"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Automazioni - Queue Operativa")
        self.assertContains(response, "Poller automatico queue")
        self.assertContains(response, "Portale Hub Polling Mail")
        self.assertContains(response, "#101")
        self.assertContains(response, "retry failed")
        self.assertContains(response, "1 log")
        mock_list_queue_events.assert_called_once_with(
            status="error",
            source_code="assenze",
            operation_type="update",
            limit=200,
        )
        mock_count_queue_by_status.assert_called_once_with(source_code="assenze", operation_type="update")

    @patch("automazioni.views.count_queue_by_status")
    @patch("automazioni.views.list_queue_events")
    @patch("automazioni.views._build_queue_poller_health_snapshot")
    @patch("automazioni.views._queue_table_exists", return_value=True)
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_list_page_shows_stop_and_delete_for_pending_events_without_logs(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        _mock_queue_table_exists,
        mock_build_queue_poller_health_snapshot,
        mock_list_queue_events,
        mock_count_queue_by_status,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_build_queue_poller_health_snapshot.return_value = self._build_queue_poller_health_snapshot()
        mock_list_queue_events.return_value = [
            {
                "id": 102,
                "source_code": "assenze",
                "source_table": "assenze",
                "source_pk": "102",
                "operation_type": "UPDATE",
                "event_code": "assenze_update",
                "status": "pending",
                "retry_count": 0,
                "error_message": "",
                "created_at": timezone.now(),
                "picked_at": None,
                "processed_at": None,
            }
        ]
        mock_count_queue_by_status.return_value = {"pending": 1, "processing": 0, "done": 0, "error": 0}

        response = self.client.get(reverse("admin_portale:automazioni_queue_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin_portale:automazioni_queue_stop", args=[102]))
        self.assertContains(response, reverse("admin_portale:automazioni_queue_delete", args=[102]))

    @patch("automazioni.views.get_queue_event_detail")
    @patch("automazioni.views._build_queue_poller_health_snapshot")
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_detail_page_renders_payload_and_linked_logs(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_build_queue_poller_health_snapshot,
        mock_get_queue_event_detail,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_build_queue_poller_health_snapshot.return_value = self._build_queue_poller_health_snapshot(
            summary_label="In ritardo",
            summary_state="warning",
        )
        rule = AutomationRule.objects.create(
            code="queue-detail-rule",
            name="Queue detail rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_draft=False,
        )
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            config_json={"message_template": "Queue {id}"},
        )
        run_log = AutomationRunLog.objects.create(
            rule=rule,
            queue_event_id=77,
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS,
            payload_json={"id": 77, "moderation_status": 2},
            old_payload_json={"id": 77, "moderation_status": 1},
            result_message="Run OK",
        )
        AutomationActionLog.objects.create(
            run_log=run_log,
            action=action,
            status=AutomationActionLogStatus.SUCCESS,
            result_message="Action OK",
        )
        mock_get_queue_event_detail.return_value = {
            "id": 77,
            "source_code": "assenze",
            "source_table": "assenze",
            "source_pk": "77",
            "operation_type": "UPDATE",
            "event_code": "assenze_update",
            "watched_field": None,
            "payload_json": '{"id": 77, "moderation_status": 2}',
            "old_payload_json": '{"id": 77, "moderation_status": 1}',
            "status": "error",
            "retry_count": 1,
            "error_message": "runtime error",
            "created_at": timezone.now(),
            "picked_at": timezone.now(),
            "processed_at": timezone.now(),
        }

        response = self.client.get(reverse("admin_portale:automazioni_queue_detail", args=[77]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Automazioni - Dettaglio Queue")
        self.assertContains(response, "Portale Hub Polling Mail")
        self.assertContains(response, "In ritardo")
        self.assertContains(response, "moderation_status")
        self.assertContains(response, "Run OK")
        self.assertContains(response, "Action OK")
        self.assertContains(response, "runtime error")

    @patch("automazioni.views.get_queue_event_detail")
    @patch("automazioni.views._build_queue_poller_health_snapshot")
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_detail_page_shows_stop_and_delete_for_pending_event_without_logs(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_build_queue_poller_health_snapshot,
        mock_get_queue_event_detail,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_build_queue_poller_health_snapshot.return_value = self._build_queue_poller_health_snapshot()
        mock_get_queue_event_detail.return_value = {
            "id": 78,
            "source_code": "assenze",
            "source_table": "assenze",
            "source_pk": "78",
            "operation_type": "UPDATE",
            "event_code": "assenze_update",
            "watched_field": None,
            "payload_json": '{"id": 78}',
            "old_payload_json": "{}",
            "status": "pending",
            "retry_count": 0,
            "error_message": "",
            "created_at": timezone.now(),
            "picked_at": None,
            "processed_at": None,
        }

        response = self.client.get(reverse("admin_portale:automazioni_queue_detail", args=[78]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin_portale:automazioni_queue_stop", args=[78]))
        self.assertContains(response, reverse("admin_portale:automazioni_queue_delete", args=[78]))

    @patch("automazioni.views.reset_queue_event_to_pending", return_value=True)
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_reset_view_resets_error_event(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_reset_queue_event_to_pending,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(reverse("admin_portale:automazioni_queue_reset", args=[88]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_queue_detail", args=[88]))
        mock_reset_queue_event_to_pending.assert_called_once_with(88)

    @patch("automazioni.views.reset_queue_event_to_pending", return_value=False)
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_reset_view_handles_incompatible_status(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_reset_queue_event_to_pending,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(reverse("admin_portale:automazioni_queue_reset", args=[89]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_queue_detail", args=[89]))
        mock_reset_queue_event_to_pending.assert_called_once_with(89)

    @patch("automazioni.views.process_single_queue_event_by_id")
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_retry_view_runs_single_event(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_process_single_queue_event_by_id,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_process_single_queue_event_by_id.return_value = {
            "queue_id": 90,
            "status": "done",
            "rule_runs": 2,
            "message": "",
        }

        response = self.client.post(reverse("admin_portale:automazioni_queue_retry", args=[90]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_queue_detail", args=[90]))
        mock_process_single_queue_event_by_id.assert_called_once_with(90)

    @patch("automazioni.views.process_single_queue_event_by_id")
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_retry_view_handles_worker_error(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_process_single_queue_event_by_id,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
        mock_process_single_queue_event_by_id.return_value = {
            "queue_id": 91,
            "status": "error",
            "rule_runs": 0,
            "message": "payload_json non contiene JSON valido.",
        }

        response = self.client.post(reverse("admin_portale:automazioni_queue_retry", args=[91]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_queue_detail", args=[91]))
        mock_process_single_queue_event_by_id.assert_called_once_with(91)

    @patch("automazioni.views.log_action")
    @patch("automazioni.views.stop_queue_event", return_value=True)
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_stop_view_stops_pending_event(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_stop_queue_event,
        mock_log_action,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(reverse("admin_portale:automazioni_queue_stop", args=[92]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_queue_detail", args=[92]))
        mock_stop_queue_event.assert_called_once_with(92)
        mock_log_action.assert_called_once()

    @patch("automazioni.views.log_action")
    @patch("automazioni.views.stop_queue_event", return_value=False)
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_stop_view_handles_incompatible_status(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_stop_queue_event,
        mock_log_action,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(reverse("admin_portale:automazioni_queue_stop", args=[93]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_queue_detail", args=[93]))
        mock_stop_queue_event.assert_called_once_with(93)
        mock_log_action.assert_not_called()

    @patch("automazioni.views.log_action")
    @patch("automazioni.views.delete_queue_event", return_value=True)
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_delete_view_removes_pending_event_without_logs(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_delete_queue_event,
        mock_log_action,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(reverse("admin_portale:automazioni_queue_delete", args=[94]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_queue_list"))
        mock_delete_queue_event.assert_called_once_with(94)
        mock_log_action.assert_called_once()

    @patch("automazioni.views.log_action")
    @patch("automazioni.views.delete_queue_event", return_value=False)
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_delete_view_blocks_events_with_logs_or_invalid_status(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_delete_queue_event,
        mock_log_action,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.post(reverse("admin_portale:automazioni_queue_delete", args=[95]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_queue_list"))
        mock_delete_queue_event.assert_called_once_with(95)
        mock_log_action.assert_not_called()

    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_run_log_list_page_filters_results(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin
        matching_rule = AutomationRule.objects.create(
            code="run-log-filter-rule",
            name="Run log filter rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_draft=False,
        )
        other_rule = AutomationRule.objects.create(
            code="run-log-other-rule",
            name="Run log other rule",
            source_code="tasks",
            operation_type=AutomationRuleOperationType.INSERT,
            trigger_scope=AutomationRuleTriggerScope.ALL_INSERTS,
            is_draft=False,
        )
        matching_run = AutomationRunLog.objects.create(
            rule=matching_rule,
            queue_event_id=201,
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS,
            payload_json={"id": 201},
            is_test=False,
            result_message="matching",
        )
        other_run = AutomationRunLog.objects.create(
            rule=other_rule,
            queue_event_id=202,
            source_code="tasks",
            operation_type=AutomationRuleOperationType.INSERT,
            status=AutomationRunLogStatus.ERROR,
            payload_json={"id": 202},
            is_test=True,
            result_message="other",
        )

        response = self.client.get(
            reverse("admin_portale:automazioni_run_log_list"),
            {
                "status": "success",
                "source_code": "assenze",
                "is_test": "false",
                "rule": str(matching_rule.id),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Automazioni - Run Log")
        self.assertContains(response, f"#{matching_run.id}")
        self.assertNotContains(response, reverse("admin_portale:automazioni_run_log_detail", args=[other_run.id]))

    @patch("automazioni.views.get_queue_event_detail")
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_run_log_detail_page_shows_payload_and_action_logs(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_get_queue_event_detail,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
        rule = AutomationRule.objects.create(
            code="run-log-detail-rule",
            name="Run log detail rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_draft=False,
        )
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            config_json={"message_template": "Run {id}"},
        )
        run_log = AutomationRunLog.objects.create(
            rule=rule,
            queue_event_id=301,
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.ERROR,
            payload_json={"id": 301, "tipo_assenza": "Permesso"},
            old_payload_json={"id": 301, "tipo_assenza": "Bozza"},
            result_message="Errore action",
            error_trace="Trace line 1",
        )
        AutomationActionLog.objects.create(
            run_log=run_log,
            action=action,
            status=AutomationActionLogStatus.ERROR,
            result_message="Action exploded",
            error_trace="Trace action",
        )
        mock_get_queue_event_detail.return_value = {
            "id": 301,
            "status": "error",
            "source_code": "assenze",
        }

        response = self.client.get(reverse("admin_portale:automazioni_run_log_detail", args=[run_log.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Automazioni - Dettaglio Run Log")
        self.assertContains(response, "tipo_assenza")
        self.assertContains(response, "Action exploded")
        self.assertContains(response, "Trace line 1")


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    NAVIGATION_REGISTRY_ENABLED=False,
    NAVIGATION_LEGACY_FALLBACK_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
)
class AutomationPackageImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="package-import-admin",
            email="package-import@test.local",
            password="pass12345",
        )
        UserOnboarding.objects.update_or_create(
            user=self.user,
            defaults={
                "completed": True,
                "skipped": False,
                "completed_at": timezone.now(),
            },
        )
        self.client.force_login(self.user)
        self.legacy_admin = SimpleNamespace(id=7, ruolo_id=1, nome="Admin Import Package")
        self.get_legacy_user_patcher = patch("admin_portale.decorators.get_legacy_user", return_value=self.legacy_admin)
        self.is_legacy_admin_patcher = patch("admin_portale.decorators.is_legacy_admin", return_value=True)
        self.get_legacy_user_patcher.start()
        self.is_legacy_admin_patcher.start()
        self.addCleanup(self.get_legacy_user_patcher.stop)
        self.addCleanup(self.is_legacy_admin_patcher.stop)

    def _base_package(self, *, rules=None, mapping=None):
        return {
            "package_version": "2026.03",
            "input": {"flow_name": "Task Import Flow"},
            "source_candidate": {"source_code": "tasks", "label": "Tasks"},
            "compatibility": {"compatible": True, "status": "ok"},
            "issues": [],
            "target_context": {"module": "automazioni", "source": "tasks"},
            "approved_field_mapping": mapping
            or {
                "Task ID": "id",
                "Task Title": "title",
                "Task Status": "status",
                "Assigned To": "assigned_to_id",
                "Project": "project_id",
                "Due Date": "due_date",
            },
            "proposed_rules": rules
            or [
                {
                    "code": "pa-task-log",
                    "name": "Task log importata",
                    "description": "Regola da package esterno",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "Task Status",
                    "is_active": False,
                    "is_draft": True,
                    "stop_on_first_failure": True,
                    "conditions": [
                        {
                            "field": "Task Status",
                            "operator": "equals",
                            "value": "DONE",
                            "value_type": "string",
                        }
                    ],
                    "actions": [
                        {
                            "action_type": "write_log",
                            "description": "Scrive log",
                            "message_template": "Task {title} -> {status}",
                        }
                    ],
                }
            ],
        }

    def _upload_package(self, package, *, filename="tasks.automation_package.json", follow=False):
        content = json.dumps(package).encode("utf-8")
        upload = SimpleUploadedFile(filename, content, content_type="application/json")
        return self.client.post(
            reverse("admin_portale:automazioni_rule_import_package"),
            {"action": "analyze", "package_file": upload},
            follow=follow,
        )

    def _analyze_package(self, package):
        response = self._upload_package(package)
        self.assertEqual(response.status_code, 302)
        session_state = self.client.session.get("automazioni_package_import_state")
        self.assertIsNotNone(session_state)
        return session_state["analysis"]

    def _run_dry_run(self, *, sample_mode="json", payload=None, old_payload=None, record_id=""):
        return self.client.post(
            reverse("admin_portale:automazioni_rule_import_package"),
            {
                "action": "dry_run",
                "sample_mode": sample_mode,
                "payload_json": json.dumps(payload or {}),
                "old_payload_json": json.dumps(old_payload) if old_payload is not None else "",
                "source_record_id": str(record_id or ""),
            },
            follow=True,
        )

    def _power_automate_converter_record(self):
        package = self._base_package()
        package["issues"] = [
            {
                "code": "approval-branch-manual-review",
                "severity": "medium",
                "title": "Branch approval da rifinire",
                "detail": "Il flow usa approval convertita in send_approval con qualche step rimasto fuori dai branch.",
                "remediation": "Rifinisci i branch nel designer dopo l'import.",
            }
        ]
        package["approval_conversion"] = {
            "detected": True,
            "strategy": "send_approval",
            "template_code": "tpl-approval-hybrid",
            "template_delivery_mode": "hybrid",
            "approver_template": "{capo_email}",
            "subject_template": "Approvazione richiesta #{id}",
            "message_template": "Body approval {id}",
            "approved_branch_supported_count": 1,
            "rejected_branch_supported_count": 1,
            "unsupported_branch_actions": [{"name": "Until_1", "type": "Until", "parent": ""}],
        }
        return {
            "record_id": "pa-demo-001",
            "created_at": "2026-04-14T10:00:00+00:00",
            "target_context": {},
            "remediations_applied": [],
            "normalized": {
                "diagram": {
                    "width": 820,
                    "height": 360,
                    "lanes": [
                        {"x": 24, "y": 24, "width": 772, "height": 300, "fill": "#fffdf8", "stroke": "#d6d3d1", "label": "Main"},
                    ],
                    "edges": [
                        {"x1": 180, "y1": 110, "label_x": 280, "y2": 110, "x2": 380, "label_y": 110, "label": ""},
                    ],
                    "nodes": [
                        {
                            "x": 56,
                            "y": 72,
                            "width": 220,
                            "height": 76,
                            "fill": "#eff6ff",
                            "stroke": "#2563eb",
                            "icon": "TRG",
                            "lines": ["Trigger", "When an item changes"],
                            "issue_badge": "",
                        },
                        {
                            "x": 360,
                            "y": 72,
                            "width": 260,
                            "height": 76,
                            "fill": "#fff7ed",
                            "stroke": "#f97316",
                            "icon": "ACT",
                            "lines": ["Create approval", "Delegare al portale"],
                            "issue_badge": "ISSUE",
                        },
                    ],
                },
            },
            "package": package,
        }

    def _power_automate_converter_analysis(self):
        return {
            "package_hash": "pa-hash-001",
            "filename": "assenze-approval.automation_package.json",
            "flow_name": "Assenze Approval Flow",
            "package_version": "1.0",
            "source_code": "tasks",
            "source_candidate": {"source_code": "tasks", "label": "Tasks"},
            "source_supported": True,
            "compatibility_lines": ["status: partial"],
            "compatibility_pretty": '{"status":"partial"}',
            "issues_lines": ["approval-delegated-to-portal"],
            "issues_pretty": '[{"code":"approval-delegated-to-portal"}]',
            "target_context_pretty": "",
            "target_context": {},
            "mapping_source": "runtime_catalog",
            "mapping_rows": [
                {"source_field": "Task Status", "target_field": "status", "status_label": "approvato"},
            ],
            "status": "partial",
            "status_label": "import parziale",
            "warnings": ["Una regola richiede remediation."],
            "errors": [],
            "rules": [
                {
                    "name": "Task log importata",
                    "source_rule_code": "pa-task-log",
                    "portal_code": "pa-task-log",
                    "description": "Regola proposta dal converter",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "conditions": [{"field_name": "status", "operator": "equals", "expected_value": "DONE"}],
                    "actions": [{"action_type": "write_log", "description": "Scrive log"}],
                    "errors": [],
                    "warnings": [],
                    "is_importable": True,
                }
            ],
            "rule_count": 1,
            "importable_rule_count": 1,
            "skipped_rule_count": 0,
        }

    def test_upload_valid_package_shows_preview(self):
        response = self._upload_package(self._base_package(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Importa Package")
        self.assertContains(response, "Task Import Flow")
        self.assertContains(response, "pronto all&#x27;import", html=False)
        self.assertContains(response, "Task log importata")

    def test_power_automate_converter_page_renders(self):
        response = self.client.get(reverse("admin_portale:automazioni_rule_power_automate_convert"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Converti Power Automate")
        self.assertContains(response, "Analizza flow")
        self.assertContains(response, "Template approvazione")

    @patch("automazioni.views.analyze_package_dict")
    @patch("automazioni.views.analyze_power_automate_flow_upload")
    def test_power_automate_converter_analyze_flow_stores_state(
        self,
        mock_analyze_flow_upload,
        mock_analyze_package_dict,
    ):
        from .models import ApprovalEmailTemplate

        ApprovalEmailTemplate.objects.create(
            code="tpl-approval-hybrid",
            name="Template Approval Hybrid",
            delivery_mode="hybrid",
            subject_template="Approval {id}",
        )
        mock_analyze_flow_upload.return_value = self._power_automate_converter_record()
        mock_analyze_package_dict.return_value = self._power_automate_converter_analysis()
        upload = SimpleUploadedFile("sample.zip", b"PK\x03\x04demo", content_type="application/zip")

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_power_automate_convert"),
            {
                "action": "analyze",
                "flow_file": upload,
                "target_table": "",
                "approval_email_template_code": "tpl-approval-hybrid",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Diagramma del Flusso Power Automate")
        self.assertContains(response, "Apri import guidato")
        session_state = self.client.session.get("automazioni_power_automate_converter_state")
        self.assertIsNotNone(session_state)
        self.assertEqual(session_state["analysis"]["flow_name"], "Assenze Approval Flow")
        self.assertEqual(session_state["selected_approval_template_code"], "tpl-approval-hybrid")
        mock_analyze_flow_upload.assert_called_once()
        self.assertEqual(
            mock_analyze_flow_upload.call_args.kwargs["approval_template"]["code"],
            "tpl-approval-hybrid",
        )

    def test_power_automate_converter_handoff_import_reuses_package_import_workflow(self):
        session = self.client.session
        session["automazioni_power_automate_converter_state"] = {
            "record": self._power_automate_converter_record(),
            "analysis": self._power_automate_converter_analysis(),
            "selected_target_table": "",
            "selected_approval_template_code": "tpl-approval-hybrid",
        }
        session.save()

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_power_automate_convert"),
            {"action": "handoff_import"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_portale:automazioni_rule_import_package"))
        package_state = self.client.session.get("automazioni_package_import_state")
        self.assertIsNotNone(package_state)
        self.assertEqual(package_state["analysis"]["flow_name"], "Assenze Approval Flow")

    def test_power_automate_converter_open_designer_creates_draft_rule(self):
        session = self.client.session
        session["automazioni_power_automate_converter_state"] = {
            "record": self._power_automate_converter_record(),
            "analysis": self._power_automate_converter_analysis(),
            "selected_target_table": "",
            "selected_approval_template_code": "tpl-approval-hybrid",
        }
        session.save()

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_power_automate_convert"),
            {"action": "open_designer", "rule_index": "1"},
        )

        created_rule = AutomationRule.objects.get(code="pa-task-log")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("admin_portale:automazioni_rule_designer", args=[created_rule.id]),
        )
        self.assertTrue(created_rule.is_draft)
        self.assertFalse(created_rule.is_active)
        self.assertEqual(created_rule.import_flow_name, "Assenze Approval Flow")
        self.assertEqual(created_rule.conditions.count(), 1)
        self.assertEqual(created_rule.actions.count(), 1)

    def test_invalid_package_is_rejected(self):
        response = self._upload_package(
            {
                "package_version": "2026.03",
                "source_candidate": {"source_code": "tasks"},
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Il package non contiene regole proposte")
        self.assertIsNone(self.client.session.get("automazioni_package_import_state"))

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_dry_run_has_no_side_effects(self, mock_email_class):
        task = Task.objects.create(
            title="Task dry run",
            status="DONE",
            priority="MEDIUM",
            created_by=self.user,
            assigned_to=self.user,
        )
        package = self._base_package(
            rules=[
                {
                    "code": "pa-task-dry-run",
                    "name": "Dry run package",
                    "description": "Regola con action multiple",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "Task Status",
                    "is_active": False,
                    "is_draft": True,
                    "conditions": [
                        {
                            "field": "Task Status",
                            "operator": "equals",
                            "value": "DONE",
                            "value_type": "string",
                        }
                    ],
                    "actions": [
                        {
                            "action_type": "send_email",
                            "to": "ops@example.com",
                            "from_email": "noreply@example.com",
                            "subject_template": "Task {title}",
                            "body_text_template": "Stato {status}",
                        },
                        {
                            "action_type": "update_dashboard_metric",
                            "metric_code": "tasks_done",
                            "operation": "increment",
                            "value_template": "1",
                        },
                    ],
                }
            ]
        )
        self._analyze_package(package)

        response = self._run_dry_run(sample_mode="record", record_id=task.id)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Esito dry-run")
        self.assertEqual(AutomationRunLog.objects.count(), 0)
        self.assertEqual(AutomationActionLog.objects.count(), 0)
        self.assertEqual(DashboardMetricValue.objects.count(), 0)
        mock_email_class.assert_not_called()

    def test_dry_run_supports_send_approval_preview_with_template_code(self):
        from .models import ApprovalEmailTemplate

        template = ApprovalEmailTemplate.objects.create(
            code="tpl-dry-run-approval",
            name="Template Dry Run Approval",
            delivery_mode="hybrid",
            subject_template="Subject {id}",
        )
        package = {
            "package_version": "2026.03",
            "input": {"flow_name": "Assenze Approval Dry Run"},
            "source_candidate": {"source_code": "assenze", "label": "Assenze"},
            "compatibility": {"compatible": True, "status": "ok"},
            "issues": [],
            "target_context": {"module": "automazioni", "source": "assenze"},
            "approved_field_mapping": {
                "EmailDipendente": "dipendente_email",
                "CAR": "capo_email",
                "Tipoassenza": "tipo_assenza",
                "Data_x0020_inizio": "data_inizio",
                "Datafine": "data_fine",
            },
            "proposed_rules": [
                {
                    "code": "pa-assenze-send-approval-dry-run",
                    "name": "Assenze approval dry run",
                    "source_code": "assenze",
                    "operation_type": "insert",
                    "trigger_scope": "all_inserts",
                    "is_active": False,
                    "is_draft": True,
                    "actions": [
                        {
                            "action_type": "send_approval",
                            "config_json": {
                                "delivery_mode": "email",
                                "to_template": "{capo_email}",
                                "subject_template": "Approval {id}",
                                "message_template": "Body {tipo_assenza}",
                                "approval_email_template_code": template.code,
                                "approved_actions": [
                                    {
                                        "action_type": "update_trigger_record",
                                        "config_json": {"update_fields": {"moderation_status": 0}},
                                    }
                                ],
                                "rejected_actions": [
                                    {
                                        "action_type": "write_log",
                                        "config_json": {"message_template": "KO {id}"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
        self._analyze_package(package)

        response = self._run_dry_run(
            sample_mode="json",
            payload=build_example_payload("assenze"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approval dry-run")
        self.assertContains(response, template.code)
        self.assertContains(response, "approved_actions=1")
        self.assertContains(response, "rejected_actions=1")

    def test_import_creates_draft_rules_and_metadata(self):
        package = self._base_package(
            rules=[
                {
                    "code": "pa-task-import",
                    "name": "Import draft task",
                    "description": "Da package esterno",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "Task Status",
                    "is_active": True,
                    "is_draft": False,
                    "stop_on_first_failure": True,
                    "conditions": [
                        {
                            "field": "Task Status",
                            "operator": "equals",
                            "value": "DONE",
                            "value_type": "string",
                        }
                    ],
                    "actions": [
                        {
                            "action_type": "write_log",
                            "description": "Logga",
                            "message_template": "Task {title} -> {status}",
                        },
                        {
                            "action_type": "update_record",
                            "description": "Aggiorna task",
                            "target_table": "tasks_task",
                            "where_field": "id",
                            "where_value_template": "{id}",
                            "update_fields": {"status": "DONE"},
                        },
                    ],
                }
            ]
        )
        self._analyze_package(package)
        self._run_dry_run(
            sample_mode="json",
            payload={
                "id": 99,
                "title": "Task import",
                "status": "DONE",
                "assigned_to_id": self.user.id,
                "project_id": 1,
                "due_date": "2026-03-11",
            },
            old_payload={
                "id": 99,
                "title": "Task import",
                "status": "TODO",
                "assigned_to_id": self.user.id,
                "project_id": 1,
                "due_date": "2026-03-11",
            },
        )

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_import_package"),
            {"action": "import"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        rule = AutomationRule.objects.get(import_source_rule_code="pa-task-import")
        self.assertFalse(rule.is_active)
        self.assertTrue(rule.is_draft)
        self.assertEqual(rule.import_flow_name, "Task Import Flow")
        self.assertEqual(rule.import_source_package_version, "2026.03")
        self.assertEqual(rule.conditions.count(), 1)
        self.assertEqual(rule.actions.count(), 2)
        self.assertContains(response, "Regole create")
        self.assertContains(response, reverse("admin_portale:automazioni_rule_detail", args=[rule.id]))

    def test_import_can_activate_rules_after_successful_dry_run(self):
        package = self._base_package(
            rules=[
                {
                    "code": "pa-task-activate",
                    "name": "Import active task",
                    "description": "Da package esterno",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "Task Status",
                    "is_active": False,
                    "is_draft": True,
                    "conditions": [
                        {
                            "field": "Task Status",
                            "operator": "equals",
                            "value": "DONE",
                            "value_type": "string",
                        }
                    ],
                    "actions": [
                        {
                            "action_type": "write_log",
                            "description": "Logga",
                            "message_template": "Task {title} -> {status}",
                        }
                    ],
                }
            ]
        )
        self._analyze_package(package)
        self._run_dry_run(
            sample_mode="json",
            payload={
                "id": 99,
                "title": "Task import",
                "status": "DONE",
                "assigned_to_id": self.user.id,
                "project_id": 1,
                "due_date": "2026-03-11",
            },
            old_payload={
                "id": 99,
                "title": "Task import",
                "status": "TODO",
                "assigned_to_id": self.user.id,
                "project_id": 1,
                "due_date": "2026-03-11",
            },
        )

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_import_package"),
            {"action": "import", "activate_after_import": "1"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        rule = AutomationRule.objects.get(import_source_rule_code="pa-task-activate")
        self.assertTrue(rule.is_active)
        self.assertFalse(rule.is_draft)
        self.assertContains(response, "Regole attivate")
        self.assertContains(response, "attiva")

    def test_activation_is_blocked_when_dry_run_importable_rules_have_errors(self):
        package = self._base_package(
            rules=[
                {
                    "code": "pa-task-activate-invalid",
                    "name": "Import active invalid task",
                    "description": "Da package esterno",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "all_updates",
                    "is_active": False,
                    "is_draft": True,
                    "actions": [
                        {
                            "action_type": "send_email",
                            "description": "Invia email",
                            "to": "{title}",
                            "from_email": "noreply@example.com",
                            "subject_template": "Task {title}",
                            "body_text_template": "Stato {status}",
                        }
                    ],
                }
            ]
        )
        self._analyze_package(package)
        self._run_dry_run(
            sample_mode="json",
            payload={
                "id": 100,
                "title": "titolo non email",
                "status": "DONE",
                "assigned_to_id": self.user.id,
                "project_id": 1,
                "due_date": "2026-03-11",
            },
        )

        response = self.client.post(
            reverse("admin_portale:automazioni_rule_import_package"),
            {"action": "import", "activate_after_import": "1"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "attivazione diretta richiede un test al volo valido", html=False)
        self.assertEqual(AutomationRule.objects.filter(import_source_rule_code="pa-task-activate-invalid").count(), 0)

    def test_import_rolls_back_if_a_rule_fails(self):
        package = self._base_package(
            rules=[
                {
                    "code": "pa-task-import-a",
                    "name": "Rule A",
                    "description": "",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "all_updates",
                    "is_active": False,
                    "is_draft": True,
                    "actions": [
                        {
                            "action_type": "write_log",
                            "message_template": "A {title}",
                        }
                    ],
                },
                {
                    "code": "pa-task-import-b",
                    "name": "Rule B",
                    "description": "",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "all_updates",
                    "is_active": False,
                    "is_draft": True,
                    "actions": [
                        {
                            "action_type": "write_log",
                            "message_template": "B {title}",
                        }
                    ],
                },
            ]
        )
        analysis = analyze_package_dict(package, filename="tasks.automation_package.json")
        original_create_imported_rule = package_importer._create_imported_rule
        call_state = {"count": 0}

        def flaky_create_imported_rule(*args, **kwargs):
            call_state["count"] += 1
            if call_state["count"] == 2:
                raise RuntimeError("boom")
            return original_create_imported_rule(*args, **kwargs)

        with patch("automazioni.package_importer._create_imported_rule", side_effect=flaky_create_imported_rule):
            with self.assertRaises(RuntimeError):
                import_analyzed_package(analysis, created_by=self.user)

        self.assertEqual(AutomationRule.objects.count(), 0)
        self.assertEqual(AutomationCondition.objects.count(), 0)
        self.assertEqual(AutomationAction.objects.count(), 0)

    def test_unsupported_actions_are_skipped_and_reported(self):
        package = self._base_package(
            rules=[
                {
                    "code": "pa-task-valid",
                    "name": "Rule valida",
                    "description": "",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "all_updates",
                    "is_active": False,
                    "is_draft": True,
                    "actions": [
                        {
                            "action_type": "write_log",
                            "message_template": "Valida {title}",
                        }
                    ],
                },
                {
                    "code": "pa-task-unsupported",
                    "name": "Rule non supportata",
                    "description": "",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "all_updates",
                    "is_active": False,
                    "is_draft": True,
                    "actions": [
                        {
                            "action_type": "unsupported_magic",
                            "description": "Non supportata",
                        }
                    ],
                },
            ]
        )

        analysis = self._analyze_package(package)
        self.assertEqual(analysis["status"], "partial")
        self.assertEqual(analysis["importable_rule_count"], 1)
        self.assertEqual(analysis["skipped_rule_count"], 1)

        self._run_dry_run(
            sample_mode="json",
            payload={
                "id": 1,
                "title": "Task partial",
                "status": "DONE",
                "assigned_to_id": self.user.id,
                "project_id": 1,
                "due_date": "2026-03-11",
            },
        )
        response = self.client.post(
            reverse("admin_portale:automazioni_rule_import_package"),
            {"action": "import"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AutomationRule.objects.filter(import_flow_name="Task Import Flow").count(), 1)
        self.assertContains(response, "Rule non supportata")
        self.assertContains(response, "unsupported_magic")

    def test_assenze_runtime_fields_are_importable_and_external_mapping_noise_is_condensed(self):
        package = {
            "package_version": "1.0",
            "input": {"flow_name": "Certificazione presenza"},
            "source_candidate": {"source_code": "assenze", "label": "Assenze"},
            "compatibility": {"compatible": True, "status": "partial"},
            "issues": [],
            "target_context": {
                "database": "PORTALE NOVICROM",
                "schema": "dbo",
                "table": "assenze_certificazionepresenza",
                "full_name": "dbo.assenze_certificazionepresenza",
            },
            "approved_field_mapping": {
                "ID": "id",
                "DATAINIZIO": "data",
                "Email": "dipendente_email",
                "SALTAAPPROVAZIONE": "salta_approvazione",
            },
            "proposed_rules": [
                {
                    "code": "pa-assenze-update-approvata-notifica-dipendente",
                    "name": "Esito approvazione assenza",
                    "description": "",
                    "source_code": "assenze",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "moderation_status",
                    "is_active": False,
                    "is_draft": True,
                    "conditions": [
                        {
                            "field": "moderation_status",
                            "operator": "changed_to",
                            "value": "0",
                            "value_type": "int",
                            "compare_with_old": True,
                        }
                    ],
                    "actions": [
                        {
                            "action_type": "send_email",
                            "to": "{dipendente_email}",
                            "from_email": "noreply@example.com",
                            "subject_template": "Esito #{id}",
                            "body_text_template": "Esito per {dipendente_email}",
                        }
                    ],
                },
                {
                    "code": "pa-assenze-insert-skip-approval-audit",
                    "name": "Audit skip approval",
                    "description": "",
                    "source_code": "assenze",
                    "operation_type": "insert",
                    "trigger_scope": "all_inserts",
                    "is_active": False,
                    "is_draft": True,
                    "conditions": [
                        {
                            "field": "salta_approvazione",
                            "operator": "is_true",
                            "value_type": "bool",
                        }
                    ],
                    "actions": [
                        {
                            "action_type": "write_log",
                            "message_template": "skip {salta_approvazione}",
                        }
                    ],
                },
            ],
        }

        analysis = analyze_package_dict(package, filename="assenze.automation_package.json")

        self.assertEqual(analysis["importable_rule_count"], 2)
        self.assertTrue(all(rule["is_importable"] for rule in analysis["rules"]))
        self.assertTrue(any("target_context punta" in warning for warning in analysis["warnings"]))
        self.assertFalse(any("Mapping non risolto" in warning for warning in analysis["warnings"]))
        mapping_rows = {row["source_field"]: row for row in analysis["mapping_rows"]}
        self.assertEqual(mapping_rows["ID"]["status"], "ok")
        self.assertEqual(mapping_rows["DATAINIZIO"]["status"], "ok")

    @patch("automazioni.package_importer.enrich_payload_for_source")
    @patch("automazioni.package_importer.connection.cursor")
    def test_load_source_record_payload_supports_alias_fields_and_virtual_enrichment(
        self,
        mock_connection_cursor,
        mock_enrich_payload,
    ):
        cursor = MagicMock()
        cursor.fetchone.return_value = (
            4051,
            101,
            "2026-03-11T06:00:00",
            "2026-03-11T14:00:00",
            "Ferie",
            "Richiesta di test",
            0,
            22,
            "dipendente@example.com",
            True,
        )
        cursor.description = [
            ("id",),
            ("dipendente_id",),
            ("data_inizio",),
            ("data_fine",),
            ("tipo_assenza",),
            ("motivazione_richiesta",),
            ("moderation_status",),
            ("capo_reparto_id",),
            ("dipendente_email",),
            ("salta_approvazione",),
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False
        mock_connection_cursor.return_value = cursor_context
        mock_enrich_payload.side_effect = lambda source_code, payload: {
            **payload,
            "capo_email": "capo@example.com",
        }

        payload = package_importer.load_source_record_payload("assenze", 4051)

        self.assertEqual(payload["dipendente_email"], "dipendente@example.com")
        self.assertTrue(payload["salta_approvazione"])
        self.assertEqual(payload["capo_email"], "capo@example.com")
        sql = cursor.execute.call_args.args[0]
        self.assertIn("email_esterna", sql)
        self.assertIn("dipendente_email", sql)
        self.assertNotIn("capo_email", sql)

    def test_aliases_are_resolved_for_all_registered_sources(self):
        scenarios = [
            {
                "filename": "tasks.automation_package.json",
                "source_code": "tasks",
                "rule": {
                    "code": "tasks-alias",
                    "name": "Tasks alias",
                    "source_code": "tasks",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "assigned_to",
                    "conditions": [{"field": "task_status", "operator": "equals", "value": "DONE", "value_type": "string"}],
                    "actions": [{"action_type": "write_log", "message_template": "Task {titolo} scade {deadline}"}],
                },
                "expected_watched_field": "assigned_to_id",
                "expected_condition_field": "status",
                "expected_template": "Task {title} scade {due_date}",
            },
            {
                "filename": "assets.automation_package.json",
                "source_code": "assets",
                "rule": {
                    "code": "assets-alias",
                    "name": "Assets alias",
                    "source_code": "assets",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "codice",
                    "conditions": [{"field": "sede", "operator": "is_not_empty", "value_type": "string"}],
                    "actions": [{"action_type": "write_log", "message_template": "Asset {codice} in {location}"}],
                },
                "expected_watched_field": "asset_tag",
                "expected_condition_field": "assignment_location",
                "expected_template": "Asset {asset_tag} in {assignment_location}",
            },
            {
                "filename": "tickets.automation_package.json",
                "source_code": "tickets",
                "rule": {
                    "code": "tickets-alias",
                    "name": "Tickets alias",
                    "source_code": "tickets",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "status",
                    "conditions": [{"field": "category", "operator": "is_not_empty", "value_type": "string"}],
                    "actions": [{"action_type": "write_log", "message_template": "Ticket {title} -> {assigned_to}"}],
                },
                "expected_watched_field": "stato",
                "expected_condition_field": "categoria",
                "expected_template": "Ticket {titolo} -> {assegnato_a}",
            },
            {
                "filename": "anomalie.automation_package.json",
                "source_code": "anomalie",
                "rule": {
                    "code": "anomalie-alias",
                    "name": "Anomalie alias",
                    "source_code": "anomalie",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "status",
                    "conditions": [{"field": "created_by_user_id", "operator": "equals", "value": "15", "value_type": "int"}],
                    "actions": [{"action_type": "write_log", "message_template": "Anomalia {pn} op {op}"}],
                },
                "expected_watched_field": "avanzamento",
                "expected_condition_field": "created_by",
                "expected_template": "Anomalia {seriale} op {ex_op_nominativo}",
            },
            {
                "filename": "assenze.automation_package.json",
                "source_code": "assenze",
                "rule": {
                    "code": "assenze-alias",
                    "name": "Assenze alias",
                    "source_code": "assenze",
                    "operation_type": "update",
                    "trigger_scope": "specific_field",
                    "watched_field": "ModerationStatus",
                    "conditions": [{"field": "SALTAAPPROVAZIONE", "operator": "is_true", "value_type": "bool"}],
                    "actions": [{"action_type": "write_log", "message_template": "Assenza {Email} {CAR}"}],
                },
                "expected_watched_field": "moderation_status",
                "expected_condition_field": "salta_approvazione",
                "expected_template": "Assenza {dipendente_email} {capo_email}",
            },
        ]

        for scenario in scenarios:
            analysis = analyze_package_dict(
                {
                    "package_version": "1.0",
                    "input": {"flow_name": f"{scenario['source_code']} import"},
                    "source_candidate": {
                        "source_code": scenario["source_code"],
                        "label": scenario["source_code"].title(),
                    },
                    "compatibility": {"compatible": True, "status": "ok"},
                    "issues": [],
                    "target_context": {"module": "automazioni", "source": scenario["source_code"]},
                    "proposed_rules": [scenario["rule"]],
                },
                filename=scenario["filename"],
            )

            self.assertEqual(analysis["importable_rule_count"], 1, msg=scenario["source_code"])
            rule_plan = analysis["rules"][0]
            self.assertTrue(rule_plan["is_importable"], msg=scenario["source_code"])
            self.assertEqual(rule_plan["watched_field"], scenario["expected_watched_field"])
            self.assertEqual(rule_plan["conditions"][0]["field_name"], scenario["expected_condition_field"])
            self.assertEqual(
                rule_plan["actions"][0]["config_json"]["message_template"],
                scenario["expected_template"],
            )

    @patch("automazioni.package_importer.connection.cursor")
    def test_load_source_record_payload_supports_anomalie_db_column_alias(self, mock_connection_cursor):
        cursor = MagicMock()
        cursor.fetchone.return_value = (91, "OP-001", 42, "SN-001", "APERTO", False, 7, 8001)
        cursor.description = [
            ("id",),
            ("ex_op_nominativo",),
            ("op_lookup_id",),
            ("seriale",),
            ("avanzamento",),
            ("chiudere",),
            ("created_by",),
            ("ordine_id",),
        ]
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        cursor_context.__exit__.return_value = False
        mock_connection_cursor.return_value = cursor_context

        payload = package_importer.load_source_record_payload("anomalie", 91)

        self.assertEqual(payload["created_by"], 7)
        sql = cursor.execute.call_args.args[0]
        self.assertIn("created_by_user_id", sql)
        self.assertIn(f"AS {connection.ops.quote_name('created_by')}", sql)


class AutomationRuleModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="rule-user", password="pass12345")

    def test_rule_creation_and_str(self):
        rule = AutomationRule.objects.create(
            code="assenze-approvate",
            name="Assenze approvate",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            watched_field="moderation_status",
            trigger_scope=AutomationRuleTriggerScope.SPECIFIC_FIELD,
            is_active=True,
            is_draft=False,
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertEqual(str(rule), "Assenze approvate [assenze-approvate]")
        self.assertEqual(rule.created_by, self.user)

    def test_rule_requires_watched_field_for_specific_field_scope(self):
        rule = AutomationRule(
            code="assenze-missing-field",
            name="Assenze missing field",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.SPECIFIC_FIELD,
        )

        with self.assertRaises(ValidationError) as exc:
            rule.full_clean()

        self.assertIn("watched_field", exc.exception.message_dict)

    def test_rule_rejects_watched_field_for_non_specific_scope(self):
        rule = AutomationRule(
            code="assenze-all-updates",
            name="Assenze all updates",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            watched_field="moderation_status",
        )

        with self.assertRaises(ValidationError) as exc:
            rule.full_clean()

        self.assertIn("watched_field", exc.exception.message_dict)

    def test_rule_rejects_insert_scope_incompatible_with_insert_operation(self):
        rule = AutomationRule(
            code="tasks-insert-any-change",
            name="Tasks insert any change",
            source_code="tasks",
            operation_type=AutomationRuleOperationType.INSERT,
            trigger_scope=AutomationRuleTriggerScope.ANY_CHANGE,
        )

        with self.assertRaises(ValidationError) as exc:
            rule.full_clean()

        self.assertIn("trigger_scope", exc.exception.message_dict)


class AutomationConditionModelTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="rule-condition-order",
            name="Rule condition order",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )

    def test_condition_choices_and_valid_creation(self):
        self.assertIn(AutomationConditionOperator.CHANGED, AutomationConditionOperator.values)
        self.assertIn(AutomationConditionValueType.DATETIME, AutomationConditionValueType.values)

        condition = AutomationCondition.objects.create(
            rule=self.rule,
            order=1,
            field_name="moderation_status",
            operator=AutomationConditionOperator.EQUALS,
            expected_value="1",
            value_type=AutomationConditionValueType.INT,
            compare_with_old=True,
        )

        self.assertEqual(condition.field_name, "moderation_status")
        self.assertTrue(condition.compare_with_old)

    def test_conditions_are_ordered_by_order_then_id(self):
        AutomationCondition.objects.create(
            rule=self.rule,
            order=20,
            field_name="tipo_assenza",
            operator=AutomationConditionOperator.CONTAINS,
            expected_value="Permesso",
            value_type=AutomationConditionValueType.STRING,
        )
        AutomationCondition.objects.create(
            rule=self.rule,
            order=10,
            field_name="moderation_status",
            operator=AutomationConditionOperator.EQUALS,
            expected_value="1",
            value_type=AutomationConditionValueType.INT,
        )

        self.assertEqual(list(self.rule.conditions.values_list("order", flat=True)), [10, 20])


class AutomationActionModelTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="rule-action",
            name="Rule action",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )

    def test_action_json_config_is_persisted(self):
        self.assertIn(AutomationActionType.SEND_EMAIL, AutomationActionType.values)

        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.SEND_EMAIL,
            description="Invio notifica HR",
            config_json={
                "from_email": "hr@azienda.local",
                "to": ["capo@azienda.local"],
                "subject_template": "Assenza approvata #{id}",
                "body_text_template": "Richiesta {id} approvata",
            },
        )

        self.assertEqual(action.config_json["from_email"], "hr@azienda.local")
        self.assertEqual(action.config_json["to"], ["capo@azienda.local"])


class AutomationRunLogModelTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="rule-run-log",
            name="Rule run log",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )

    def test_run_log_stores_payloads_and_status(self):
        self.assertIn(AutomationRunLogStatus.TEST, AutomationRunLogStatus.values)

        run_log = AutomationRunLog.objects.create(
            rule=self.rule,
            queue_event_id=10,
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_event_label="assenze_update",
            status=AutomationRunLogStatus.SUCCESS,
            payload_json={"id": 1, "moderation_status": 1},
            old_payload_json={"id": 1, "moderation_status": 2},
            result_message="OK",
        )

        self.assertEqual(run_log.payload_json["moderation_status"], 1)
        self.assertEqual(run_log.old_payload_json["moderation_status"], 2)


class DashboardMetricValueModelTests(TestCase):
    def test_metric_code_is_unique(self):
        DashboardMetricValue.objects.create(
            metric_code="assenze_approvate_oggi",
            label="Assenze approvate oggi",
            current_value="1.0000",
        )

        with self.assertRaises(IntegrityError):
            DashboardMetricValue.objects.create(
                metric_code="assenze_approvate_oggi",
                label="Duplicato",
                current_value="2.0000",
            )


class AutomationServiceHelperTests(TestCase):
    def test_safe_get_payload_value_supports_simple_and_nested_fields(self):
        payload = {"id": 1, "utente": {"email": "a@b.it", "reparto": {"nome": "HR"}}}

        self.assertEqual(safe_get_payload_value(payload, "id"), 1)
        self.assertEqual(safe_get_payload_value(payload, "utente.email"), "a@b.it")
        self.assertEqual(safe_get_payload_value(payload, "utente.reparto.nome"), "HR")

    def test_safe_get_payload_value_handles_missing_payload_or_field(self):
        self.assertIsNone(safe_get_payload_value(None, "id"))
        self.assertIsNone(safe_get_payload_value({"utente": None}, "utente.email"))
        self.assertIsNone(safe_get_payload_value({"id": 1}, "missing"))

    def test_render_template_string_renders_known_placeholders_and_keeps_missing_ones(self):
        self.assertEqual(render_template_string("Richiesta {id}", {"id": 5}), "Richiesta 5")
        self.assertEqual(render_template_string("Richiesta {missing}", {"id": 5}), "Richiesta {missing}")
        self.assertEqual(render_template_string(None, {"id": 5}), "")

    @patch("automazioni.services._fetch_assenza_runtime_details", return_value={})
    @patch("automazioni.services._resolve_caporeparto_email_from_local_id", return_value="capo@example.com")
    def test_enrich_payload_for_source_assenze_resolves_capo_email_from_local_caporeparto_id(
        self,
        _mock_resolve_local_capo_email,
        _mock_runtime_details,
    ):
        enriched = enrich_payload_for_source("assenze", {"id": 4060, "capo_reparto_id": 7})
        self.assertEqual(enriched["capo_email"], "capo@example.com")

    @patch(
        "automazioni.services._fetch_assenza_runtime_details",
        return_value={"capo_reparto_id": 9, "dipendente_nome": "Mario Rossi"},
    )
    @patch("automazioni.services._resolve_caporeparto_email_from_local_id", return_value="capo@example.com")
    def test_enrich_payload_for_source_assenze_uses_runtime_details_for_missing_manager_and_name(
        self,
        _mock_resolve_local_capo_email,
        _mock_runtime_details,
    ):
        enriched = enrich_payload_for_source("assenze", {"id": 17})
        self.assertEqual(enriched["capo_reparto_id"], 9)
        self.assertEqual(enriched["capo_email"], "capo@example.com")
        self.assertEqual(enriched["dipendente_nome"], "Mario Rossi")

    @patch("automazioni.services.connection.cursor")
    @patch("automazioni.services._queue_table_has_column", return_value=False)
    def test_fetch_pending_queue_events_skips_execute_after_when_column_missing(
        self,
        _mock_has_column,
        mock_connection_cursor,
    ):
        cursor = MagicMock()
        cursor.description = [("id",), ("status",)]
        cursor.fetchall.return_value = []
        mock_connection_cursor.return_value.__enter__.return_value = cursor

        fetch_pending_queue_events(limit=5, source_code="assenze")

        sql = cursor.execute.call_args.args[0]
        params = cursor.execute.call_args.args[1]
        self.assertNotIn("execute_after", sql)
        self.assertIn("source_code = %s", sql)
        self.assertEqual(params, ["pending", "assenze", "processing"])

    @patch("automazioni.services.connection.cursor")
    @patch("automazioni.services._queue_table_has_column", return_value=True)
    def test_fetch_pending_queue_events_uses_execute_after_when_column_available(
        self,
        _mock_has_column,
        mock_connection_cursor,
    ):
        cursor = MagicMock()
        cursor.description = [("id",), ("status",)]
        cursor.fetchall.return_value = []
        mock_connection_cursor.return_value.__enter__.return_value = cursor

        fetch_pending_queue_events(limit=5, source_code="assenze")

        sql = cursor.execute.call_args.args[0]
        self.assertIn("execute_after", sql)

    @patch("automazioni.services.connection.cursor")
    @patch("automazioni.services._queue_table_has_column", return_value=False)
    def test_fetch_pending_queue_event_snapshots_skip_execute_after_when_column_missing(
        self,
        _mock_has_column,
        mock_connection_cursor,
    ):
        cursor = MagicMock()
        cursor.description = [("id",), ("status",)]
        cursor.fetchall.return_value = []
        mock_connection_cursor.return_value.__enter__.return_value = cursor

        fetch_pending_queue_event_snapshots(limit=5, source_code="assenze")

        sql = cursor.execute.call_args.args[0]
        params = cursor.execute.call_args.args[1]
        self.assertNotIn("execute_after", sql)
        self.assertEqual(params, ["pending", "assenze"])


class AutomationConditionEvaluationTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="rule-condition-runtime",
            name="Rule condition runtime",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        self.payload = {
            "id": 1,
            "tipo_assenza": "Permesso retribuito",
            "moderation_status": 2,
            "richiesta": {"durata_ore": "8"},
            "approved": "true",
            "tags": "",
        }
        self.old_payload = {
            "id": 1,
            "tipo_assenza": "Bozza",
            "moderation_status": 1,
            "richiesta": {"durata_ore": "4"},
            "approved": "false",
            "tags": "",
        }

    def _condition(self, **overrides):
        base = {
            "rule": self.rule,
            "order": 1,
            "field_name": "moderation_status",
            "operator": AutomationConditionOperator.EQUALS,
            "expected_value": "2",
            "value_type": AutomationConditionValueType.INT,
        }
        base.update(overrides)
        return AutomationCondition(**base)

    def test_evaluate_condition_equals(self):
        self.assertTrue(evaluate_condition(self._condition(), self.payload))

    def test_evaluate_condition_not_equals(self):
        condition = self._condition(
            operator=AutomationConditionOperator.NOT_EQUALS,
            expected_value="3",
        )
        self.assertTrue(evaluate_condition(condition, self.payload))

    def test_evaluate_condition_contains(self):
        condition = self._condition(
            field_name="tipo_assenza",
            operator=AutomationConditionOperator.CONTAINS,
            expected_value="Permesso",
            value_type=AutomationConditionValueType.STRING,
        )
        self.assertTrue(evaluate_condition(condition, self.payload))

    def test_evaluate_condition_gt(self):
        condition = self._condition(
            field_name="richiesta.durata_ore",
            operator=AutomationConditionOperator.GT,
            expected_value="6",
            value_type=AutomationConditionValueType.INT,
        )
        self.assertTrue(evaluate_condition(condition, self.payload))

    def test_evaluate_condition_is_true(self):
        condition = self._condition(
            field_name="approved",
            operator=AutomationConditionOperator.IS_TRUE,
            expected_value="",
            value_type=AutomationConditionValueType.BOOL,
        )
        self.assertTrue(evaluate_condition(condition, self.payload))

    def test_evaluate_condition_in_csv(self):
        condition = self._condition(
            operator=AutomationConditionOperator.IN_CSV,
            expected_value="1,2,3",
        )
        self.assertTrue(evaluate_condition(condition, self.payload))

    def test_evaluate_condition_is_empty(self):
        condition = self._condition(
            field_name="tags",
            operator=AutomationConditionOperator.IS_EMPTY,
            expected_value="",
            value_type=AutomationConditionValueType.STRING,
        )
        self.assertTrue(evaluate_condition(condition, self.payload))

    def test_evaluate_condition_changed(self):
        condition = self._condition(operator=AutomationConditionOperator.CHANGED)
        self.assertTrue(evaluate_condition(condition, self.payload, old_payload=self.old_payload))

    def test_evaluate_condition_changed_to(self):
        condition = self._condition(
            operator=AutomationConditionOperator.CHANGED_TO,
            expected_value="2",
        )
        self.assertTrue(evaluate_condition(condition, self.payload, old_payload=self.old_payload))

    def test_evaluate_condition_changed_from_to(self):
        condition = self._condition(
            operator=AutomationConditionOperator.CHANGED_FROM_TO,
            expected_value="1|2",
        )
        self.assertTrue(evaluate_condition(condition, self.payload, old_payload=self.old_payload))


class AutomationRunRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="runtime-user", password="pass12345")
        self.payload = {
            "id": 7,
            "dipendente_id": 3,
            "moderation_status": 1,
            "tipo_assenza": "Permesso",
        }
        self.old_payload = {
            "id": 7,
            "dipendente_id": 3,
            "moderation_status": 0,
            "tipo_assenza": "Permesso",
        }

    def test_run_rule_skips_when_condition_fails(self):
        rule = AutomationRule.objects.create(
            code="skip-rule",
            name="Skip rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        AutomationCondition.objects.create(
            rule=rule,
            order=1,
            field_name="moderation_status",
            operator=AutomationConditionOperator.EQUALS,
            expected_value="9",
            value_type=AutomationConditionValueType.INT,
        )

        run_log = run_rule(rule, self.payload, old_payload=self.old_payload, queue_event_id=101, initiated_by=self.user)

        self.assertEqual(run_log.status, AutomationRunLogStatus.SKIPPED)
        self.assertEqual(run_log.queue_event_id, 101)
        self.assertEqual(run_log.action_logs.count(), 0)

    def test_run_rule_success_with_write_log(self):
        rule = AutomationRule.objects.create(
            code="write-log-rule",
            name="Write log rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            config_json={"message_template": "Automazione eseguita per richiesta #{id}"},
        )

        run_log = run_rule(rule, self.payload, old_payload=self.old_payload)

        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(run_log.action_logs.count(), 1)
        self.assertEqual(run_log.action_logs.first().status, AutomationActionLogStatus.SUCCESS)
        self.assertIn("richiesta #7", run_log.action_logs.first().result_message)

    @patch("automazioni.services._resolve_legacy_user_email", return_value="capo@example.com")
    def test_run_rule_persists_enriched_capo_email_in_run_log(self, _mock_resolve_email):
        rule = AutomationRule.objects.create(
            code="capo-email-rule",
            name="Capo email rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )

        run_log = run_rule(
            rule,
            {**self.payload, "capo_reparto_id": 12},
            old_payload={**self.old_payload, "capo_reparto_id": 12},
        )

        self.assertEqual(run_log.payload_json["capo_email"], "capo@example.com")
        self.assertEqual(run_log.old_payload_json["capo_email"], "capo@example.com")

    @patch(
        "automazioni.services._fetch_assenza_runtime_details",
        return_value={
            "dipendente_email": "dipendente@example.com",
            "dipendente_nome": "Mario Rossi",
            "salta_approvazione": True,
        },
    )
    @patch("automazioni.services._resolve_legacy_user_email", return_value="capo@example.com")
    def test_run_rule_persists_enriched_assenze_runtime_fields_in_run_log(
        self,
        _mock_resolve_email,
        _mock_runtime_details,
    ):
        rule = AutomationRule.objects.create(
            code="assenze-runtime-fields-rule",
            name="Assenze runtime fields rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )

        run_log = run_rule(
            rule,
            {**self.payload, "capo_reparto_id": 12},
            old_payload={**self.old_payload, "capo_reparto_id": 12},
        )

        self.assertEqual(run_log.payload_json["capo_email"], "capo@example.com")
        self.assertEqual(run_log.payload_json["dipendente_email"], "dipendente@example.com")
        self.assertEqual(run_log.payload_json["dipendente_nome"], "Mario Rossi")
        self.assertTrue(run_log.payload_json["salta_approvazione"])
        self.assertEqual(run_log.old_payload_json["dipendente_email"], "dipendente@example.com")
        self.assertEqual(run_log.old_payload_json["dipendente_nome"], "Mario Rossi")
        self.assertTrue(run_log.old_payload_json["salta_approvazione"])

    def test_run_rule_success_with_update_dashboard_metric(self):
        rule = AutomationRule.objects.create(
            code="metric-rule",
            name="Metric rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.UPDATE_DASHBOARD_METRIC,
            config_json={
                "metric_code": "assenze_approvate_oggi",
                "operation": "increment",
                "value_template": "1.5",
            },
        )

        run_log = run_rule(rule, self.payload, old_payload=self.old_payload)
        metric = DashboardMetricValue.objects.get(metric_code="assenze_approvate_oggi")

        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(metric.current_value, Decimal("1.5000"))

    def test_run_rule_stops_on_first_failure(self):
        rule = AutomationRule.objects.create(
            code="stop-first-rule",
            name="Stop first rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            stop_on_first_failure=True,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.SEND_EMAIL,
            config_json={},
        )
        AutomationAction.objects.create(
            rule=rule,
            order=2,
            action_type=AutomationActionType.WRITE_LOG,
            config_json={"message_template": "Questa action non deve partire"},
        )

        run_log = run_rule(rule, self.payload, old_payload=self.old_payload)

        self.assertEqual(run_log.status, AutomationRunLogStatus.ERROR)
        self.assertEqual(run_log.action_logs.count(), 1)
        self.assertEqual(run_log.action_logs.first().status, AutomationActionLogStatus.ERROR)

    def test_run_rule_marks_test_runs(self):
        rule = AutomationRule.objects.create(
            code="test-rule",
            name="Test rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            config_json={"message_template": "Test #{id}"},
        )

        run_log = run_rule(rule, self.payload, old_payload=self.old_payload, is_test=True, initiated_by=self.user)
        rule.refresh_from_db()

        self.assertEqual(run_log.status, AutomationRunLogStatus.TEST)
        self.assertTrue(run_log.is_test)
        self.assertIsNotNone(rule.last_test_at)


class DashboardMetricRuntimeTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="metric-runtime",
            name="Metric runtime",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        self.payload = {"id": 1, "metric_value": "2.5"}

    def _run_metric_action(self, operation, value_template, metric_code="assenze_metric"):
        AutomationAction.objects.all().delete()
        AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.UPDATE_DASHBOARD_METRIC,
            config_json={
                "metric_code": metric_code,
                "operation": operation,
                "value_template": value_template,
            },
        )
        return run_rule(self.rule, self.payload, old_payload=None)

    def test_metric_created_on_first_use(self):
        run_log = self._run_metric_action("increment", "1")
        metric = DashboardMetricValue.objects.get(metric_code="assenze_metric")

        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(metric.current_value, Decimal("1.0000"))

    def test_metric_increment_and_decrement(self):
        DashboardMetricValue.objects.create(
            metric_code="assenze_metric",
            label="Assenze metric",
            current_value="5.0000",
        )

        run_log = self._run_metric_action("increment", "2")
        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(
            DashboardMetricValue.objects.get(metric_code="assenze_metric").current_value,
            Decimal("7.0000"),
        )

        run_log = self._run_metric_action("decrement", "1.5")
        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(
            DashboardMetricValue.objects.get(metric_code="assenze_metric").current_value,
            Decimal("5.5000"),
        )

    def test_metric_set_supports_decimals(self):
        DashboardMetricValue.objects.create(
            metric_code="assenze_metric",
            label="Assenze metric",
            current_value="0.0000",
        )

        run_log = self._run_metric_action("set", "{metric_value}")

        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(
            DashboardMetricValue.objects.get(metric_code="assenze_metric").current_value,
            Decimal("2.5000"),
        )


@override_settings(DEFAULT_FROM_EMAIL="noreply@test.local")
class AutomationEmailExecutorTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="email-runtime",
            name="Email runtime",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        self.payload = {
            "id": 99,
            "dipendente_id": 15,
            "utente": {"email": "utente@test.local"},
        }
        self.run_log = AutomationRunLog.objects.create(
            rule=self.rule,
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS,
            payload_json=self.payload,
        )

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_email_renders_templates_and_uses_default_from_email(self, mock_email_class):
        email_message = MagicMock()
        email_message.send.return_value = 1
        mock_email_class.return_value = email_message
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.SEND_EMAIL,
            config_json={
                "to": "capo@test.local, hr@test.local",
                "cc": ["audit@test.local"],
                "reply_to": ["reply@test.local"],
                "subject_template": "Assenza #{id}",
                "body_text_template": "Richiesta {id} per dipendente {dipendente_id}",
                "body_html_template": "<p>Richiesta {id}</p>",
            },
        )

        result = execute_action(action, self.payload, run_log=self.run_log)

        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        mock_email_class.assert_called_once_with(
            subject="Assenza #99",
            body="Richiesta 99 per dipendente 15",
            from_email="noreply@test.local",
            to=["capo@test.local", "hr@test.local"],
            cc=["audit@test.local"],
            bcc=[],
            reply_to=["reply@test.local"],
        )
        email_message.attach_alternative.assert_called_once_with("<p>Richiesta 99</p>", "text/html")
        email_message.send.assert_called_once_with(fail_silently=False)

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_email_accepts_recipient_lists(self, mock_email_class):
        email_message = MagicMock()
        email_message.send.return_value = 1
        mock_email_class.return_value = email_message
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.SEND_EMAIL,
            config_json={
                "from_email": "sender@test.local",
                "to": ["{utente.email}", "capo@test.local"],
                "subject_template": "Test {id}",
                "body_text_template": "Body {id}",
            },
        )

        result = execute_action(action, self.payload, run_log=self.run_log)

        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        mock_email_class.assert_called_once()
        kwargs = mock_email_class.call_args.kwargs
        self.assertEqual(kwargs["to"], ["utente@test.local", "capo@test.local"])
        self.assertEqual(kwargs["from_email"], "sender@test.local")

    def test_send_email_with_invalid_recipient_returns_controlled_error(self):
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.SEND_EMAIL,
            config_json={
                "to": "not-an-email",
                "subject_template": "Test",
                "body_text_template": "Body",
            },
        )

        result = execute_action(action, self.payload, run_log=self.run_log)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("Indirizzo email non valido", result["result_message"])


@override_settings(DEFAULT_FROM_EMAIL="noreply@test.local", SITE_URL="https://hub.test.local")
class AutomationApprovalExecutorTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="approval-runtime",
            name="Approval runtime",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        self.payload = {
            "id": 77,
            "capo_email": "manager@test.local",
            "dipendente_email": "employee@test.local",
            "dipendente_nome": "Mario Rossi",
            "tipo_assenza": "Ferie",
            "data_inizio": "2026-04-20",
            "data_fine": "2026-04-22",
        }
        self.old_payload = {**self.payload, "tipo_assenza": "Permesso"}

    def _create_flow_endpoint(self, suffix: str = "default") -> AutomationDeliveryEndpoint:
        return AutomationDeliveryEndpoint.objects.create(
            code=f"teams-flow-{suffix}",
            name=f"Teams Flow {suffix}",
            endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
            endpoint_url=f"https://flow.example.com/{suffix}",
        )

    def _create_send_approval_action(self, **config_overrides) -> AutomationAction:
        config = {
            "delivery_mode": ApprovalDeliveryMode.EMAIL,
            "to_template": "{capo_email}",
            "subject_template": "Approvazione richiesta #{id}",
            "message_template": "Richiesta {tipo_assenza} per {dipendente_nome}",
            "expiry_days": 3,
            "approve_label": "Approva",
            "reject_label": "Rifiuta",
            "approved_actions": [],
            "rejected_actions": [],
        }
        config.update(config_overrides)
        return AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.SEND_APPROVAL,
            config_json=config,
        )

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_approval_email_sets_waiting_status(self, mock_email_class):
        email_message = MagicMock()
        email_message.send.return_value = 1
        mock_email_class.return_value = email_message
        self._create_send_approval_action()

        run_log = run_rule(self.rule, self.payload, old_payload=self.old_payload)

        approval = AutomationApproval.objects.get()
        self.assertEqual(run_log.status, AutomationRunLogStatus.WAITING_APPROVAL)
        self.assertEqual(approval.approver_emails, ["manager@test.local"])
        self.assertIn("Email approvazione inviata a manager@test.local.", run_log.result_message)
        kwargs = mock_email_class.call_args.kwargs
        self.assertEqual(kwargs["to"], ["manager@test.local"])
        self.assertEqual(kwargs["subject"], "Approvazione richiesta #77")

    def test_send_approval_with_unresolved_recipient_placeholder_returns_clear_error(self):
        self._create_send_approval_action()

        payload = dict(self.payload)
        payload.pop("capo_email", None)

        run_log = run_rule(self.rule, payload, old_payload=self.old_payload)

        self.assertEqual(run_log.status, AutomationRunLogStatus.ERROR)
        self.assertEqual(AutomationApproval.objects.count(), 0)
        action_log = run_log.action_logs.first()
        self.assertEqual(action_log.status, AutomationActionLogStatus.ERROR)
        self.assertIn("Placeholder non risolto in to_template: {capo_email}.", action_log.result_message)

    @patch("automazioni.services.requests.post")
    def test_send_approval_teams_chat_flow_posts_payload(self, mock_post):
        endpoint = self._create_flow_endpoint("chat")
        response = MagicMock()
        response.ok = True
        response.status_code = 202
        mock_post.return_value = response
        self._create_send_approval_action(
            delivery_mode=ApprovalDeliveryMode.TEAMS_CHAT_FLOW,
            to_template="",
            teams_flow_endpoint_id=str(endpoint.pk),
            teams_recipient_email_template="{capo_email}",
            teams_title_template="Teams approval #{id}",
            teams_facts_inline="Richiesta | {tipo_assenza}\nDipendente | {dipendente_nome}",
        )

        run_log = run_rule(self.rule, self.payload, old_payload=self.old_payload)

        approval = AutomationApproval.objects.get()
        self.assertEqual(run_log.status, AutomationRunLogStatus.WAITING_APPROVAL)
        self.assertEqual(mock_post.call_args.args[0], endpoint.endpoint_url)
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 10)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["approval_id"], approval.pk)
        self.assertEqual(payload["token"], str(approval.token))
        self.assertEqual(payload["recipient_email"], "manager@test.local")
        self.assertEqual(payload["subject"], "Teams approval #77")
        self.assertEqual(payload["message"], "Richiesta Ferie per Mario Rossi")
        self.assertTrue(payload["approve_url"].endswith(f"/automazioni/approvazione/{approval.token}/approva/"))
        self.assertTrue(payload["reject_url"].endswith(f"/automazioni/approvazione/{approval.token}/rifiuta/"))
        self.assertTrue(payload["expires_at"].endswith("Z"))
        self.assertEqual(payload["facts"][0]["value"], "Ferie")
        self.assertIn("Teams chat flow inviato a manager@test.local (HTTP 202).", run_log.result_message)

    @patch("automazioni.services.requests.post")
    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_approval_email_and_teams_chat_flow_accumulates_result_message(
        self,
        mock_email_class,
        mock_post,
    ):
        endpoint = self._create_flow_endpoint("combo")
        email_message = MagicMock()
        email_message.send.return_value = 1
        mock_email_class.return_value = email_message
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        mock_post.return_value = response
        self._create_send_approval_action(
            delivery_mode=ApprovalDeliveryMode.EMAIL_AND_TEAMS_CHAT_FLOW,
            teams_flow_endpoint_id=str(endpoint.pk),
            teams_recipient_email_template="{dipendente_email}",
        )

        run_log = run_rule(self.rule, self.payload, old_payload=self.old_payload)

        approval = AutomationApproval.objects.get()
        self.assertEqual(run_log.status, AutomationRunLogStatus.WAITING_APPROVAL)
        self.assertEqual(
            approval.approver_emails,
            ["manager@test.local", "employee@test.local"],
        )
        self.assertIn("Richiesta approvazione creata per manager@test.local, employee@test.local.", run_log.result_message)
        self.assertIn("Email approvazione inviata a manager@test.local.", run_log.result_message)
        self.assertIn("Teams chat flow inviato a employee@test.local (HTTP 200).", run_log.result_message)

    @patch("automazioni.services.requests.post")
    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_approval_email_and_teams_chat_flow_warns_on_flow_failure_by_default(
        self,
        mock_email_class,
        mock_post,
    ):
        endpoint = self._create_flow_endpoint("warn")
        email_message = MagicMock()
        email_message.send.return_value = 1
        mock_email_class.return_value = email_message
        response = MagicMock()
        response.ok = False
        response.status_code = 500
        mock_post.return_value = response
        self._create_send_approval_action(
            delivery_mode=ApprovalDeliveryMode.EMAIL_AND_TEAMS_CHAT_FLOW,
            teams_flow_endpoint_id=str(endpoint.pk),
            teams_recipient_email_template="{dipendente_email}",
        )

        run_log = run_rule(self.rule, self.payload, old_payload=self.old_payload)

        self.assertEqual(run_log.status, AutomationRunLogStatus.WAITING_APPROVAL)
        self.assertEqual(AutomationApproval.objects.count(), 1)
        self.assertIn("Email approvazione inviata a manager@test.local.", run_log.result_message)
        self.assertIn("Teams chat flow non inviato (Teams chat flow ha risposto con HTTP 500.).", run_log.result_message)

    @patch("automazioni.services.requests.post")
    def test_send_approval_teams_chat_flow_returns_error_when_flow_fails(self, mock_post):
        endpoint = self._create_flow_endpoint("fail")
        response = MagicMock()
        response.ok = False
        response.status_code = 500
        mock_post.return_value = response
        self._create_send_approval_action(
            delivery_mode=ApprovalDeliveryMode.TEAMS_CHAT_FLOW,
            to_template="",
            teams_flow_endpoint_id=str(endpoint.pk),
            teams_recipient_email_template="{capo_email}",
        )

        run_log = run_rule(self.rule, self.payload, old_payload=self.old_payload)

        self.assertEqual(run_log.status, AutomationRunLogStatus.ERROR)
        self.assertEqual(AutomationApproval.objects.count(), 0)
        self.assertEqual(run_log.action_logs.first().status, AutomationActionLogStatus.ERROR)

    @patch("automazioni.services.get_teams_flow_endpoint_by_id", return_value=(None, True))
    def test_send_approval_teams_chat_flow_returns_clear_error_when_endpoint_table_is_unavailable(
        self,
        _mock_get_endpoint,
    ):
        self._create_send_approval_action(
            delivery_mode=ApprovalDeliveryMode.TEAMS_CHAT_FLOW,
            to_template="",
            teams_flow_endpoint_id="123",
            teams_recipient_email_template="{capo_email}",
        )

        run_log = run_rule(self.rule, self.payload, old_payload=self.old_payload)

        self.assertEqual(run_log.status, AutomationRunLogStatus.ERROR)
        self.assertEqual(AutomationApproval.objects.count(), 0)
        action_log = run_log.action_logs.first()
        self.assertEqual(action_log.status, AutomationActionLogStatus.ERROR)
        self.assertIn(AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE, action_log.result_message)

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_process_approval_decision_runs_approved_branch(self, mock_email_class):
        email_message = MagicMock()
        email_message.send.return_value = 1
        mock_email_class.return_value = email_message
        self._create_send_approval_action(
            approved_actions=[
                {
                    "action_type": AutomationActionType.WRITE_LOG,
                    "description": "Log approvato",
                    "config_json": {"message_template": "approved {id}"},
                }
            ],
        )

        run_log = run_rule(self.rule, self.payload, old_payload=self.old_payload)
        approval = AutomationApproval.objects.get()
        result = process_approval_decision(str(approval.token), "approved", decided_by_email="boss@test.local")

        approval.refresh_from_db()
        run_log.refresh_from_db()
        self.assertTrue(result["ok"])
        self.assertEqual(result["actions_run"], 1)
        self.assertEqual(approval.status, AutomationApproval.Status.APPROVED)
        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertIn("Approvazione ricevuta: approved", run_log.result_message)
        self.assertTrue(run_log.action_logs.filter(result_message="approved 77").exists())

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_process_approval_decision_runs_rejected_branch(self, mock_email_class):
        email_message = MagicMock()
        email_message.send.return_value = 1
        mock_email_class.return_value = email_message
        self._create_send_approval_action(
            rejected_actions=[
                {
                    "action_type": AutomationActionType.WRITE_LOG,
                    "description": "Log rifiutato",
                    "config_json": {"message_template": "rejected {id}"},
                }
            ],
        )

        run_log = run_rule(self.rule, self.payload, old_payload=self.old_payload)
        approval = AutomationApproval.objects.get()
        result = process_approval_decision(str(approval.token), "rejected", decided_by_email="boss@test.local")

        approval.refresh_from_db()
        run_log.refresh_from_db()
        self.assertTrue(result["ok"])
        self.assertEqual(result["actions_run"], 1)
        self.assertEqual(approval.status, AutomationApproval.Status.REJECTED)
        self.assertEqual(run_log.status, AutomationRunLogStatus.SKIPPED)
        self.assertTrue(run_log.action_logs.filter(result_message="rejected 77").exists())

class AutomationActionFormExtendedTests(TestCase):
    def test_target_table_choices_include_module_tables_but_mark_unconfigured_ones(self):
        form = AutomationActionForm(source_code="assenze")

        insert_choices = dict(form.fields["insert_target_table"].choices)
        update_choices = dict(form.fields["update_target_table"].choices)

        self.assertIn("tasks_project", insert_choices)
        self.assertIn("tasks_project", update_choices)
        self.assertIn("[da abilitare]", insert_choices["tasks_project"])
        self.assertIn("[da abilitare]", update_choices["tasks_project"])
        self.assertNotIn("[da abilitare]", insert_choices["core_notifica"])

    def test_insert_record_form_rejects_module_table_not_yet_enabled(self):
        form = AutomationActionForm(
            data={
                "order": "1",
                "action_type": AutomationActionType.INSERT_RECORD,
                "is_enabled": "on",
                "description": "Inserisce progetto",
                "insert_target_table": "tasks_project",
                "insert_field_mappings_text": "name = Progetto {id}",
            },
            source_code="assenze",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("insert_target_table", form.errors)
        self.assertIn("non e' ancora abilitata", form.errors["insert_target_table"][0])

    def test_update_trigger_record_form_accepts_source_fields_and_run_if(self):
        form = AutomationActionForm(
            data={
                "order": "1",
                "action_type": AutomationActionType.UPDATE_TRIGGER_RECORD,
                "is_enabled": "on",
                "description": "Aggiorna record triggerante",
                "trigger_update_fields_text": "status = DONE\nnext_step_text = Sollecito {id}",
                "run_if_field_name": "status",
                "run_if_operator": AutomationConditionOperator.CHANGED,
                "run_if_expected_value": "",
                "run_if_value_type": AutomationConditionValueType.STRING,
                "run_if_compare_with_old": "on",
                "run_if_negate": "",
            },
            source_code="tasks",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form._config_json["update_fields"],
            {"status": "DONE", "next_step_text": "Sollecito {id}"},
        )
        self.assertEqual(form._config_json["run_if"]["field_name"], "status")
        self.assertEqual(form._config_json["run_if"]["operator"], AutomationConditionOperator.CHANGED)
        self.assertTrue(form._config_json["run_if"]["compare_with_old"])

    def test_update_trigger_record_form_rejects_invalid_source_field(self):
        form = AutomationActionForm(
            data={
                "order": "1",
                "action_type": AutomationActionType.UPDATE_TRIGGER_RECORD,
                "is_enabled": "on",
                "description": "Aggiorna record triggerante",
                "trigger_update_fields_text": "campo_inesistente = X",
            },
            source_code="tasks",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("trigger_update_fields_text", form.errors)

    def test_send_approval_form_requires_teams_recipient_email_for_chat_flow(self):
        endpoint = AutomationDeliveryEndpoint.objects.create(
            code="teams-flow-form-recipient",
            name="Teams Flow Form Recipient",
            endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
            endpoint_url="https://flow.example.com/hook",
        )
        form = AutomationActionForm(
            data={
                "order": "1",
                "action_type": AutomationActionType.SEND_APPROVAL,
                "description": "Approvazione Teams",
                "approval_delivery_mode": ApprovalDeliveryMode.TEAMS_CHAT_FLOW,
                "approval_subject_template": "Approval {id}",
                "approval_message_template": "Body {id}",
                "approval_teams_flow_endpoint_id": str(endpoint.pk),
            },
            source_code="assenze",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("approval_teams_recipient_email_template", form.errors)

    def test_send_approval_form_requires_flow_endpoint_for_chat_flow(self):
        form = AutomationActionForm(
            data={
                "order": "1",
                "action_type": AutomationActionType.SEND_APPROVAL,
                "description": "Approvazione Teams",
                "approval_delivery_mode": ApprovalDeliveryMode.TEAMS_CHAT_FLOW,
                "approval_subject_template": "Approval {id}",
                "approval_message_template": "Body {id}",
                "approval_teams_recipient_email_template": "{capo_email}",
            },
            source_code="assenze",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("approval_teams_flow_endpoint_id", form.errors)

    @patch("automazioni.forms.list_teams_flow_endpoints", return_value=([], True))
    def test_send_approval_form_warns_when_flow_endpoint_table_is_unavailable(self, _mock_list_endpoints):
        form = AutomationActionForm(
            data={
                "order": "1",
                "action_type": AutomationActionType.SEND_APPROVAL,
                "description": "Approvazione Teams",
                "approval_delivery_mode": ApprovalDeliveryMode.TEAMS_CHAT_FLOW,
                "approval_subject_template": "Approval {id}",
                "approval_message_template": "Body {id}",
                "approval_teams_recipient_email_template": "{capo_email}",
            },
            source_code="assenze",
        )

        self.assertFalse(form.is_valid())
        self.assertIn("approval_teams_flow_endpoint_id", form.errors)
        self.assertIn(
            AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
            form.errors["approval_teams_flow_endpoint_id"],
        )
        self.assertIn(
            AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
            str(form.fields["approval_teams_flow_endpoint_id"].help_text),
        )

    def test_send_approval_form_prefills_template_selector_from_saved_code(self):
        from .models import ApprovalEmailTemplate

        template = ApprovalEmailTemplate.objects.create(
            code="tpl-approval-form-code",
            name="Template Approval Form",
            delivery_mode="hybrid",
            subject_template="Subject {id}",
        )
        rule = AutomationRule.objects.create(
            code="form-template-prefill",
            name="Form template prefill",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.INSERT,
            trigger_scope=AutomationRuleTriggerScope.ALL_INSERTS,
        )
        action = AutomationAction(
            rule=rule,
            action_type=AutomationActionType.SEND_APPROVAL,
            config_json={
                "delivery_mode": ApprovalDeliveryMode.EMAIL,
                "to_template": "{capo_email}",
                "subject_template": "Approval {id}",
                "message_template": "Body {id}",
                "approval_email_template_code": template.code,
            },
        )

        form = AutomationActionForm(instance=action, source_code="assenze")

        self.assertEqual(form.initial["approval_email_template_id"], str(template.pk))

    def test_send_approval_form_persists_template_code_when_selected(self):
        from .models import ApprovalEmailTemplate

        template = ApprovalEmailTemplate.objects.create(
            code="tpl-approval-form-save",
            name="Template Approval Save",
            delivery_mode="mail_reply",
            subject_template="Subject {id}",
        )
        form = AutomationActionForm(
            data={
                "order": "1",
                "action_type": AutomationActionType.SEND_APPROVAL,
                "description": "Approvazione mail",
                "approval_delivery_mode": ApprovalDeliveryMode.EMAIL,
                "approval_to_template": "{capo_email}",
                "approval_subject_template": "Approval {id}",
                "approval_message_template": "Body {id}",
                "approval_email_template_id": str(template.pk),
            },
            source_code="assenze",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._config_json["approval_email_template_code"], template.code)
        self.assertEqual(form._config_json["approval_email_template_id"], str(template.pk))

    def test_branch_form_serializes_true_and_false_actions(self):
        true_actions = [
            {
                "action_type": AutomationActionType.WRITE_LOG,
                "description": "Log OK",
                "config_json": {"message_template": "Ramo true"},
            }
        ]
        false_actions = [
            {
                "action_type": AutomationActionType.SEND_EMAIL,
                "description": "Avvisa",
                "config_json": {"to": "{owner_email}", "subject_template": "KO", "body_text_template": "No"},
            }
        ]
        form = AutomationActionForm(
            data={
                "order": "1",
                "action_type": AutomationActionType.BRANCH,
                "description": "Branch decisionale",
                "branch_condition_field": "status",
                "branch_condition_operator": AutomationConditionOperator.EQUALS,
                "branch_condition_value": "DONE",
                "branch_condition_value_type": AutomationConditionValueType.STRING,
                "branch_compare_with_old": "on",
                "branch_if_true_actions_json": json.dumps(true_actions),
                "branch_if_false_actions_json": json.dumps(false_actions),
            },
            source_code="tasks",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._config_json["condition_field"], "status")
        self.assertEqual(form._config_json["condition_operator"], AutomationConditionOperator.EQUALS)
        self.assertTrue(form._config_json["compare_with_old"])
        self.assertEqual(form._config_json["if_true_actions"], true_actions)
        self.assertEqual(form._config_json["if_false_actions"], false_actions)

    def test_do_until_form_serializes_loop_configuration(self):
        loop_actions = [
            {
                "action_type": AutomationActionType.WRITE_LOG,
                "description": "Reminder loop",
                "config_json": {"message_template": "Ancora in attesa"},
            }
        ]
        success_actions = [
            {
                "action_type": AutomationActionType.UPDATE_TRIGGER_RECORD,
                "description": "Chiudi loop",
                "config_json": {"update_fields": {"status": "DONE"}},
            }
        ]
        timeout_actions = [
            {
                "action_type": AutomationActionType.SEND_EMAIL,
                "description": "Escalation",
                "config_json": {"to": "{owner_email}", "subject_template": "Timeout", "body_text_template": "KO"},
            }
        ]
        form = AutomationActionForm(
            data={
                "order": "2",
                "action_type": AutomationActionType.DO_UNTIL,
                "description": "Attendi chiusura",
                "loop_check_field": "status",
                "loop_check_operator": AutomationConditionOperator.EQUALS,
                "loop_check_value": "DONE",
                "loop_check_value_type": AutomationConditionValueType.STRING,
                "loop_retry_delay_value": "6",
                "loop_retry_delay_unit": "hours",
                "loop_max_iterations": "8",
                "loop_loop_actions_json": json.dumps(loop_actions),
                "loop_on_success_actions_json": json.dumps(success_actions),
                "loop_on_timeout_actions_json": json.dumps(timeout_actions),
            },
            source_code="tasks",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._config_json["check_field"], "status")
        self.assertEqual(form._config_json["check_operator"], AutomationConditionOperator.EQUALS)
        self.assertEqual(form._config_json["retry_delay_value"], 6)
        self.assertEqual(form._config_json["retry_delay_unit"], "hours")
        self.assertEqual(form._config_json["max_iterations"], 8)
        self.assertEqual(form._config_json["loop_actions"], loop_actions)
        self.assertEqual(form._config_json["on_success_actions"], success_actions)
        self.assertEqual(form._config_json["on_timeout_actions"], timeout_actions)

    def test_for_each_form_serializes_source_and_actions(self):
        each_actions = [
            {
                "action_type": AutomationActionType.WRITE_LOG,
                "description": "Traccia record",
                "config_json": {"message_template": "Record correlato {id}"},
            }
        ]
        form = AutomationActionForm(
            data={
                "order": "3",
                "action_type": AutomationActionType.FOR_EACH,
                "description": "Itera correlati",
                "each_source_code": "tasks",
                "each_filter_field": "status",
                "each_filter_value_template": "TODO",
                "each_max_items": "25",
                "each_actions_json": json.dumps(each_actions),
            },
            source_code="tasks",
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._config_json["source_code"], "tasks")
        self.assertEqual(form._config_json["filter_field"], "status")
        self.assertEqual(form._config_json["filter_value_template"], "TODO")
        self.assertEqual(form._config_json["max_items"], 25)
        self.assertEqual(form._config_json["each_actions"], each_actions)


class AutomationExtendedActionExecutorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="extended-action-user", password="pass12345")
        self.rule = AutomationRule.objects.create(
            code="extended-actions-rule",
            name="Extended actions rule",
            source_code="tasks",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        self.task = Task.objects.create(
            title="Task runtime",
            status="TODO",
            priority="MEDIUM",
            next_step_text="In attesa",
            created_by=self.user,
            assigned_to=self.user,
        )
        self.payload = {
            "id": self.task.id,
            "title": self.task.title,
            "status": self.task.status,
            "priority": self.task.priority,
            "next_step_text": self.task.next_step_text,
            "assigned_to_id": self.task.assigned_to_id,
            "created_by_id": self.task.created_by_id,
        }
        self.old_payload = {**self.payload, "status": "OPEN"}
        self.run_log = AutomationRunLog.objects.create(
            rule=self.rule,
            source_code="tasks",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS,
            payload_json=self.payload,
            old_payload_json=self.old_payload,
        )

    def test_execute_action_skips_when_run_if_is_not_satisfied(self):
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            config_json={
                "message_template": "Non dovrei partire",
                "run_if": {
                    "field_name": "status",
                    "operator": AutomationConditionOperator.EQUALS,
                    "expected_value": "DONE",
                    "value_type": AutomationConditionValueType.STRING,
                    "compare_with_old": False,
                    "negate": False,
                },
            },
        )

        result = execute_action(action, self.payload, old_payload=self.old_payload, run_log=self.run_log)

        self.assertEqual(result["status"], AutomationActionLogStatus.SKIPPED)
        self.assertIn("branch non soddisfatto", result["result_message"])
        self.assertEqual(self.run_log.action_logs.count(), 1)
        self.assertEqual(self.run_log.action_logs.first().status, AutomationActionLogStatus.SKIPPED)

    def test_update_trigger_record_updates_current_source_row(self):
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.UPDATE_TRIGGER_RECORD,
            config_json={
                "update_fields": {
                    "status": "DONE",
                    "next_step_text": "Sollecito task {id}",
                }
            },
        )

        result = execute_action(
            action,
            self.payload,
            old_payload=self.old_payload,
            run_log=self.run_log,
            queue_event={"source_code": "tasks", "source_table": "tasks_task", "source_pk": str(self.task.id), "operation_type": "update"},
        )

        self.task.refresh_from_db()

        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        self.assertEqual(self.task.status, "DONE")
        self.assertEqual(self.task.next_step_text, f"Sollecito task {self.task.id}")

    @patch("automazioni.services.requests.request")
    def test_http_request_executes_and_checks_expected_status(self, mock_request):
        response = MagicMock()
        response.status_code = 201
        response.ok = True
        response.text = "created"
        mock_request.return_value = response
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.HTTP_REQUEST,
            config_json={
                "method": "POST",
                "url_template": "https://example.local/hooks/tasks/{id}",
                "headers": {"Content-Type": "application/json", "X-Test": "task-{id}"},
                "body_template": "{\"id\":\"{id}\",\"status\":\"{status}\"}",
                "timeout_seconds": 15,
                "expected_statuses": [200, 201],
            },
        )

        result = execute_action(action, self.payload, old_payload=self.old_payload, run_log=self.run_log)

        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        kwargs = mock_request.call_args.kwargs
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["url"], f"https://example.local/hooks/tasks/{self.task.id}")
        self.assertEqual(kwargs["headers"]["X-Test"], f"task-{self.task.id}")
        self.assertEqual(kwargs["json"], {"id": str(self.task.id), "status": self.task.status})

    @patch("automazioni.services.requests.request")
    def test_teams_webhook_posts_message_card(self, mock_request):
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.text = "1"
        mock_request.return_value = response
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.TEAMS_WEBHOOK,
            config_json={
                "webhook_url": "https://outlook.office.com/webhook/demo",
                "title_template": "Task {id}",
                "summary_template": "Aggiornamento task",
                "text_template": "Stato: {status}",
                "theme_color": "00AA55",
                "facts": {"ID": "{id}", "Priorita": "{priority}"},
            },
        )

        result = execute_action(action, self.payload, old_payload=self.old_payload, run_log=self.run_log)

        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        kwargs = mock_request.call_args.kwargs
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["url"], "https://outlook.office.com/webhook/demo")
        self.assertEqual(kwargs["json"]["title"], f"Task {self.task.id}")
        self.assertEqual(kwargs["json"]["themeColor"], "00AA55")
        self.assertEqual(kwargs["json"]["sections"][0]["facts"][0]["value"], str(self.task.id))

    @patch("automazioni.services._schedule_queue_event")
    def test_delay_schedule_relative_uses_new_units(self, mock_schedule):
        action = AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.DELAY_SCHEDULE,
            config_json={
                "mode": "relative",
                "value_template": "2",
                "unit": "hours",
            },
        )

        before = timezone.now()
        result = execute_action(
            action,
            self.payload,
            old_payload=self.old_payload,
            run_log=self.run_log,
            queue_event={"source_code": "tasks", "source_table": "tasks_task", "source_pk": str(self.task.id), "operation_type": "update"},
        )

        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        self.assertTrue(mock_schedule.called)
        execute_after = mock_schedule.call_args.kwargs["execute_after"]
        self.assertGreater(execute_after, before + timedelta(hours=1, minutes=50))
        self.assertLess(execute_after, before + timedelta(hours=2, minutes=10))


class AutomationDatabaseExecutorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="db-executor-user", password="pass12345")
        self.payload = {
            "id": 42,
            "capo_reparto_id": 7,
            "moderation_status": 1,
            "task_id": 14,
        }

    def _mock_cursor(self, rowcount=1, lastrowid=55):
        cursor = MagicMock()
        cursor.rowcount = rowcount
        cursor.lastrowid = lastrowid
        context_manager = MagicMock()
        context_manager.__enter__.return_value = cursor
        context_manager.__exit__.return_value = False
        return cursor, context_manager

    def test_insert_record_rejects_non_whitelisted_table(self):
        action = SimpleNamespace(
            action_type=AutomationActionType.INSERT_RECORD,
            config_json={"target_table": "dbo.assenze", "field_mappings": {"messaggio": "Test"}},
        )

        with patch("automazioni.services._create_action_log", return_value=None):
            result = execute_action(action, self.payload, run_log=None)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("Tabella target non whitelistata", result["result_message"])

    def test_insert_record_rejects_non_whitelisted_column(self):
        action = SimpleNamespace(
            action_type=AutomationActionType.INSERT_RECORD,
            config_json={"target_table": "core_notifica", "field_mappings": {"hack_field": "Test"}},
        )

        with patch("automazioni.services._create_action_log", return_value=None):
            result = execute_action(action, self.payload, run_log=None)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("Colonne non whitelistate", result["result_message"])

    def test_execute_safe_insert_uses_parameterized_query(self):
        cursor, context_manager = self._mock_cursor(lastrowid=321)
        atomic_manager = MagicMock()
        atomic_manager.__enter__.return_value = None
        atomic_manager.__exit__.return_value = False
        with patch("automazioni.services.connection.cursor", return_value=context_manager), patch(
            "automazioni.services.transaction.atomic",
            return_value=atomic_manager,
        ), patch(
            "automazioni.services.get_action_table_whitelist",
            return_value={
                AutomationActionType.INSERT_RECORD: {
                    "core_notifica": {
                        "fields": {"legacy_user_id", "tipo", "messaggio", "url_azione"},
                        "where_fields": set(),
                    }
                },
                AutomationActionType.UPDATE_RECORD: {},
            },
        ):
            result = execute_safe_insert(
                "core_notifica",
                {
                    "legacy_user_id": "7",
                    "tipo": "generico",
                    "messaggio": "Nuova assenza #42",
                    "url_azione": "/assenze/42/",
                },
            )

        self.assertEqual(result["inserted_pk"], 321)
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO", sql)
        self.assertIn("%s", sql)
        self.assertEqual(params, ["7", "generico", "Nuova assenza #42", "/assenze/42/"])

    def test_update_record_rejects_non_whitelisted_table(self):
        action = SimpleNamespace(
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "dbo.assenze",
                "where_field": "id",
                "where_value_template": "{id}",
                "update_fields": {"status": "DONE"},
            },
        )

        with patch("automazioni.services._create_action_log", return_value=None):
            result = execute_action(action, self.payload, run_log=None)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("Tabella target non whitelistata", result["result_message"])

    def test_update_record_allowed_on_whitelisted_table_and_field(self):
        task = Task.objects.create(
            title="Safety allowed task",
            status="TODO",
            priority="MEDIUM",
            next_step_text="Prima",
            created_by=self.user,
        )
        action = SimpleNamespace(
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "id",
                "where_value_template": "{task_id}",
                "update_fields": {"status": "DONE", "next_step_text": "Aggiornato {id}"},
            },
            pk=None,
            rule=None,
        )

        result = execute_action(action, {"id": 42, "task_id": task.id}, run_log=None)
        task.refresh_from_db()

        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        self.assertEqual(task.status, "DONE")
        self.assertEqual(task.next_step_text, "Aggiornato 42")

    def test_update_record_rejects_non_whitelisted_where_field(self):
        action = SimpleNamespace(
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "title",
                "where_value_template": "{id}",
                "update_fields": {"status": "DONE"},
            },
        )

        with patch("automazioni.services._create_action_log", return_value=None):
            result = execute_action(action, self.payload, run_log=None)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("Campo where non whitelistato", result["result_message"])

    def test_update_record_rejects_non_whitelisted_update_field(self):
        action = SimpleNamespace(
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "id",
                "where_value_template": "{id}",
                "update_fields": {"title": "Non consentito"},
            },
        )

        with patch("automazioni.services._create_action_log", return_value=None):
            result = execute_action(action, self.payload, run_log=None)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("Colonne non whitelistate", result["result_message"])

    def test_update_record_rejects_missing_where_value(self):
        action = SimpleNamespace(
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "id",
                "where_value_template": "{missing}",
                "update_fields": {"status": "DONE"},
            },
        )

        with patch("automazioni.services._create_action_log", return_value=None):
            result = execute_action(action, self.payload, run_log=None)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("where_value_template non produce un valore valido", result["result_message"])

    def test_update_record_rejects_empty_update_fields(self):
        action = SimpleNamespace(
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "id",
                "where_value_template": "{task_id}",
                "update_fields": {},
            },
        )

        with patch("automazioni.services._create_action_log", return_value=None):
            result = execute_action(action, self.payload, run_log=None)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("update_fields non vuoto", result["result_message"])

    def test_execute_safe_update_uses_parameterized_query(self):
        cursor, context_manager = self._mock_cursor(rowcount=2, lastrowid=None)
        atomic_manager = MagicMock()
        atomic_manager.__enter__.return_value = None
        atomic_manager.__exit__.return_value = False
        with patch("automazioni.services.connection.cursor", return_value=context_manager), patch(
            "automazioni.services.transaction.atomic",
            return_value=atomic_manager,
        ), patch(
            "automazioni.services.get_action_table_whitelist",
            return_value={
                AutomationActionType.INSERT_RECORD: {},
                AutomationActionType.UPDATE_RECORD: {
                    "tasks_task": {
                        "fields": {"status", "next_step_text"},
                        "where_fields": {"id"},
                    }
                },
            },
        ):
            result = execute_safe_update(
                "tasks_task",
                {
                    "status": "DONE",
                    "next_step_text": "Aggiornato da automazione #42'; DROP TABLE tasks_task; --",
                },
                "id",
                "14 OR 1=1",
            )

        self.assertEqual(result["rowcount"], 2)
        sql, params = cursor.execute.call_args.args
        self.assertIn("UPDATE", sql)
        self.assertIn("WHERE", sql)
        self.assertIn("%s", sql)
        self.assertNotIn("DROP TABLE", sql)
        self.assertNotIn("14 OR 1=1", sql)
        self.assertEqual(params, ["DONE", "Aggiornato da automazione #42'; DROP TABLE tasks_task; --", "14 OR 1=1"])

    def test_safety_error_is_recorded_as_action_log(self):
        rule = AutomationRule.objects.create(
            code="safety-log-rule",
            name="Safety log rule",
            source_code="tasks",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "id",
                "where_value_template": "{task_id}",
                "update_fields": {"title": "Bloccato"},
            },
        )
        run_log = AutomationRunLog.objects.create(
            rule=rule,
            source_code="tasks",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS,
            payload_json={"task_id": 1},
        )

        with self.assertLogs("automazioni.services", level="WARNING") as logs:
            result = execute_action(action, {"task_id": 1}, run_log=run_log)

        self.assertEqual(result["status"], AutomationActionLogStatus.ERROR)
        action_log = run_log.action_logs.get()
        self.assertEqual(action_log.status, AutomationActionLogStatus.ERROR)
        self.assertIn("Safety guardrail", action_log.result_message)
        self.assertIn(f"action_id={action.id}", "\n".join(logs.output))


class AutomationRunRuleExecutorIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="executor-user", password="pass12345")
        self.payload = {"id": 5, "capo_reparto_id": 8, "task_id": 77}

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_run_rule_with_write_log_and_send_email(self, mock_email_class):
        email_message = MagicMock()
        email_message.send.return_value = 1
        mock_email_class.return_value = email_message
        rule = AutomationRule.objects.create(
            code="integration-email",
            name="Integration email",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.WRITE_LOG,
            config_json={"message_template": "Start #{id}"},
        )
        AutomationAction.objects.create(
            rule=rule,
            order=2,
            action_type=AutomationActionType.SEND_EMAIL,
            config_json={
                "to": "dest@test.local",
                "from_email": "sender@test.local",
                "subject_template": "Subject #{id}",
                "body_text_template": "Body {id}",
            },
        )

        run_log = run_rule(rule, self.payload, initiated_by=self.user)

        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(run_log.action_logs.count(), 2)

    @patch("automazioni.services.execute_safe_insert")
    def test_run_rule_with_insert_record(self, mock_insert):
        mock_insert.return_value = {"rowcount": 1, "inserted_pk": 123}
        rule = AutomationRule.objects.create(
            code="integration-insert",
            name="Integration insert",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.INSERT_RECORD,
            config_json={
                "target_table": "core_notifica",
                "field_mappings": {
                    "legacy_user_id": "{capo_reparto_id}",
                    "tipo": "generico",
                    "messaggio": "Insert #{id}",
                },
            },
        )

        run_log = run_rule(rule, self.payload)

        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(run_log.action_logs.count(), 1)
        mock_insert.assert_called_once()

    @patch("automazioni.services.execute_safe_update")
    def test_run_rule_with_update_record(self, mock_update):
        mock_update.return_value = {"rowcount": 1}
        rule = AutomationRule.objects.create(
            code="integration-update",
            name="Integration update",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "id",
                "where_value_template": "{task_id}",
                "update_fields": {"status": "DONE"},
            },
        )

        run_log = run_rule(rule, self.payload)

        self.assertEqual(run_log.status, AutomationRunLogStatus.SUCCESS)
        self.assertEqual(run_log.action_logs.count(), 1)
        mock_update.assert_called_once()


class AutomationQueueMatchingTests(TestCase):
    def setUp(self):
        self.insert_rule = AutomationRule.objects.create(
            code="queue-insert",
            name="Queue insert",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.INSERT,
            trigger_scope=AutomationRuleTriggerScope.ALL_INSERTS,
            is_draft=False,
        )
        self.update_rule = AutomationRule.objects.create(
            code="queue-update-all",
            name="Queue update all",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_draft=False,
        )
        self.specific_rule = AutomationRule.objects.create(
            code="queue-update-specific",
            name="Queue update specific",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.SPECIFIC_FIELD,
            watched_field="moderation_status",
            is_draft=False,
        )

    def test_find_matching_rules_for_insert_all_inserts(self):
        rules = find_matching_rules(
            {
                "source_code": "assenze",
                "operation_type": "insert",
                "payload": {"id": 1},
                "old_payload": None,
            }
        )

        self.assertEqual([rule.code for rule in rules], ["queue-insert"])

    def test_find_matching_rules_for_update_all_updates(self):
        rules = find_matching_rules(
            {
                "source_code": "assenze",
                "operation_type": "update",
                "payload": {"id": 1, "moderation_status": 1},
                "old_payload": {"id": 1, "moderation_status": 1},
            }
        )

        self.assertIn("queue-update-all", [rule.code for rule in rules])

    def test_find_matching_rules_for_specific_field_changed(self):
        rules = find_matching_rules(
            {
                "source_code": "assenze",
                "operation_type": "update",
                "payload": {"id": 1, "moderation_status": 1},
                "old_payload": {"id": 1, "moderation_status": 0},
            }
        )

        self.assertIn("queue-update-specific", [rule.code for rule in rules])

    def test_find_matching_rules_for_specific_field_not_changed(self):
        rules = find_matching_rules(
            {
                "source_code": "assenze",
                "operation_type": "update",
                "payload": {"id": 1, "moderation_status": 1},
                "old_payload": {"id": 1, "moderation_status": 1},
            }
        )

        self.assertNotIn("queue-update-specific", [rule.code for rule in rules])


class AutomationQueueProcessorTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="queue-processor-rule",
            name="Queue processor rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_draft=False,
        )

    @patch("automazioni.services.mark_queue_done")
    @patch("automazioni.services.run_rule")
    def test_process_queue_event_marks_done_on_success(self, mock_run_rule, mock_mark_done):
        mock_run_rule.return_value = SimpleNamespace(status=AutomationRunLogStatus.SUCCESS)
        result = process_queue_event(
            {
                "id": 1,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": '{"id": 1, "moderation_status": 1}',
                "old_payload_json": '{"id": 1, "moderation_status": 0}',
            }
        )

        self.assertEqual(result["status"], "done")
        mock_mark_done.assert_called_once_with(1)
        mock_run_rule.assert_called_once()

    @patch("automazioni.services.mark_queue_error")
    def test_process_queue_event_marks_error_on_invalid_payload_json(self, mock_mark_error):
        result = process_queue_event(
            {
                "id": 2,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": "{invalid",
                "old_payload_json": None,
            }
        )

        self.assertEqual(result["status"], "error")
        mock_mark_error.assert_called_once()

    @patch("automazioni.services.mark_queue_done")
    @patch("automazioni.services.run_rule")
    def test_process_queue_event_keeps_done_when_rule_is_skipped(self, mock_run_rule, mock_mark_done):
        mock_run_rule.return_value = SimpleNamespace(status=AutomationRunLogStatus.SKIPPED)
        result = process_queue_event(
            {
                "id": 3,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": '{"id": 1, "moderation_status": 1}',
                "old_payload_json": '{"id": 1, "moderation_status": 0}',
            }
        )

        self.assertEqual(result["status"], "done")
        mock_mark_done.assert_called_once_with(3)

    @patch("automazioni.services._resolve_legacy_user_email", return_value="capo@example.com")
    @patch("automazioni.services.mark_queue_done")
    @patch("automazioni.services.run_rule")
    def test_process_queue_event_enriches_assenze_payload_with_capo_email(
        self,
        mock_run_rule,
        mock_mark_done,
        _mock_resolve_email,
    ):
        mock_run_rule.return_value = SimpleNamespace(status=AutomationRunLogStatus.SUCCESS)

        result = process_queue_event(
            {
                "id": 30,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": '{"id": 1, "capo_reparto_id": 12, "moderation_status": 1}',
                "old_payload_json": '{"id": 1, "capo_reparto_id": 12, "moderation_status": 0}',
            }
        )

        self.assertEqual(result["status"], "done")
        mock_mark_done.assert_called_once_with(30)
        payload = mock_run_rule.call_args.args[1]
        old_payload = mock_run_rule.call_args.kwargs["old_payload"]
        self.assertEqual(payload["capo_email"], "capo@example.com")
        self.assertEqual(old_payload["capo_email"], "capo@example.com")

    @patch("automazioni.services._resolve_caporeparto_email_from_local_id", return_value="capo-local@example.com")
    @patch("automazioni.services.mark_queue_done")
    @patch("automazioni.services.run_rule")
    def test_process_queue_event_enriches_assenze_payload_with_capo_email_from_local_caporeparto_id(
        self,
        mock_run_rule,
        mock_mark_done,
        _mock_resolve_local_email,
    ):
        mock_run_rule.return_value = SimpleNamespace(status=AutomationRunLogStatus.SUCCESS)

        result = process_queue_event(
            {
                "id": 32,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": '{"id": 4060, "capo_reparto_id": 7, "moderation_status": 2}',
                "old_payload_json": '{"id": 4060, "capo_reparto_id": 7, "moderation_status": 1}',
            }
        )

        self.assertEqual(result["status"], "done")
        mock_mark_done.assert_called_once_with(32)
        payload = mock_run_rule.call_args.args[1]
        self.assertEqual(payload["capo_email"], "capo-local@example.com")

    @patch(
        "automazioni.services._fetch_assenza_runtime_details",
        return_value={
            "dipendente_email": "dipendente@example.com",
            "dipendente_nome": "Mario Rossi",
            "salta_approvazione": True,
        },
    )
    @patch("automazioni.services._resolve_legacy_user_email", return_value="capo@example.com")
    @patch("automazioni.services.mark_queue_done")
    @patch("automazioni.services.run_rule")
    def test_process_queue_event_enriches_assenze_payload_with_runtime_fields(
        self,
        mock_run_rule,
        mock_mark_done,
        _mock_resolve_email,
        _mock_runtime_details,
    ):
        mock_run_rule.return_value = SimpleNamespace(status=AutomationRunLogStatus.SUCCESS)

        result = process_queue_event(
            {
                "id": 31,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": '{"id": 1, "capo_reparto_id": 12, "moderation_status": 1}',
                "old_payload_json": '{"id": 1, "capo_reparto_id": 12, "moderation_status": 0}',
            }
        )

        self.assertEqual(result["status"], "done")
        mock_mark_done.assert_called_once_with(31)
        payload = mock_run_rule.call_args.args[1]
        old_payload = mock_run_rule.call_args.kwargs["old_payload"]
        self.assertEqual(payload["dipendente_email"], "dipendente@example.com")
        self.assertEqual(payload["dipendente_nome"], "Mario Rossi")
        self.assertTrue(payload["salta_approvazione"])
        self.assertEqual(old_payload["dipendente_email"], "dipendente@example.com")
        self.assertEqual(old_payload["dipendente_nome"], "Mario Rossi")
        self.assertTrue(old_payload["salta_approvazione"])

    @patch("automazioni.services.mark_queue_error")
    @patch("automazioni.services.run_rule", side_effect=RuntimeError("runtime exploded"))
    def test_process_queue_event_marks_error_on_worker_runtime_failure(self, _mock_run_rule, mock_mark_error):
        result = process_queue_event(
            {
                "id": 4,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": '{"id": 1, "moderation_status": 1}',
                "old_payload_json": '{"id": 1, "moderation_status": 0}',
            }
        )

        self.assertEqual(result["status"], "error")
        mock_mark_error.assert_called_once()

    @patch("automazioni.services.process_queue_event")
    @patch("automazioni.services.fetch_pending_queue_events")
    def test_process_pending_queue_events_handles_batch_without_stopping(self, mock_fetch, mock_process):
        mock_fetch.return_value = [{"id": 10}, {"id": 11}]
        mock_process.side_effect = [
            {"queue_id": 10, "status": "done", "rule_runs": 1, "message": ""},
            {"queue_id": 11, "status": "error", "rule_runs": 0, "message": "boom"},
        ]

        summary = process_pending_queue_events(limit=2)

        self.assertEqual(summary["fetched"], 2)
        self.assertEqual(summary["done"], 1)
        self.assertEqual(summary["error"], 1)
        self.assertEqual(summary["rule_runs"], 1)

    @patch("automazioni.services.execute_safe_update")
    @patch("automazioni.services.fetch_pending_queue_event_snapshots")
    def test_dry_run_previews_update_record_without_writing(self, mock_fetch_snapshots, mock_execute_update):
        user = User.objects.create_user(username="dry-run-queue-user", password="pass12345")
        task = Task.objects.create(
            title="Dry run task",
            status="TODO",
            priority="MEDIUM",
            next_step_text="Prima",
            created_by=user,
        )
        AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "id",
                "where_value_template": "{task_id}",
                "update_fields": {"status": "DONE", "next_step_text": "Dry {id}"},
            },
        )
        mock_fetch_snapshots.return_value = [
            {
                "id": 88,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": json.dumps({"id": 42, "task_id": task.id}),
                "old_payload_json": json.dumps({"id": 42, "task_id": task.id}),
            }
        ]

        summary = process_pending_queue_events(limit=1, dry_run=True)
        task.refresh_from_db()

        self.assertEqual(task.status, "TODO")
        mock_execute_update.assert_not_called()
        self.assertEqual(summary["fetched"], 1)
        self.assertEqual(summary["rule_runs"], 1)
        action_previews = summary["events"][0]["rule_previews"][0]["actions"]
        self.assertEqual(action_previews[0]["status"], AutomationActionLogStatus.SUCCESS)
        self.assertIn("DRY-RUN update_record", action_previews[0]["message"])
        self.assertIn("status=DONE", action_previews[0]["message"])

    @patch("automazioni.services.fetch_pending_queue_event_snapshots")
    def test_dry_run_reports_safety_blocked_action(self, mock_fetch_snapshots):
        AutomationAction.objects.create(
            rule=self.rule,
            order=1,
            action_type=AutomationActionType.UPDATE_RECORD,
            config_json={
                "target_table": "tasks_task",
                "where_field": "id",
                "where_value_template": "{task_id}",
                "update_fields": {"title": "Non consentito"},
            },
        )
        mock_fetch_snapshots.return_value = [
            {
                "id": 89,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": json.dumps({"id": 42, "task_id": 1}),
                "old_payload_json": json.dumps({"id": 42, "task_id": 1}),
            }
        ]

        summary = process_pending_queue_events(limit=1, dry_run=True)

        self.assertEqual(summary["error"], 1)
        action_preview = summary["events"][0]["rule_previews"][0]["actions"][0]
        self.assertEqual(action_preview["status"], AutomationActionLogStatus.ERROR)
        self.assertIn("safety blocked", action_preview["message"])


class AutomationQueueCommandTests(SimpleTestCase):
    @patch("automazioni.management.commands.process_automation_queue.process_pending_queue_events")
    def test_process_automation_queue_command_supports_limit_and_source_code(self, mock_process):
        mock_process.return_value = {
            "fetched": 1,
            "done": 1,
            "error": 0,
            "rule_runs": 2,
            "events": [{"queue_id": 1, "status": "done", "message": ""}],
        }
        stdout = io.StringIO()

        call_command("process_automation_queue", "--limit=5", "--source-code=assenze", "--no-monitoring", stdout=stdout)

        mock_process.assert_called_once_with(limit=5, source_code="assenze", dry_run=False)
        self.assertIn("fetched=1 done=1 error=0 rule_runs=2", stdout.getvalue())

    @patch("automazioni.management.commands.process_automation_queue.process_pending_queue_events")
    def test_process_automation_queue_command_supports_dry_run(self, mock_process):
        mock_process.return_value = {
            "fetched": 1,
            "done": 0,
            "error": 0,
            "rule_runs": 0,
            "events": [{"queue_id": 7, "status": "dry-run", "candidate_rule_codes": ["rule-a"]}],
        }
        stdout = io.StringIO()

        call_command("process_automation_queue", "--dry-run", "--no-monitoring", stdout=stdout)

        mock_process.assert_called_once_with(limit=50, source_code=None, dry_run=True)
        self.assertIn("candidate_rules=rule-a", stdout.getvalue())

    @patch("automazioni.management.commands.process_automation_queue.process_pending_queue_events")
    def test_process_automation_queue_command_prints_dry_run_action_previews(self, mock_process):
        mock_process.return_value = {
            "fetched": 1,
            "done": 0,
            "error": 0,
            "rule_runs": 1,
            "events": [
                {
                    "queue_id": 7,
                    "status": "dry-run",
                    "candidate_rule_codes": ["rule-a"],
                    "rule_previews": [
                        {
                            "message": "DRY-RUN regola rule-a: azioni valutate=1, errori=0.",
                            "actions": [
                                {
                                    "action_id": 12,
                                    "action_type": "update_record",
                                    "status": "success",
                                    "message": "DRY-RUN update_record: aggiornerebbe tasks_task.",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        stdout = io.StringIO()

        call_command("process_automation_queue", "--dry-run", "--no-monitoring", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("DRY-RUN regola rule-a", output)
        self.assertIn("action_id=12 type=update_record status=success", output)


class AutomationQueueDisplayDateTests(SimpleTestCase):
    def test_format_display_datetime_converts_aware_values_to_project_timezone(self):
        from .views import _format_display_datetime

        with timezone.override("Europe/Rome"):
            value = datetime(2026, 4, 17, 10, 33, 41, tzinfo=dt_timezone.utc)
            self.assertEqual(_format_display_datetime(value), "17/04/2026 12:33:41")

    def test_format_display_datetime_assumes_project_timezone_for_naive_values(self):
        from .views import _format_display_datetime

        with timezone.override("Europe/Rome"):
            value = datetime(2026, 4, 17, 12, 33, 41)
            self.assertEqual(_format_display_datetime(value), "17/04/2026 12:33:41")


# ---------------------------------------------------------------------------
# evaluate_condition — resilienza su eccezione interna
# ---------------------------------------------------------------------------

class EvaluateConditionResilienceTests(TestCase):
    """
    evaluate_condition deve restituire False (mai propagare) quando incontra
    un errore interno, e deve emettere un log di warning per l'osservabilità.
    """

    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="rule-resilience",
            name="Rule resilience",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.INSERT,
            trigger_scope=AutomationRuleTriggerScope.ALL_INSERTS,
        )

    def _condition(self, **overrides):
        base = {
            "rule": self.rule,
            "order": 1,
            "field_name": "moderation_status",
            "operator": AutomationConditionOperator.EQUALS,
            "expected_value": "2",
            "value_type": AutomationConditionValueType.INT,
        }
        base.update(overrides)
        return AutomationCondition(**base)

    def test_returns_false_and_logs_warning_on_internal_exception(self):
        """
        Se _coerce_value o qualsiasi helper lancia, evaluate_condition
        restituisce False e logga un warning (non propaga l'eccezione).
        """
        condition = self._condition()
        # Forziamo un'eccezione interna sostituendo _coerce_value con un crash
        with patch("automazioni.services._coerce_value", side_effect=RuntimeError("boom")):
            with self.assertLogs("automazioni.services", level="WARNING") as log_ctx:
                result = evaluate_condition(condition, {"moderation_status": 2})
        self.assertFalse(result)
        self.assertTrue(
            any("evaluate_condition" in line and "moderation_status" in line for line in log_ctx.output),
            msg="Il warning deve menzionare evaluate_condition e il field_name",
        )

    def test_returns_false_on_none_operator_without_crash(self):
        """Operator None non deve propagare (None non matcha nessun ramo → return False finale)."""
        condition = self._condition(operator=None)
        result = evaluate_condition(condition, {"moderation_status": 2})
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# run_rule — logging su eccezione interna inattesa
# ---------------------------------------------------------------------------

class RunRuleExceptionLoggingTests(TestCase):
    """
    Se avviene un'eccezione inattesa durante run_rule (es. DB momentaneamente
    non disponibile), il run_log deve essere salvato con status=ERROR e
    l'eccezione deve essere loggata via logger.exception.
    """

    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="rule-logging-test",
            name="Rule logging test",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_draft=False,
        )

    def _add_condition(self):
        """Aggiunge una condizione alla regola in modo che evaluate_condition venga invocata."""
        return AutomationCondition.objects.create(
            rule=self.rule,
            order=1,
            field_name="moderation_status",
            operator=AutomationConditionOperator.EQUALS,
            expected_value="1",
            value_type=AutomationConditionValueType.INT,
        )

    def test_run_rule_finally_saves_run_log_on_base_exception(self):
        """
        Se evaluate_condition lancia un BaseException (es. SystemExit), il blocco
        finally di run_rule deve comunque salvare il run_log su DB prima di propagare.
        """
        self._add_condition()
        # SystemExit non è catturata dall'except Exception → propaga, ma finally gira
        with patch(
            "automazioni.services.evaluate_condition",
            side_effect=SystemExit("forza crash"),
        ):
            with self.assertRaises(SystemExit):
                run_rule(
                    self.rule,
                    {"moderation_status": 1},
                    old_payload={"moderation_status": 0},
                    queue_event_id=999,
                )

        run_log = AutomationRunLog.objects.filter(rule=self.rule).first()
        self.assertIsNotNone(run_log, "Il run_log deve essere salvato anche dopo un BaseException")
        self.assertIsNotNone(run_log.finished_at)

    def test_run_rule_logs_unexpected_exception(self):
        """
        Un'eccezione catturata dall'except Exception di run_rule deve essere loggata
        via logger.exception e il run_log deve avere status=ERROR.
        """
        self._add_condition()
        with patch(
            "automazioni.services.evaluate_condition",
            side_effect=Exception("eccezione inattesa"),
        ):
            with self.assertLogs("automazioni.services", level="ERROR") as log_ctx:
                run_rule(
                    self.rule,
                    {"moderation_status": 1},
                    old_payload={"moderation_status": 0},
                    queue_event_id=42,
                )

        self.assertTrue(
            any("run_rule" in line for line in log_ctx.output),
            msg="logger.exception deve produrre un log ERROR con 'run_rule'",
        )
        run_log = AutomationRunLog.objects.filter(rule=self.rule).first()
        self.assertEqual(run_log.status, AutomationRunLogStatus.ERROR)
        self.assertIn("eccezione inattesa", run_log.error_trace)


# ---------------------------------------------------------------------------
# process_queue_event — candidate_rule_codes nella risposta
# ---------------------------------------------------------------------------

class ProcessQueueEventCandidateRulesTests(TestCase):
    """
    process_queue_event deve sempre restituire candidate_rule_codes
    (non solo nel dry-run) per l'osservabilità via management command e log.
    """

    def setUp(self):
        self.rule = AutomationRule.objects.create(
            code="rule-candidate-test",
            name="Rule candidate test",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
            is_draft=False,
        )

    @patch("automazioni.services.mark_queue_done")
    @patch("automazioni.services.run_rule")
    def test_done_result_includes_candidate_rule_codes(self, mock_run_rule, mock_mark_done):
        mock_run_rule.return_value = SimpleNamespace(status=AutomationRunLogStatus.SUCCESS)
        result = process_queue_event(
            {
                "id": 100,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": '{"id": 1, "moderation_status": 2}',
                "old_payload_json": '{"id": 1, "moderation_status": 1}',
            }
        )
        self.assertEqual(result["status"], "done")
        self.assertIn("candidate_rule_codes", result)
        self.assertIn(self.rule.code, result["candidate_rule_codes"])

    @patch("automazioni.services.mark_queue_error")
    @patch("automazioni.services.run_rule", side_effect=Exception("boom"))
    def test_error_result_includes_candidate_rule_codes(self, _mock_run_rule, _mock_mark_error):
        result = process_queue_event(
            {
                "id": 101,
                "source_code": "assenze",
                "operation_type": "update",
                "payload_json": '{"id": 1, "moderation_status": 2}',
                "old_payload_json": '{"id": 1, "moderation_status": 1}',
            }
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("candidate_rule_codes", result)
        self.assertIn(self.rule.code, result["candidate_rule_codes"])


# ═══════════════════════════════════════════════════════════════════════════════
# Test: ApprovalEmailTemplate — rendering, mailto, fallback
# ═══════════════════════════════════════════════════════════════════════════════

class ApprovalEmailTemplateRenderingTests(SimpleTestCase):
    """Test rendering del template email approvazione senza DB."""

    def _make_template(self, **kwargs):
        from types import SimpleNamespace as _NS
        defaults = dict(
            code="test-tpl",
            name="Test",
            delivery_mode="portal_links",
            subject_template="Approva richiesta #{id}",
            title_template="Titolo: {dipendente_nome}",
            intro_template="Hai una richiesta di {tipo_assenza}.",
            body_template="",
            include_facts=True,
            facts_lines="Tipo | {tipo_assenza}\nDal | {data_inizio}",
            approval_label="Approva",
            rejection_label="Rifiuta",
            include_mailto_actions=False,
            mailto_mailbox="",
            approval_mailto_subject_template="CMD APPROVO RID {approval_token}",
            approval_mailto_body_template="CMD: APPROVO\nRID: {approval_token}",
            rejection_mailto_subject_template="CMD RIFIUTO RID {approval_token}",
            rejection_mailto_body_template="CMD: RIFIUTO\nRID: {approval_token}\nMOTIVO: ",
        )
        defaults.update(kwargs)
        ns = _NS(**defaults)
        ns.uses_portal_links = lambda: ns.delivery_mode in ("portal_links", "hybrid")
        ns.uses_mailto = lambda: ns.delivery_mode in ("mail_reply", "hybrid")
        return ns

    def test_subject_rendered(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template()
        ctx = {"id": "ABS-001", "tipo_assenza": "Ferie", "data_inizio": "2026-06-01", "dipendente_nome": "Mario"}
        result = render_approval_email(tpl, ctx, approve_url="http://example.com/approva/", reject_url="http://example.com/rifiuta/")
        self.assertEqual(result["subject"], "Approva richiesta #ABS-001")

    def test_html_contains_intro_and_title(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template()
        ctx = {"id": "ABS-001", "tipo_assenza": "Ferie", "data_inizio": "2026-06-01", "dipendente_nome": "Mario"}
        result = render_approval_email(tpl, ctx, approve_url="http://ex.com/a/", reject_url="http://ex.com/r/")
        self.assertIn("Titolo: Mario", result["html_body"])
        self.assertIn("Hai una richiesta di Ferie", result["html_body"])

    def test_html_contains_facts_table(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template()
        ctx = {"tipo_assenza": "Ferie", "data_inizio": "2026-06-01"}
        result = render_approval_email(tpl, ctx, approve_url="#a", reject_url="#r")
        self.assertIn("<table", result["html_body"])
        self.assertIn("Ferie", result["html_body"])
        self.assertIn("2026-06-01", result["html_body"])

    def test_html_contains_portal_cta_buttons(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template(delivery_mode="portal_links")
        ctx = {}
        result = render_approval_email(tpl, ctx, approve_url="http://ex.com/a/", reject_url="http://ex.com/r/")
        self.assertIn("http://ex.com/a/", result["html_body"])
        self.assertIn("http://ex.com/r/", result["html_body"])

    def test_body_template_overrides_intro_and_facts(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template(body_template="<strong>Corpo libero {tipo_assenza}</strong>")
        ctx = {"tipo_assenza": "Malattia"}
        result = render_approval_email(tpl, ctx, approve_url="#a", reject_url="#r")
        self.assertIn("<strong>Corpo libero Malattia</strong>", result["html_body"])
        self.assertNotIn("Hai una richiesta di", result["html_body"])

    def test_unresolved_placeholder_stays_in_output(self):
        from .approval_email_templates import render_approval_email, find_unresolved_placeholders
        tpl = self._make_template(subject_template="Richiesta #{id} da {dipendente_nome}")
        ctx = {"id": "ABS-001"}
        result = render_approval_email(tpl, ctx, approve_url="#a", reject_url="#r")
        self.assertIn("{dipendente_nome}", result["subject"])
        unresolved = find_unresolved_placeholders(result["subject"])
        self.assertIn("dipendente_nome", unresolved)
        self.assertNotIn("id", unresolved)

    def test_no_portal_cta_when_delivery_mode_mail_reply(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template(delivery_mode="mail_reply")
        ctx = {}
        result = render_approval_email(tpl, ctx, approve_url="http://ex.com/a/", reject_url="http://ex.com/r/")
        self.assertNotIn("http://ex.com/a/", result["html_body"])

    def test_mailto_cta_present_when_mail_reply_and_include_mailto(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template(
            delivery_mode="mail_reply",
            include_mailto_actions=True,
            mailto_mailbox="approvazioni@cnovicrom.local",
        )
        ctx = {"approval_token": "abc-token-123"}
        result = render_approval_email(tpl, ctx, approve_url="#a", reject_url="#r")
        self.assertIn("mailto:approvazioni@cnovicrom.local", result["html_body"])
        self.assertIn("abc-token-123", result["html_body"])

    def test_mailto_links_contain_token(self):
        from .approval_email_templates import build_mailto_approve_link, build_mailto_reject_link
        tpl = self._make_template(
            delivery_mode="mail_reply",
            include_mailto_actions=True,
            mailto_mailbox="approvazioni@test.local",
        )
        ctx = {"approval_token": "UNIQUE-TOKEN-XYZ"}
        approve_link = build_mailto_approve_link(tpl, ctx)
        reject_link = build_mailto_reject_link(tpl, ctx)
        self.assertIn("mailto:approvazioni@test.local", approve_link)
        self.assertIn("UNIQUE-TOKEN-XYZ", approve_link)
        self.assertIn("UNIQUE-TOKEN-XYZ", reject_link)

    def test_mailto_empty_when_no_mailbox(self):
        from .approval_email_templates import build_mailto_approve_link
        tpl = self._make_template(delivery_mode="mail_reply", include_mailto_actions=True, mailto_mailbox="")
        ctx = {"approval_token": "TOKEN"}
        link = build_mailto_approve_link(tpl, ctx)
        self.assertEqual(link, "")

    def test_hybrid_has_both_portal_and_mailto_cta(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template(
            delivery_mode="hybrid",
            include_mailto_actions=True,
            mailto_mailbox="approvazioni@test.local",
        )
        ctx = {"approval_token": "TOK"}
        result = render_approval_email(tpl, ctx, approve_url="http://ex.com/a/", reject_url="http://ex.com/r/")
        self.assertIn("http://ex.com/a/", result["html_body"])
        self.assertIn("mailto:approvazioni@test.local", result["html_body"])

    def test_text_body_not_empty(self):
        from .approval_email_templates import render_approval_email
        tpl = self._make_template()
        ctx = {"tipo_assenza": "Ferie", "data_inizio": "2026-06-01"}
        result = render_approval_email(tpl, ctx, approve_url="#a", reject_url="#r")
        self.assertTrue(len(result["text_body"]) > 0)

    def test_demo_payload_preview(self):
        from .approval_email_templates import render_approval_email_preview
        tpl = self._make_template()
        result = render_approval_email_preview(tpl)
        self.assertIn("subject", result)
        self.assertIn("html_body", result)
        self.assertIn("text_body", result)
        self.assertTrue(result["subject"])

    def test_build_template_context_injects_approval_fields(self):
        from .approval_email_templates import build_template_context
        from types import SimpleNamespace as _NS
        approval = _NS(token="TOKEN-UUID", pk=42)
        ctx = build_template_context({"id": "ABS-001"}, approval=approval, approve_url="/a/", reject_url="/r/")
        self.assertEqual(ctx["approval_token"], "TOKEN-UUID")
        self.assertEqual(ctx["approval_id"], "42")
        self.assertEqual(ctx["approve_url"], "/a/")
        self.assertEqual(ctx["reject_url"], "/r/")

    def test_parse_facts_lines(self):
        from .approval_email_templates import _parse_facts_lines
        facts = _parse_facts_lines(
            "Tipo | {tipo_assenza}\nDal | {data_inizio}\n  |  \n",
            {"tipo_assenza": "Ferie", "data_inizio": "2026-06-01"},
        )
        self.assertEqual(len(facts), 2)
        self.assertEqual(facts[0]["name"], "Tipo")
        self.assertEqual(facts[0]["value"], "Ferie")
        self.assertEqual(facts[1]["value"], "2026-06-01")


class ApprovalEmailTemplateDBTests(TestCase):
    """Test model + helper DB (usa SQLite)."""

    def _make_tpl(self, **kwargs):
        from .models import ApprovalEmailTemplate
        defaults = dict(
            code="tpl-db-test",
            name="DB Test Template",
            delivery_mode="portal_links",
            subject_template="Approva #{id}",
        )
        defaults.update(kwargs)
        return ApprovalEmailTemplate.objects.create(**defaults)

    def test_create_and_retrieve(self):
        from .models import ApprovalEmailTemplate
        tpl = self._make_tpl()
        fetched = ApprovalEmailTemplate.objects.get(pk=tpl.pk)
        self.assertEqual(fetched.code, "tpl-db-test")
        self.assertTrue(fetched.is_enabled)

    def test_unique_code_raises_integrity_error(self):
        from django.db import IntegrityError as DjIntegrityError
        self._make_tpl()
        with self.assertRaises(DjIntegrityError):
            self._make_tpl()

    def test_list_approval_email_templates_enabled_only(self):
        from .models import list_approval_email_templates
        self._make_tpl(code="tpl-enabled", is_enabled=True)
        self._make_tpl(code="tpl-disabled", is_enabled=False)
        enabled, missing = list_approval_email_templates(enabled_only=True)
        codes = [t.code for t in enabled]
        self.assertIn("tpl-enabled", codes)
        self.assertNotIn("tpl-disabled", codes)
        self.assertFalse(missing)

    def test_get_approval_email_template_by_id(self):
        from .models import get_approval_email_template
        tpl = self._make_tpl()
        found, missing = get_approval_email_template(template_id=tpl.pk)
        self.assertIsNotNone(found)
        self.assertEqual(found.pk, tpl.pk)
        self.assertFalse(missing)

    def test_get_approval_email_template_by_code(self):
        from .models import get_approval_email_template
        self._make_tpl()
        found, missing = get_approval_email_template(template_code="tpl-db-test")
        self.assertIsNotNone(found)
        self.assertEqual(found.code, "tpl-db-test")

    def test_get_approval_email_template_not_found(self):
        from .models import get_approval_email_template
        found, missing = get_approval_email_template(template_id=99999)
        self.assertIsNone(found)
        self.assertFalse(missing)

    def test_uses_mailto(self):
        from .models import ApprovalEmailTemplate, ApprovalEmailTemplateDeliveryMode
        tpl = self._make_tpl(delivery_mode=ApprovalEmailTemplateDeliveryMode.MAIL_REPLY)
        self.assertTrue(tpl.uses_mailto())
        self.assertFalse(tpl.uses_portal_links())

    def test_uses_portal_links(self):
        from .models import ApprovalEmailTemplateDeliveryMode
        tpl = self._make_tpl(delivery_mode=ApprovalEmailTemplateDeliveryMode.PORTAL_LINKS)
        self.assertFalse(tpl.uses_mailto())
        self.assertTrue(tpl.uses_portal_links())

    def test_uses_hybrid(self):
        from .models import ApprovalEmailTemplateDeliveryMode
        tpl = self._make_tpl(delivery_mode=ApprovalEmailTemplateDeliveryMode.HYBRID)
        self.assertTrue(tpl.uses_mailto())
        self.assertTrue(tpl.uses_portal_links())

    def test_mail_reply_full_clean_rejects_unparseable_subject(self):
        from .models import ApprovalEmailTemplate, ApprovalEmailTemplateDeliveryMode

        tpl = ApprovalEmailTemplate(
            code="tpl-db-invalid-mailreply",
            name="DB Invalid Mail Reply",
            delivery_mode=ApprovalEmailTemplateDeliveryMode.MAIL_REPLY,
            subject_template="Approva #{id}",
            approval_mailto_subject_template="APPROVA SENZA TOKEN",
            rejection_mailto_subject_template="CMD RIFIUTO RID {approval_token}",
        )

        with self.assertRaises(ValidationError) as ctx:
            tpl.full_clean()

        self.assertIn("approval_mailto_subject_template", ctx.exception.message_dict)


class ApprovalEmailTemplateFallbackTests(TestCase):
    """Test che il fallback in send_approval sia sicuro se il template manca."""

    def _build_rule_and_action(self, config_override=None):
        User = get_user_model()
        User.objects.filter(username="test-approval-tpl").delete()
        rule = AutomationRule.objects.create(
            code="test-rule-tpl-fallback",
            name="Test fallback",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ANY_CHANGE,
            is_active=True,
            is_draft=False,
        )
        config = {
            "delivery_mode": "email",
            "to_template": "admin@test.local",
            "subject_template": "Approva",
            "message_template": "Ciao",
            "expiry_days": 7,
            "approve_label": "Approva",
            "reject_label": "Rifiuta",
        }
        if config_override:
            config.update(config_override)
        action = AutomationAction.objects.create(
            rule=rule,
            order=1,
            action_type=AutomationActionType.SEND_APPROVAL,
            is_enabled=True,
            config_json=config,
        )
        run_log = AutomationRunLog.objects.create(
            rule=rule,
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            status=AutomationRunLogStatus.SUCCESS,
        )
        return action, run_log

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_approval_fallback_no_template(self, mock_email_cls):
        """send_approval senza template deve funzionare come prima."""
        mock_msg = MagicMock()
        mock_msg.send.return_value = 1
        mock_email_cls.return_value = mock_msg
        action, run_log = self._build_rule_and_action()
        payload_context = {"id": "ABS-001"}
        result = execute_action(
            action=action,
            payload=payload_context,
            old_payload=None,
            run_log=run_log,
        )
        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        mock_email_cls.assert_called_once()

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_approval_invalid_template_code_falls_back(self, mock_email_cls):
        """Template code inesistente deve degradare silenziosamente."""
        mock_msg = MagicMock()
        mock_msg.send.return_value = 1
        mock_email_cls.return_value = mock_msg
        action, run_log = self._build_rule_and_action(
            config_override={"approval_email_template_code": "missing-template-code"}
        )
        result = execute_action(
            action=action,
            payload={"id": "ABS-001"},
            old_payload=None,
            run_log=run_log,
        )
        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)

    @patch("automazioni.services.EmailMultiAlternatives")
    def test_send_approval_with_valid_template_uses_rendered_body(self, mock_email_cls):
        """Con template valido l'HTML deve contenere il corpo reso dal template."""
        from .models import ApprovalEmailTemplate
        tpl = ApprovalEmailTemplate.objects.create(
            code="tpl-test-send",
            name="Test Send",
            delivery_mode="portal_links",
            subject_template="SUBJ #{id}",
            intro_template="INTRO_CONTENT {id}",
            include_facts=False,
        )
        mock_msg = MagicMock()
        mock_msg.send.return_value = 1
        mock_email_cls.return_value = mock_msg
        action, run_log = self._build_rule_and_action(
            config_override={"approval_email_template_code": tpl.code}
        )
        result = execute_action(
            action=action,
            payload={"id": "ABS-TMPL"},
            old_payload=None,
            run_log=run_log,
        )
        self.assertEqual(result["status"], AutomationActionLogStatus.SUCCESS)
        attach_calls = mock_msg.attach_alternative.call_args_list
        self.assertTrue(len(attach_calls) > 0)
        html_arg = attach_calls[0][0][0]
        self.assertIn("INTRO_CONTENT ABS-TMPL", html_arg)


class ApprovalEmailTemplateFormTests(TestCase):
    """Test form ApprovalEmailTemplateForm."""

    def _base_data(self, **overrides):
        data = {
            "code": "tpl-form-valid",
            "name": "Form Valid",
            "description": "",
            "is_enabled": True,
            "delivery_mode": "portal_links",
            "subject_template": "Approva #{id}",
            "title_template": "",
            "intro_template": "",
            "body_template": "",
            "include_facts": True,
            "facts_lines": "Tipo | {tipo_assenza}",
            "approval_label": "Approva",
            "rejection_label": "Rifiuta",
            "include_mailto_actions": False,
            "mailto_mailbox": "",
            "approval_mailto_subject_template": "CMD APPROVO RID {approval_token}",
            "approval_mailto_body_template": "CMD: APPROVO",
            "rejection_mailto_subject_template": "CMD RIFIUTO RID {approval_token}",
            "rejection_mailto_body_template": "CMD: RIFIUTO",
        }
        data.update(overrides)
        return data

    def test_valid_form(self):
        from .forms import ApprovalEmailTemplateForm
        data = self._base_data()
        form = ApprovalEmailTemplateForm(data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_code_with_spaces(self):
        from .forms import ApprovalEmailTemplateForm
        data = {
            "code": "invalid code",
            "name": "Test",
            "delivery_mode": "portal_links",
            "subject_template": "S",
            "approval_label": "A",
            "rejection_label": "R",
        }
        form = ApprovalEmailTemplateForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)

    def test_include_mailto_portal_only_invalid(self):
        from .forms import ApprovalEmailTemplateForm
        data = self._base_data(
            code="tpl-form-mailto",
            name="Form Mailto Portal",
            delivery_mode="portal_links",
            subject_template="S",
            approval_label="A",
            rejection_label="R",
            include_mailto_actions=True,
            approval_mailto_subject_template="S",
            approval_mailto_body_template="B",
            rejection_mailto_subject_template="S",
            rejection_mailto_body_template="B",
        )
        form = ApprovalEmailTemplateForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("include_mailto_actions", form.errors)

    def test_mail_reply_template_valid_custom_parseable_subjects(self):
        from .forms import ApprovalEmailTemplateForm

        data = self._base_data(
            code="tpl-mailreply-valid",
            delivery_mode="mail_reply",
            include_mailto_actions=True,
            approval_mailto_subject_template="Re: CMD APPROVO RID {approval_token}",
            rejection_mailto_subject_template="Re: CMD RIFIUTO RID {approval_token}",
        )
        form = ApprovalEmailTemplateForm(data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_mail_reply_template_requires_approval_token(self):
        from .forms import ApprovalEmailTemplateForm

        data = self._base_data(
            code="tpl-mailreply-no-token",
            delivery_mode="mail_reply",
            include_mailto_actions=True,
            approval_mailto_subject_template="CMD APPROVO RID fisso",
        )
        form = ApprovalEmailTemplateForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("approval_mailto_subject_template", form.errors)

    def test_mail_reply_template_requires_command_keyword(self):
        from .forms import ApprovalEmailTemplateForm

        data = self._base_data(
            code="tpl-mailreply-no-command",
            delivery_mode="mail_reply",
            include_mailto_actions=True,
            rejection_mailto_subject_template="Richiesta {approval_token}",
        )
        form = ApprovalEmailTemplateForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("rejection_mailto_subject_template", form.errors)


# ── Test: poll_approval_mailbox — parser IMAP ─────────────────────────────────

class PollApprovalMailboxParserTests(SimpleTestCase):
    """
    Test per le funzioni helper del comando poll_approval_mailbox.
    Non richiedono DB né connessione IMAP reale.
    """

    def _parse(self, subject: str, body: str) -> tuple:
        from .management.commands.poll_approval_mailbox import _parse_approval_command
        return _parse_approval_command(subject, [body])

    # ── subject-based parsing ─────────────────────────────────────────────────

    def test_subject_approvo_uppercase(self):
        token, decision = self._parse(
            "CMD APPROVO RID aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", ""
        )
        self.assertEqual(token, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(decision, "approved")

    def test_subject_rifiuto_uppercase(self):
        token, decision = self._parse(
            "CMD RIFIUTO RID aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", ""
        )
        self.assertEqual(token, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(decision, "rejected")

    def test_subject_cmd_colon_approvo(self):
        token, decision = self._parse(
            "Re: CMD: APPROVO RID 12345678-1234-1234-1234-123456789abc", ""
        )
        self.assertEqual(token, "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(decision, "approved")

    def test_subject_cmd_colon_rifiuto(self):
        token, decision = self._parse(
            "CMD: RIFIUTO RID 12345678-1234-1234-1234-123456789abc", ""
        )
        self.assertEqual(token, "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(decision, "rejected")

    def test_subject_case_insensitive(self):
        token, decision = self._parse(
            "cmd approvo rid aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", ""
        )
        self.assertEqual(decision, "approved")

    def test_subject_no_uuid_returns_none(self):
        token, decision = self._parse("CMD APPROVO RID mancante", "")
        self.assertIsNone(token)
        self.assertIsNone(decision)

    # ── body-based parsing (fallback) ────────────────────────────────────────

    def test_body_cmd_approvo_with_rid_line(self):
        body = "CMD: APPROVO\nRID: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n"
        token, decision = self._parse("Risposta automatica", body)
        self.assertEqual(token, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(decision, "approved")

    def test_body_cmd_rifiuto_with_rid_line(self):
        body = "CMD: RIFIUTO\nRID: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\nMOTIVO: Ferie bloccate"
        token, decision = self._parse("RE: Approvazione richiesta", body)
        self.assertEqual(token, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(decision, "rejected")

    def test_body_fallback_uuid_without_rid_prefix(self):
        """Se RID: manca ma c'è solo un UUID nel corpo, viene comunque estratto."""
        body = "CMD: APPROVO\nToken: aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\n"
        token, decision = self._parse("Risposta", body)
        self.assertEqual(token, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(decision, "approved")

    def test_body_no_command_keyword_returns_none(self):
        body = "Ciao, ho letto la richiesta. aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        token, decision = self._parse("Nessun comando", body)
        self.assertIsNone(token)
        self.assertIsNone(decision)

    def test_body_no_uuid_returns_none(self):
        body = "CMD: APPROVO\nNessun UUID qui"
        token, decision = self._parse("Approvazione", body)
        self.assertIsNone(token)
        self.assertIsNone(decision)

    def test_subject_takes_priority_over_body(self):
        """Il subject viene valutato per primo; il body viene ignorato se il subject è valido."""
        subject_token = "11111111-2222-3333-4444-555555555555"
        body_token = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        token, decision = self._parse(
            f"CMD APPROVO RID {subject_token}",
            f"CMD: RIFIUTO\nRID: {body_token}",
        )
        self.assertEqual(token, subject_token)
        self.assertEqual(decision, "approved")

    # ── _get_text_parts ───────────────────────────────────────────────────────

    def test_get_text_parts_simple_plaintext(self):
        import email as email_lib
        from .management.commands.poll_approval_mailbox import _get_text_parts
        raw = b"From: test@example.com\r\nSubject: Test\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHello world"
        msg = email_lib.message_from_bytes(raw)
        parts = _get_text_parts(msg)
        self.assertEqual(len(parts), 1)
        self.assertIn("Hello world", parts[0])

    def test_get_text_parts_multipart(self):
        import email as email_lib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from .management.commands.poll_approval_mailbox import _get_text_parts
        outer = MIMEMultipart("alternative")
        outer.attach(MIMEText("Testo plain CMD: APPROVO", "plain", "utf-8"))
        outer.attach(MIMEText("<b>HTML</b>", "html", "utf-8"))
        msg = email_lib.message_from_bytes(outer.as_bytes())
        parts = _get_text_parts(msg)
        self.assertEqual(len(parts), 1)
        self.assertIn("Testo plain CMD: APPROVO", parts[0])

    def test_get_text_parts_non_text_returns_empty(self):
        import email as email_lib
        from email.mime.base import MIMEBase
        from .management.commands.poll_approval_mailbox import _get_text_parts
        raw = b"From: t@t.it\r\nContent-Type: application/octet-stream\r\n\r\nbinary"
        msg = email_lib.message_from_bytes(raw)
        parts = _get_text_parts(msg)
        self.assertEqual(parts, [])


@override_settings(
    APPROVAL_IMAP_HOST="imap.test.local",
    APPROVAL_IMAP_PORT="993",
    APPROVAL_IMAP_USER="approvazioni@test.local",
    APPROVAL_IMAP_PASSWORD="secret",
    APPROVAL_IMAP_SSL="1",
    APPROVAL_IMAP_FOLDER="INBOX",
)
class ApprovalMailboxRuntimeTests(SimpleTestCase):
    def test_get_approval_imap_status_marks_runtime_ready(self):
        from .approval_mailbox_runtime import get_approval_imap_status

        status = get_approval_imap_status()

        self.assertTrue(status["is_ready"])
        self.assertEqual(status["host"], "imap.test.local")
        self.assertEqual(status["user"], "approvazioni@test.local")
        self.assertTrue(status["password_configured"])
        self.assertEqual(status["folder"], "INBOX")

    @patch("automazioni.approval_mailbox_runtime.call_command")
    def test_run_approval_imap_poll_now_parses_command_summary(self, mock_call_command):
        from .approval_mailbox_runtime import run_approval_imap_poll_now

        def _fake_call_command(*args, **kwargs):
            kwargs["stdout"].write(
                "[run] Completato - processed=2 approved=1 rejected=1 skipped=0 error=0"
            )

        mock_call_command.side_effect = _fake_call_command

        result = run_approval_imap_poll_now()

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["stats"],
            {"processed": 2, "approved": 1, "rejected": 1, "skipped": 0, "error": 0},
        )
        self.assertIn("1 approvate", result["message"])

    def test_save_approval_imap_settings_updates_env_and_runtime(self):
        from .approval_mailbox_runtime import get_approval_imap_form_defaults, save_approval_imap_settings

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            ok, message = save_approval_imap_settings(
                host="imap.changed.local",
                port=995,
                user="approvazioni-changed@test.local",
                password="",
                use_ssl=False,
                folder="Approvazioni",
                dotenv_path=env_path,
            )
            env_text = env_path.read_text(encoding="utf-8")

        self.assertTrue(ok)
        self.assertIn("Configurazione IMAP salvata", message)
        self.assertIn("APPROVAL_IMAP_HOST=imap.changed.local", env_text)
        self.assertIn("APPROVAL_IMAP_PORT=995", env_text)
        self.assertIn("APPROVAL_IMAP_USER=approvazioni-changed@test.local", env_text)
        self.assertIn("APPROVAL_IMAP_PASSWORD=secret", env_text)
        self.assertIn("APPROVAL_IMAP_SSL=0", env_text)
        self.assertIn("APPROVAL_IMAP_FOLDER=Approvazioni", env_text)
        self.assertEqual(str(getattr(settings, "APPROVAL_IMAP_HOST", "")), "imap.changed.local")
        self.assertEqual(str(getattr(settings, "APPROVAL_IMAP_PORT", "")), "995")
        self.assertEqual(str(getattr(settings, "APPROVAL_IMAP_SSL", "")), "0")
        form_defaults = get_approval_imap_form_defaults()
        self.assertEqual(form_defaults["host"], "imap.changed.local")
        self.assertEqual(form_defaults["port"], 995)
        self.assertFalse(form_defaults["use_ssl"])


# ─────────────────────────────────────────────────────────────────────────────
# Test suite: Graph mailbox backend
# ─────────────────────────────────────────────────────────────────────────────

class GraphMailboxParsingTests(SimpleTestCase):
    """Test del parser comandi per il backend Graph (nessun DB richiesto)."""

    def _parse(self, subject: str, body: str):
        from .mailbox_graph import parse_approval_command
        return parse_approval_command(subject, body)

    # ── Parsing soggetto APPROVO ──────────────────────────────────────────────
    def test_parse_subject_approvo_uuid(self):
        token = "550e8400-e29b-41d4-a716-446655440000"
        cmd, t, reason = self._parse(f"CMD APPROVO RID {token}", "")
        self.assertEqual(cmd, "approvo")
        self.assertEqual(t, token)
        self.assertIsNone(reason)

    def test_parse_subject_approvo_with_colon(self):
        token = "550e8400-e29b-41d4-a716-446655440000"
        cmd, t, _ = self._parse(f"CMD: APPROVO RID {token}", "")
        self.assertEqual(cmd, "approvo")
        self.assertEqual(t, token)

    # ── Parsing soggetto RIFIUTO ──────────────────────────────────────────────
    def test_parse_subject_rifiuto_uuid(self):
        token = "123e4567-e89b-12d3-a456-426614174000"
        cmd, t, _ = self._parse(f"CMD RIFIUTO RID {token}", "")
        self.assertEqual(cmd, "rifiuto")
        self.assertEqual(t, token)

    def test_parse_subject_rifiuto_with_reason_in_body(self):
        token = "123e4567-e89b-12d3-a456-426614174000"
        body = f"CMD RIFIUTO RID {token}\nMOTIVO: Non autorizzato"
        cmd, t, reason = self._parse(f"CMD RIFIUTO RID {token}", body)
        self.assertEqual(cmd, "rifiuto")
        self.assertEqual(reason, "Non autorizzato")

    # ── Fallback body ─────────────────────────────────────────────────────────
    def test_parse_body_fallback_approvo(self):
        token = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        body = f"CMD: APPROVO\nRID: {token}"
        cmd, t, _ = self._parse("Re: Richiesta approvazione", body)
        self.assertEqual(cmd, "approvo")
        self.assertEqual(t, token)

    def test_parse_body_fallback_rifiuto(self):
        token = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        body = f"CMD: RIFIUTO\nRID: {token}\nMOTIVO: Budget insufficiente"
        cmd, t, reason = self._parse("Re: Richiesta approvazione", body)
        self.assertEqual(cmd, "rifiuto")
        self.assertEqual(t, token)
        self.assertEqual(reason, "Budget insufficiente")

    def test_parse_body_fallback_accepts_token_label(self):
        token = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        body = f"CMD: APPROVO\nTOKEN: {token}"
        cmd, t, _ = self._parse("Re: Richiesta approvazione", body)
        self.assertEqual(cmd, "approvo")
        self.assertEqual(t, token)

    def test_parse_body_fallback_ignores_unlabeled_uuid(self):
        token = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        body = f"CMD: APPROVO\nToken libero nel testo {token}"
        cmd, t, _ = self._parse("Re: Richiesta approvazione", body)
        self.assertEqual(cmd, "approvo")
        self.assertIsNone(t)

    def test_parse_body_fallback_uses_only_labeled_uuid_when_multiple_present(self):
        labeled_token = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        other_token = "11111111-2222-3333-4444-555555555555"
        body = (
            f"CMD: RIFIUTO\n"
            f"Thread precedente {other_token}\n"
            f"RID: {labeled_token}\n"
            "MOTIVO: Non approvato"
        )
        cmd, t, reason = self._parse("Re: Richiesta approvazione", body)
        self.assertEqual(cmd, "rifiuto")
        self.assertEqual(t, labeled_token)
        self.assertEqual(reason, "Non approvato")

    # ── Nessun comando ────────────────────────────────────────────────────────
    def test_parse_no_command(self):
        cmd, t, reason = self._parse("Riunione di domani", "Ciao a tutti")
        self.assertIsNone(cmd)
        self.assertIsNone(t)
        self.assertIsNone(reason)

    def test_parse_command_without_uuid(self):
        cmd, t, _ = self._parse("CMD APPROVO RID senza-uuid", "nessun uuid qui")
        # soggetto matchato ma UUID non trovato
        self.assertIsNone(t)

    def test_parse_uppercase_insensitive(self):
        token = "550e8400-e29b-41d4-a716-446655440000"
        cmd, t, _ = self._parse(f"cmd approvo rid {token}", "")
        self.assertEqual(cmd, "approvo")
        self.assertEqual(t, token)


class GraphMailboxNormalizeTests(SimpleTestCase):
    """Test di normalize_message() su payload raw Graph (nessun DB)."""

    def _make_raw(self, **overrides):
        token = "550e8400-e29b-41d4-a716-446655440000"
        base = {
            "id": "GRAPH123",
            "internetMessageId": f"<msg.{token}@mail.example.com>",
            "subject": f"CMD APPROVO RID {token}",
            "from": {"emailAddress": {"address": "mario.rossi@costruzioninovicrom.it"}},
            "receivedDateTime": "2026-04-15T10:30:00Z",
            "bodyPreview": "CMD APPROVO RID ...",
            "body": {"contentType": "text", "content": f"CMD: APPROVO\nRID: {token}"},
            "isRead": False,
        }
        base.update(overrides)
        return base

    def test_normalize_basic(self):
        from .mailbox_graph import normalize_message
        raw = self._make_raw()
        msg = normalize_message(raw)
        self.assertEqual(msg.graph_id, "GRAPH123")
        self.assertEqual(msg.from_email, "mario.rossi@costruzioninovicrom.it")
        self.assertEqual(msg.command, "approvo")
        self.assertEqual(msg.token, "550e8400-e29b-41d4-a716-446655440000")
        self.assertFalse(msg.is_read)

    def test_normalize_html_body_strips_tags(self):
        from .mailbox_graph import normalize_message
        token = "550e8400-e29b-41d4-a716-446655440000"
        raw = self._make_raw(body={
            "contentType": "html",
            "content": f"<html><body><b>CMD APPROVO</b> RID {token}</body></html>",
        })
        msg = normalize_message(raw)
        self.assertNotIn("<b>", msg.body_text)
        self.assertEqual(msg.command, "approvo")

    def test_normalize_missing_from(self):
        from .mailbox_graph import normalize_message
        raw = self._make_raw()
        raw["from"] = {}
        msg = normalize_message(raw)
        self.assertEqual(msg.from_email, "")

    def test_normalize_invalid_date(self):
        from .mailbox_graph import normalize_message
        raw = self._make_raw(receivedDateTime="not-a-date")
        msg = normalize_message(raw)
        self.assertIsNone(msg.received_at)


class GraphMailboxDeduplicationTests(TestCase):
    """Test deduplica su DB."""

    def test_is_already_processed_false_for_new(self):
        from .mailbox_graph import is_already_processed
        self.assertFalse(is_already_processed("<nuovo-msg-id@example.com>"))

    def test_save_message_record_persists_graph_and_internet_ids(self):
        from .mailbox_graph import save_message_record, normalize_message
        from .models import ApprovalMailboxMessage

        token = "550e8400-e29b-41d4-a716-446655440000"
        raw = {
            "id": "GID1",
            "internetMessageId": "<dedup-test@example.com>",
            "subject": f"CMD APPROVO RID {token}",
            "from": {"emailAddress": {"address": "test@example.com"}},
            "receivedDateTime": "2026-04-15T10:30:00Z",
            "bodyPreview": "",
            "body": {"contentType": "text", "content": ""},
            "isRead": False,
        }
        msg = normalize_message(raw)

        with override_settings(APPROVAL_MAILBOX_ADDRESS="test@example.com", APPROVAL_MAILBOX_FOLDER="Inbox"):
            save_message_record(msg, status="processed")

        record = ApprovalMailboxMessage.objects.get(
            internet_message_id="<dedup-test@example.com>"
        )
        self.assertEqual(record.internet_message_id, "<dedup-test@example.com>")
        self.assertEqual(record.graph_message_id, "GID1")

    def test_is_already_processed_true_after_save(self):
        from .mailbox_graph import is_already_processed, save_message_record, normalize_message

        token = "550e8400-e29b-41d4-a716-446655440000"
        raw = {
            "id": "GID1",
            "internetMessageId": "<dedup-test@example.com>",
            "subject": f"CMD APPROVO RID {token}",
            "from": {"emailAddress": {"address": "test@example.com"}},
            "receivedDateTime": "2026-04-15T10:30:00Z",
            "bodyPreview": "",
            "body": {"contentType": "text", "content": ""},
            "isRead": False,
        }
        msg = normalize_message(raw)

        with override_settings(APPROVAL_MAILBOX_ADDRESS="test@example.com", APPROVAL_MAILBOX_FOLDER="Inbox"):
            save_message_record(msg, status="processed")

        self.assertTrue(is_already_processed("<dedup-test@example.com>"))

    def test_save_message_record_update_or_create_idempotent(self):
        from .mailbox_graph import save_message_record, normalize_message
        from .models import ApprovalMailboxMessage

        token = "550e8400-e29b-41d4-a716-446655440001"
        raw = {
            "id": "GID2",
            "internetMessageId": "<idempotent-test@example.com>",
            "subject": f"CMD RIFIUTO RID {token}",
            "from": {"emailAddress": {"address": "utente@example.com"}},
            "receivedDateTime": "2026-04-15T11:00:00Z",
            "bodyPreview": "",
            "body": {"contentType": "text", "content": ""},
            "isRead": False,
        }
        msg = normalize_message(raw)

        with override_settings(APPROVAL_MAILBOX_ADDRESS="mb@example.com", APPROVAL_MAILBOX_FOLDER="Inbox"):
            save_message_record(msg, status="ignored", error="test")
            save_message_record(msg, status="processed")  # seconda chiamata — deve fare update

        count = ApprovalMailboxMessage.objects.filter(
            internet_message_id="<idempotent-test@example.com>"
        ).count()
        self.assertEqual(count, 1)
        record = ApprovalMailboxMessage.objects.get(internet_message_id="<idempotent-test@example.com>")
        self.assertEqual(record.processing_status, "processed")
        self.assertEqual(record.graph_message_id, "GID2")


class GraphMailboxValidateSenderTests(TestCase):
    """Test validazione mittente."""

    def _make_approval(self, approver_emails=None, status="pending"):
        rule = AutomationRule.objects.create(
            name="ValidateSenderRule",
            source_code="assenze",
            code=f"validate_sender_rule_{AutomationRule.objects.count() + 1}",
            operation_type=AutomationRuleOperationType.INSERT,
            trigger_scope=AutomationRuleTriggerScope.ALL_INSERTS,
            is_draft=False,
        )
        run_log = AutomationRunLog.objects.create(
            rule=rule,
            source_code=rule.source_code,
            operation_type=rule.operation_type,
            status=AutomationRunLogStatus.WAITING_APPROVAL,
            payload_json={"id": 1},
        )
        approval = AutomationApproval.objects.create(
            run_log=run_log,
            subject="Test",
            approver_emails=approver_emails if approver_emails is not None else [],
            status=status,
        )
        return approval

    def test_validate_sender_authorized_with_normalization(self):
        from .mailbox_graph import _validate_sender
        approval = self._make_approval(approver_emails=[" Responsabile@example.com "])
        error = _validate_sender(str(approval.token), "  RESPONSABILE@example.com ")
        self.assertIsNone(error)

    def test_validate_sender_unauthorized(self):
        from .mailbox_graph import _validate_sender
        approval = self._make_approval(approver_emails=["responsabile@example.com"])
        error = _validate_sender(str(approval.token), "estraneo@example.com")
        self.assertIsNotNone(error)
        self.assertIn("lista degli approvatori", error)

    def test_validate_sender_rejects_if_approver_list_empty(self):
        """Se approver_emails è vuoto, qualsiasi mittente è accettato."""
        from .mailbox_graph import _validate_sender
        approval = self._make_approval(approver_emails=[])
        error = _validate_sender(str(approval.token), "chiunque@example.com")
        self.assertIsNotNone(error)
        self.assertIn("Nessun approvatore configurato", error)

    def test_validate_sender_already_decided(self):
        from .mailbox_graph import _validate_sender
        approval = self._make_approval(
            approver_emails=["responsabile@example.com"],
            status="approved",
        )
        error = _validate_sender(str(approval.token), "chiunque@example.com")
        self.assertIsNotNone(error)
        self.assertIn("già in stato", error)

    def test_validate_sender_invalid_token(self):
        from .mailbox_graph import _validate_sender
        error = _validate_sender("non-un-uuid", "chiunque@example.com")
        self.assertIsNotNone(error)
        self.assertIn("Token non valido", error)

    def test_validate_sender_token_not_found(self):
        from .mailbox_graph import _validate_sender
        error = _validate_sender("00000000-0000-0000-0000-000000000000", "chiunque@example.com")
        self.assertIsNotNone(error)
        self.assertIn("approvazione non trovata", error)

    def test_validate_sender_fails_closed_on_unexpected_exception(self):
        from .mailbox_graph import _validate_sender

        with patch("automazioni.models.AutomationApproval.objects.get", side_effect=RuntimeError("db down")):
            error = _validate_sender("00000000-0000-0000-0000-000000000001", "chiunque@example.com")

        self.assertIsNotNone(error)
        self.assertIn("errore tecnico", error)


class GraphMailboxPollIntegrationTests(TestCase):
    """Test del poll_graph_mailbox con Graph mockato."""

    def _build_raw_message(self, token: str, command: str = "approvo", from_email: str = "approver@example.com") -> dict:
        subject_cmd = "APPROVO" if command == "approvo" else "RIFIUTO"
        return {
            "id": f"GMSG_{token[:8]}",
            "internetMessageId": f"<{token}@mail.example.com>",
            "subject": f"CMD {subject_cmd} RID {token}",
            "from": {"emailAddress": {"address": from_email}},
            "receivedDateTime": "2026-04-15T10:00:00Z",
            "bodyPreview": "",
            "body": {"contentType": "text", "content": f"CMD: {subject_cmd}\nRID: {token}"},
            "isRead": False,
        }

    def _make_approval(self, approver_emails=None, status="pending"):
        rule = AutomationRule.objects.create(
            name="PollTestRule",
            source_code="assenze",
            code=f"poll_test_rule_{AutomationRule.objects.count() + 1}",
            operation_type=AutomationRuleOperationType.INSERT,
            trigger_scope=AutomationRuleTriggerScope.ALL_INSERTS,
            is_draft=False,
        )
        run_log = AutomationRunLog.objects.create(
            rule=rule,
            source_code=rule.source_code,
            operation_type=rule.operation_type,
            status=AutomationRunLogStatus.WAITING_APPROVAL,
            payload_json={"id": 1},
        )
        approval = AutomationApproval.objects.create(
            run_log=run_log,
            subject="Test approval",
            approver_emails=approver_emails if approver_emails is not None else ["approver@example.com"],
            status=status,
        )
        return approval

    @override_settings(
        GRAPH_TENANT_ID="tenant123",
        GRAPH_CLIENT_ID="client123",
        GRAPH_CLIENT_SECRET="secret123",
        APPROVAL_MAILBOX_ADDRESS="approvals@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="0",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    @patch("automazioni.mailbox_graph.mark_message_as_read")
    @patch("automazioni.mailbox_graph._validate_sender")
    @patch("automazioni.services.process_approval_decision")
    def test_poll_processes_approvo(
        self, mock_process, mock_validate, mock_mark, mock_fetch
    ):
        """Un messaggio APPROVO valido viene processato correttamente."""
        approval = self._make_approval(approver_emails=["approver@example.com"])
        token_str = str(approval.token)

        mock_fetch.return_value = [self._build_raw_message(token_str, "approvo")]
        mock_validate.return_value = None  # autorizzato
        mock_process.return_value = {"ok": True, "approval_id": approval.pk, "actions_run": 0}

        from .mailbox_graph import poll_graph_mailbox
        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=False)

        self.assertEqual(result.read, 1)
        self.assertEqual(result.processed, 1)
        self.assertEqual(result.approved, 1)
        self.assertEqual(result.error, 0)
        mock_process.assert_called_once()

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="0",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    def test_poll_ignores_no_command(self, mock_fetch):
        """Messaggio senza comando viene ignorato e tracciato."""
        msg_id = "<nocommand@example.com>"
        mock_fetch.return_value = [{
            "id": "GID_NO_CMD",
            "internetMessageId": msg_id,
            "subject": "Riunione domani mattina",
            "from": {"emailAddress": {"address": "someone@example.com"}},
            "receivedDateTime": "2026-04-15T09:00:00Z",
            "bodyPreview": "Ciao",
            "body": {"contentType": "text", "content": "Ciao a tutti"},
            "isRead": False,
        }]

        from .mailbox_graph import poll_graph_mailbox
        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=False)

        self.assertEqual(result.ignored, 1)
        self.assertEqual(result.processed, 0)

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="0",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    def test_poll_deduplicates_already_processed(self, mock_fetch):
        """Messaggio già presente in DB come 'processed' viene saltato."""
        from .models import ApprovalMailboxMessage, ApprovalMailboxMessageStatus
        from .mailbox_graph import poll_graph_mailbox

        mid = "<already-done@example.com>"
        ApprovalMailboxMessage.objects.create(
            internet_message_id=mid,
            mailbox="mb@example.com",
            processing_status=ApprovalMailboxMessageStatus.PROCESSED,
        )
        token = "550e8400-e29b-41d4-a716-446655440002"
        mock_fetch.return_value = [{
            "id": "GID_DEDUP",
            "internetMessageId": mid,
            "subject": f"CMD APPROVO RID {token}",
            "from": {"emailAddress": {"address": "someone@example.com"}},
            "receivedDateTime": "2026-04-15T09:00:00Z",
            "bodyPreview": "",
            "body": {"contentType": "text", "content": ""},
            "isRead": False,
        }]

        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=False)
        self.assertEqual(result.deduped, 1)
        self.assertEqual(result.processed, 0)

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="0",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    @patch("automazioni.mailbox_graph._validate_sender")
    def test_poll_unauthorized_sender_ignored(self, mock_validate, mock_fetch):
        """Messaggio da mittente non autorizzato viene ignorato."""
        token = "550e8400-e29b-41d4-a716-446655440003"
        mock_fetch.return_value = [self._build_raw_message(token, "approvo", "hacker@evil.com")]
        mock_validate.return_value = "'hacker@evil.com' non nella lista approvatori"

        from .mailbox_graph import poll_graph_mailbox
        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=False)

        self.assertEqual(result.ignored, 1)
        self.assertEqual(result.processed, 0)

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="1",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    @patch("automazioni.mailbox_graph.mark_message_as_read")
    @patch("automazioni.mailbox_graph._validate_sender")
    @patch("automazioni.services.process_approval_decision")
    def test_poll_marks_read_on_success_path(
        self, mock_process, mock_validate, mock_mark, mock_fetch
    ):
        approval = self._make_approval(approver_emails=["approver@example.com"])
        token_str = str(approval.token)
        mock_fetch.return_value = [self._build_raw_message(token_str, "approvo")]
        mock_validate.return_value = None
        mock_process.return_value = {"ok": True, "approval_id": approval.pk, "actions_run": 0}

        from .mailbox_graph import poll_graph_mailbox
        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=True)

        self.assertEqual(result.processed, 1)
        mock_mark.assert_called_once_with(
            mailbox="mb@example.com",
            graph_message_id=f"GMSG_{token_str[:8]}",
        )

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="1",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    @patch("automazioni.mailbox_graph.mark_message_as_read")
    @patch("automazioni.mailbox_graph._validate_sender")
    def test_poll_does_not_mark_read_on_validation_error(
        self, mock_validate, mock_mark, mock_fetch
    ):
        token = "550e8400-e29b-41d4-a716-446655440004"
        mock_fetch.return_value = [self._build_raw_message(token, "approvo", "hacker@evil.com")]
        mock_validate.return_value = "'hacker@evil.com' non nella lista approvatori"

        from .mailbox_graph import poll_graph_mailbox
        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=True)

        self.assertEqual(result.ignored, 1)
        mock_mark.assert_not_called()

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="1",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    @patch("automazioni.mailbox_graph.mark_message_as_read")
    @patch("automazioni.mailbox_graph._validate_sender")
    @patch("automazioni.services.process_approval_decision")
    def test_poll_does_not_mark_read_on_process_exception(
        self, mock_process, mock_validate, mock_mark, mock_fetch
    ):
        approval = self._make_approval(approver_emails=["approver@example.com"])
        token_str = str(approval.token)
        mock_fetch.return_value = [self._build_raw_message(token_str, "approvo")]
        mock_validate.return_value = None
        mock_process.side_effect = RuntimeError("boom")

        from .mailbox_graph import poll_graph_mailbox
        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=True)

        self.assertEqual(result.error, 1)
        mock_mark.assert_not_called()

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="1",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    @patch("automazioni.mailbox_graph.mark_message_as_read")
    @patch("automazioni.mailbox_graph._validate_sender")
    @patch("automazioni.services.process_approval_decision")
    def test_poll_does_not_mark_read_on_process_error_result(
        self, mock_process, mock_validate, mock_mark, mock_fetch
    ):
        approval = self._make_approval(approver_emails=["approver@example.com"])
        token_str = str(approval.token)
        mock_fetch.return_value = [self._build_raw_message(token_str, "approvo")]
        mock_validate.return_value = None
        mock_process.return_value = {"ok": False, "message": "boom"}

        from .mailbox_graph import poll_graph_mailbox
        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=True)

        self.assertEqual(result.error, 1)
        mock_mark.assert_not_called()

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="10",
        APPROVAL_GRAPH_MARK_READ="0",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages")
    def test_poll_first_valid_decision_wins_in_same_batch(self, mock_fetch):
        approval = self._make_approval(approver_emails=["approver@example.com"])
        token_str = str(approval.token)
        newer_reject = self._build_raw_message(token_str, "rifiuto")
        newer_reject["id"] = "GMSG_NEWER"
        newer_reject["internetMessageId"] = "<newer@example.com>"
        newer_reject["receivedDateTime"] = "2026-04-15T10:05:00Z"

        older_approve = self._build_raw_message(token_str, "approvo")
        older_approve["id"] = "GMSG_OLDER"
        older_approve["internetMessageId"] = "<older@example.com>"
        older_approve["receivedDateTime"] = "2026-04-15T10:00:00Z"

        mock_fetch.return_value = [newer_reject, older_approve]

        from .mailbox_graph import poll_graph_mailbox
        result = poll_graph_mailbox(limit=10, dry_run=False, mark_read=False)

        approval.refresh_from_db()
        self.assertEqual(approval.status, AutomationApproval.Status.APPROVED)
        self.assertEqual(result.processed, 1)
        self.assertEqual(result.approved, 1)
        self.assertEqual(result.rejected, 0)
        self.assertEqual(result.ignored, 1)
        self.assertEqual(result.messages[0]["outcome"], "processed_approved")
        self.assertEqual(result.messages[1]["outcome"], "ignored_already_decided")


class GraphMailboxRuntimeTests(SimpleTestCase):
    """Test del modulo approval_mailbox_runtime per Graph."""

    def test_get_approval_mailbox_backend_default_graph(self):
        from .approval_mailbox_runtime import get_approval_mailbox_backend, MAILBOX_BACKEND_GRAPH
        with override_settings(APPROVAL_MAILBOX_BACKEND="graph"):
            self.assertEqual(get_approval_mailbox_backend(), MAILBOX_BACKEND_GRAPH)

    def test_get_approval_mailbox_backend_imap(self):
        from .approval_mailbox_runtime import get_approval_mailbox_backend, MAILBOX_BACKEND_IMAP
        with override_settings(APPROVAL_MAILBOX_BACKEND="imap"):
            self.assertEqual(get_approval_mailbox_backend(), MAILBOX_BACKEND_IMAP)

    def test_save_approval_graph_settings_writes_env(self):
        import tempfile
        from .approval_mailbox_runtime import save_approval_graph_settings

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            ok, message = save_approval_graph_settings(
                mailbox="approvals@costruzioninovicrom.it",
                folder="Inbox",
                only_unread=True,
                page_size=20,
                mark_read=True,
                dotenv_path=env_path,
            )
            env_text = env_path.read_text(encoding="utf-8")

        self.assertTrue(ok)
        self.assertIn("APPROVAL_MAILBOX_ADDRESS=approvals@costruzioninovicrom.it", env_text)
        self.assertIn("APPROVAL_MAILBOX_FOLDER=Inbox", env_text)
        self.assertIn("APPROVAL_GRAPH_PAGE_SIZE=20", env_text)
        self.assertIn("APPROVAL_MAILBOX_BACKEND=graph", env_text)


class GraphMailboxManagementCommandTests(TestCase):
    """Test del management command process_approval_mailbox."""

    @override_settings(
        GRAPH_TENANT_ID="",
        GRAPH_CLIENT_ID="",
        GRAPH_CLIENT_SECRET="",
        APPROVAL_MAILBOX_ADDRESS="",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    def test_command_fails_if_not_configured(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as ctx:
            call_command("process_approval_mailbox")
        self.assertIn("Configurazione Graph mailbox incompleta", str(ctx.exception))

    @override_settings(
        GRAPH_TENANT_ID="t", GRAPH_CLIENT_ID="c", GRAPH_CLIENT_SECRET="s",
        APPROVAL_MAILBOX_ADDRESS="mb@example.com",
        APPROVAL_MAILBOX_FOLDER="Inbox",
        APPROVAL_GRAPH_ONLY_UNREAD="1",
        APPROVAL_GRAPH_PAGE_SIZE="5",
        APPROVAL_GRAPH_MARK_READ="0",
        APPROVAL_MAILBOX_BACKEND="graph",
    )
    @patch("automazioni.mailbox_graph.fetch_messages", return_value=[])
    def test_command_dry_run_empty_mailbox(self, mock_fetch):
        out = io.StringIO()
        call_command("process_approval_mailbox", "--dry-run", stdout=out)
        output = out.getvalue()
        self.assertIn("read=0", output)


# ─────────────────────────────────────────────────────────────────────────────
# ApprovalSecurityTests — unit test per approval_security.validate_approval_actor
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalSecurityTests(TestCase):
    """
    Unit test per validate_approval_actor() in approval_security.py.
    Verifica tutte le condizioni di deny e il caso allowed.
    """

    from automazioni.approval_security import ErrorCode as _EC

    def _make_approval(self, *, status="pending", expired=False, approver_emails=None):
        from django.utils import timezone as tz
        rule = AutomationRule.objects.create(
            code=f"sec-rule-{id(self)}-{status}",
            name="Security test rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        action = AutomationAction.objects.create(
            rule=rule, order=1,
            action_type=AutomationActionType.SEND_APPROVAL, config_json={},
        )
        run_log = AutomationRunLog.objects.create(
            rule=rule, status=AutomationRunLogStatus.WAITING_APPROVAL,
            payload_json={}, result_message="",
        )
        expires_at = (tz.now() - timedelta(hours=1)) if expired else None
        return AutomationApproval.objects.create(
            run_log=run_log, action=action,
            subject="Test", message="",
            status=status,
            approved_actions=[], rejected_actions=[], resume_payload={},
            approver_emails=approver_emails if approver_emails is not None else [],
            expires_at=expires_at,
        )

    def _validate(self, token_str, actor):
        from automazioni.approval_security import validate_approval_actor
        return validate_approval_actor(str(token_str), actor)

    def test_allowed_when_actor_in_approver_emails(self):
        approval = self._make_approval(approver_emails=["manager@example.com"])
        result = self._validate(approval.token, "manager@example.com")
        self.assertTrue(result.allowed)
        self.assertEqual(result.approval_id, approval.pk)

    def test_allowed_case_insensitive(self):
        approval = self._make_approval(approver_emails=["Manager@Example.COM"])
        result = self._validate(approval.token, "manager@example.com")
        self.assertTrue(result.allowed)

    def test_deny_no_identity(self):
        approval = self._make_approval(approver_emails=["m@example.com"])
        result = self._validate(approval.token, "")
        self.assertFalse(result.allowed)
        self.assertEqual(result.error_code, "no_identity")

    def test_deny_invalid_uuid(self):
        from automazioni.approval_security import validate_approval_actor
        result = validate_approval_actor("not-a-uuid", "m@example.com")
        self.assertFalse(result.allowed)
        self.assertEqual(result.error_code, "invalid_token")

    def test_deny_not_found(self):
        result = self._validate("00000000-0000-0000-0000-000000000000", "m@example.com")
        self.assertFalse(result.allowed)
        self.assertEqual(result.error_code, "not_found")

    def test_deny_already_decided(self):
        approval = self._make_approval(status="approved", approver_emails=["m@example.com"])
        result = self._validate(approval.token, "m@example.com")
        self.assertFalse(result.allowed)
        self.assertEqual(result.error_code, "already_decided")
        self.assertEqual(result.approval_id, approval.pk)

    def test_deny_expired(self):
        approval = self._make_approval(expired=True, approver_emails=["m@example.com"])
        result = self._validate(approval.token, "m@example.com")
        self.assertFalse(result.allowed)
        self.assertEqual(result.error_code, "expired")

    def test_deny_no_approvers_configured(self):
        approval = self._make_approval(approver_emails=[])
        result = self._validate(approval.token, "m@example.com")
        self.assertFalse(result.allowed)
        self.assertEqual(result.error_code, "no_approvers")

    def test_deny_unauthorized_actor(self):
        approval = self._make_approval(approver_emails=["allowed@example.com"])
        result = self._validate(approval.token, "intruder@example.com")
        self.assertFalse(result.allowed)
        self.assertEqual(result.error_code, "unauthorized")

    def test_mailbox_graph_validate_sender_retrocompat(self):
        """_validate_sender in mailbox_graph delega a validate_approval_actor."""
        from automazioni.mailbox_graph import _validate_sender
        approval = self._make_approval(approver_emails=["sender@example.com"])
        # Authorized sender → None (no error)
        self.assertIsNone(_validate_sender(str(approval.token), "sender@example.com"))
        # Unauthorized sender → error string
        err = _validate_sender(str(approval.token), "intruder@example.com")
        self.assertIsNotNone(err)
        self.assertIn("intruder@example.com", err)
        # Missing sender → error string
        err2 = _validate_sender(str(approval.token), "")
        self.assertIsNotNone(err2)


# ─────────────────────────────────────────────────────────────────────────────
# Approval Proxy endpoint tests (/approval-actions/approve|reject/<token>/)
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalProxyEndpointTests(TestCase):
    """
    Test degli endpoint GET /approval-actions/approve|reject/<token>/.

    L'endpoint ora valida l'attore via validate_approval_actor() prima di
    chiamare process_approval_decision(). Fail-closed:
      - identità vuota → NO_IDENTITY (bloccato)
      - attore non in approver_emails → UNAUTHORIZED (bloccato)
      - approval già decisa / scaduta → bloccato prima del processing
    """

    ACTOR = "approver@example.com"

    def _make_approval(self, *, status="pending", expired=False, approver_emails=None):
        from django.utils import timezone as tz
        rule = AutomationRule.objects.create(
            code=f"proxy-ep-rule-{id(self)}-{status}",
            name="Proxy endpoint test rule",
            source_code="assenze",
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_scope=AutomationRuleTriggerScope.ALL_UPDATES,
        )
        action = AutomationAction.objects.create(
            rule=rule, order=1,
            action_type=AutomationActionType.SEND_APPROVAL, config_json={},
        )
        run_log = AutomationRunLog.objects.create(
            rule=rule, status=AutomationRunLogStatus.WAITING_APPROVAL,
            payload_json={}, result_message="",
        )
        expires_at = (tz.now() - timedelta(hours=1)) if expired else None
        return AutomationApproval.objects.create(
            run_log=run_log, action=action,
            subject="Test approval", message="",
            status=status,
            approved_actions=[], rejected_actions=[], resume_payload={},
            approver_emails=approver_emails if approver_emails is not None else [self.ACTOR],
            expires_at=expires_at,
        )

    # ── Happy path: attore autorizzato ───────────────────────────────────────

    def test_approve_authorized_actor_get_requires_confirmation(self):
        approval = self._make_approval()
        response = self.client.get(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Conferma Approvazione")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "pending")

    def test_approve_authorized_actor_post_succeeds(self):
        approval = self._make_approval()
        response = self.client.post(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Richiesta Approvata")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "approved")

    def test_second_post_does_not_overwrite_processed_decision(self):
        approval = self._make_approval()
        first = self.client.post(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        second = self.client.post(
            f"/approval-actions/reject/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "Richiesta gi")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "approved")
        self.assertEqual(approval.decided_by_email, self.ACTOR)

    def test_reject_authorized_actor_post_succeeds(self):
        approval = self._make_approval()
        response = self.client.post(
            f"/approval-actions/reject/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Richiesta Rifiutata")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "rejected")

    # ── Estrazione identità ──────────────────────────────────────────────────

    def test_identity_from_django_session(self):
        user = User.objects.create_user(
            username="proxy.user", email=self.ACTOR, password="test"
        )
        approval = self._make_approval()
        self.client.force_login(user)
        self.client.post(f"/approval-actions/approve/{approval.token}/")
        approval.refresh_from_db()
        self.assertEqual(approval.decided_by_email, self.ACTOR)

    def test_identity_from_entra_principal_header(self):
        approval = self._make_approval()
        self.client.post(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        approval.refresh_from_db()
        self.assertEqual(approval.decided_by_email, self.ACTOR)

    def test_identity_from_forwarded_email_header(self):
        approval = self._make_approval()
        self.client.post(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_FORWARDED_EMAIL=self.ACTOR,
        )
        approval.refresh_from_db()
        self.assertEqual(approval.decided_by_email, self.ACTOR)

    def test_session_identity_takes_priority_over_entra_header(self):
        user = User.objects.create_user(
            username="session.user", email=self.ACTOR, password="test"
        )
        approval = self._make_approval()
        self.client.force_login(user)
        self.client.post(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME="entra.ignored@corp.local",
        )
        approval.refresh_from_db()
        self.assertEqual(approval.decided_by_email, self.ACTOR)

    # ── Blocchi di sicurezza: approval status ────────────────────────────────

    def test_not_found_token_shows_denied_page(self):
        fake_token = "00000000-0000-0000-0000-000000000000"
        response = self.client.get(
            f"/approval-actions/approve/{fake_token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Link non valido")
        self.assertIn(b'data-error-code="not_found"', response.content)

    def test_already_decided_shows_denied_page(self):
        approval = self._make_approval(status="approved")
        response = self.client.get(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Richiesta già elaborata")
        self.assertIn(b'data-error-code="already_decided"', response.content)

    def test_expired_shows_denied_page(self):
        approval = self._make_approval(expired=True)
        response = self.client.get(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Richiesta scaduta")
        self.assertIn(b'data-error-code="expired"', response.content)

    def test_expired_post_is_blocked(self):
        approval = self._make_approval(expired=True)
        response = self.client.post(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Richiesta scaduta")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "pending")

    # ── Blocchi di sicurezza: identità / autorizzazione ──────────────────────

    def test_empty_identity_blocked_with_no_identity_page(self):
        """Nessuna sessione, nessun header → NO_IDENTITY, approval non toccata."""
        approval = self._make_approval()
        response = self.client.get(f"/approval-actions/approve/{approval.token}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Identità non disponibile")
        self.assertIn(b'data-error-code="no_identity"', response.content)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "pending")  # immutato

    def test_unauthorized_actor_blocked(self):
        """Attore presente ma non in approver_emails → UNAUTHORIZED, approval non toccata."""
        approval = self._make_approval(approver_emails=["allowed@example.com"])
        response = self.client.get(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME="intruder@example.com",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Utente non autorizzato")
        self.assertIn(b'data-error-code="unauthorized"', response.content)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "pending")  # immutato

    def test_actor_removed_before_post_is_blocked(self):
        approval = self._make_approval()
        get_response = self.client.get(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )
        self.assertEqual(get_response.status_code, 200)
        approval.approver_emails = ["other@example.com"]
        approval.save(update_fields=["approver_emails"])

        post_response = self.client.post(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME=self.ACTOR,
        )

        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Utente non autorizzato")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "pending")

    def test_no_approvers_configured_blocks_any_actor(self):
        """approver_emails vuota → NO_APPROVERS (fail-closed), anche con attore valido."""
        approval = self._make_approval(approver_emails=[])
        response = self.client.get(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME="anyone@example.com",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configurazione non valida")
        self.assertIn(b'data-error-code="no_approvers"', response.content)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "pending")

    # ── POST method not allowed ──────────────────────────────────────────────

    def test_post_without_identity_is_denied(self):
        approval = self._make_approval()
        response = self.client.post(f"/approval-actions/approve/{approval.token}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Identit")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "pending")

    # ── Audit log ────────────────────────────────────────────────────────────

    def test_audit_log_written_on_successful_approve(self):
        from core.models import AuditLog
        user = User.objects.create_user(
            username="audit.approve", email=self.ACTOR, password="test"
        )
        approval = self._make_approval()
        self.client.force_login(user)
        self.client.post(f"/approval-actions/approve/{approval.token}/")

        entry = AuditLog.objects.filter(azione="approval_proxy_decision", modulo="automazioni").last()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.dettaglio["decision"], "approved")
        self.assertEqual(entry.dettaglio["via"], "entra_proxy")
        self.assertTrue(entry.dettaglio["ok"])

    def test_audit_log_written_on_successful_reject(self):
        from core.models import AuditLog
        user = User.objects.create_user(
            username="audit.reject", email=self.ACTOR, password="test"
        )
        approval = self._make_approval()
        self.client.force_login(user)
        self.client.post(f"/approval-actions/reject/{approval.token}/")

        entry = AuditLog.objects.filter(azione="approval_proxy_decision", modulo="automazioni").last()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.dettaglio["decision"], "rejected")
        self.assertTrue(entry.dettaglio["ok"])

    def test_audit_denial_logged_when_not_found(self):
        """Token non trovato → azione 'approval_proxy_denied' con error_code not_found."""
        from core.models import AuditLog
        user = User.objects.create_user(
            username="audit.denied", email=self.ACTOR, password="test"
        )
        fake_token = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        self.client.force_login(user)
        self.client.post(f"/approval-actions/approve/{fake_token}/")

        entry = AuditLog.objects.filter(azione="approval_proxy_denied", modulo="automazioni").last()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.dettaglio["error_code"], "not_found")
        self.assertEqual(entry.dettaglio["via"], "entra_proxy")

    def test_audit_denial_logged_when_unauthorized(self):
        """Attore non autorizzato → azione 'approval_proxy_denied' con error_code unauthorized."""
        from core.models import AuditLog
        approval = self._make_approval(approver_emails=["allowed@example.com"])
        user = User.objects.create_user(
            username="audit.unauth", email="intruder@example.com", password="test"
        )
        self.client.force_login(user)
        self.client.post(f"/approval-actions/approve/{approval.token}/")

        entry = AuditLog.objects.filter(azione="approval_proxy_denied", modulo="automazioni").last()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.dettaglio["error_code"], "unauthorized")

    def test_audit_log_works_with_anonymous_entra_header(self):
        """
        Nessuna sessione Django, identità da header Entra:
        log_action non deve crashare (display_name_for_user ora gestisce AnonymousUser).
        """
        from core.models import AuditLog
        approval = self._make_approval(approver_emails=["entra.ok@corp.local"])
        self.client.post(
            f"/approval-actions/approve/{approval.token}/",
            HTTP_X_MS_CLIENT_PRINCIPAL_NAME="entra.ok@corp.local",
        )
        entry = AuditLog.objects.filter(azione="approval_proxy_decision", modulo="automazioni").last()
        self.assertIsNotNone(entry)
        self.assertTrue(entry.dettaglio["ok"])
        self.assertEqual(entry.dettaglio["actor"], "entra.ok@corp.local")
