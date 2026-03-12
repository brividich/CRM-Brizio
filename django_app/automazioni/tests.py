from __future__ import annotations

from decimal import Decimal
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AutomationAction,
    AutomationActionLog,
    AutomationActionLogStatus,
    AutomationActionType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationConditionValueType,
    AutomationRule,
    AutomationRuleOperationType,
    AutomationRuleTriggerScope,
    AutomationRunLog,
    AutomationRunLogStatus,
    DashboardMetricValue,
)
from .services import (
    execute_action,
    execute_safe_insert,
    execute_safe_update,
    find_matching_rules,
    evaluate_condition,
    process_pending_queue_events,
    process_queue_event,
    render_template_string,
    run_rule,
    safe_get_payload_value,
)
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
        self.assertEqual([source["code"] for source in sources], ["assenze", "tasks", "assets", "tickets", "anomalie"])

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
                ("tasks", "Tasks"),
                ("assets", "Assets"),
                ("tickets", "Tickets"),
                ("anomalie", "Anomalie"),
            ],
        )

    def test_acl_action_contract_is_declared(self):
        self.assertEqual(
            AUTOMAZIONI_ACL_ACTIONS,
            ("automazioni_view", "automazioni_manage", "automazioni_logs", "automazioni_execute"),
        )


class SourceRegistryFieldFilterTests(SimpleTestCase):
    def test_trigger_condition_template_and_action_fields_are_filtered(self):
        source_fields = get_source_fields("assenze")
        trigger_fields = get_trigger_fields("assenze")
        condition_fields = get_condition_fields("assenze")
        template_fields = get_template_fields("assenze")
        action_mapping_fields = get_action_mapping_fields("assenze")

        self.assertEqual(len(source_fields), 9)
        self.assertEqual([field["name"] for field in trigger_fields], [field["name"] for field in source_fields])
        self.assertEqual([field["name"] for field in condition_fields], [field["name"] for field in source_fields])
        self.assertEqual([field["name"] for field in template_fields], [field["name"] for field in source_fields])
        self.assertEqual([field["name"] for field in action_mapping_fields], [field["name"] for field in source_fields])
        self.assertIn("capo_email", [field["name"] for field in template_fields])

    def test_unknown_source_returns_empty_field_sets(self):
        self.assertEqual(get_source_fields("missing"), [])
        self.assertEqual(get_trigger_fields("missing"), [])
        self.assertEqual(get_condition_fields("missing"), [])
        self.assertEqual(get_template_fields("missing"), [])
        self.assertEqual(get_action_mapping_fields("missing"), [])

    def test_placeholder_examples_are_generated_from_template_fields(self):
        self.assertEqual(
            build_placeholder_examples("tasks"),
            ["{id}", "{title}", "{status}", "{priority}", "{assigned_to_id}", "{project_id}", "{due_date}"],
        )
        self.assertIn("{capo_email}", build_placeholder_examples("assenze"))
        self.assertEqual(build_placeholder_examples("missing"), [])


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
        self.client.force_login(self.user)
        self.legacy_admin = SimpleNamespace(id=1, ruolo_id=1, nome="Admin Automazioni")

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
            "conditions-TOTAL_FORMS": "2",
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
            "conditions-1-order": "",
            "conditions-1-field_name": "",
            "conditions-1-operator": "",
            "conditions-1-expected_value": "",
            "conditions-1-value_type": "",
            "conditions-1-compare_with_old": "",
            "conditions-1-is_enabled": "",
            "actions-TOTAL_FORMS": "2",
            "actions-INITIAL_FORMS": "0",
            "actions-MIN_NUM_FORMS": "0",
            "actions-MAX_NUM_FORMS": "1000",
            "actions-0-order": "1",
            "actions-0-action_type": "write_log",
            "actions-0-is_enabled": "on",
            "actions-0-description": "Scrive un log operativo",
            "actions-0-write_log_message_template": "Assenza approvata #{id}",
            "actions-1-order": "",
            "actions-1-action_type": "",
            "actions-1-is_enabled": "",
            "actions-1-description": "",
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
        self.assertEqual(len(response.context["sources"]), 5)

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
    def test_rule_designer_create_page_renders(self, mock_get_legacy_user, _mock_is_admin):
        mock_get_legacy_user.return_value = self.legacy_admin

        response = self.client.get(reverse("admin_portale:automazioni_rule_designer_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Designer visuale")
        self.assertContains(response, "Nuova regola")
        self.assertContains(response, "Contenuti / Colonne disponibili")
        self.assertContains(response, "Campi suggeriti")

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

    @patch("automazioni.views.count_queue_by_status")
    @patch("automazioni.views.list_queue_events")
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_list_page_renders_with_filters(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_list_queue_events,
        mock_count_queue_by_status,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
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

    @patch("automazioni.views.get_queue_event_detail")
    @patch("admin_portale.decorators.is_legacy_admin", return_value=True)
    @patch("admin_portale.decorators.get_legacy_user")
    def test_queue_detail_page_renders_payload_and_linked_logs(
        self,
        mock_get_legacy_user,
        _mock_is_admin,
        mock_get_queue_event_detail,
    ):
        mock_get_legacy_user.return_value = self.legacy_admin
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
        self.assertContains(response, "moderation_status")
        self.assertContains(response, "Run OK")
        self.assertContains(response, "Action OK")
        self.assertContains(response, "runtime error")

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
        self.assertNotContains(response, f"#{other_run.id}")

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


class AutomationServiceHelperTests(SimpleTestCase):
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


class AutomationDatabaseExecutorTests(TestCase):
    def setUp(self):
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
        ):
            result = execute_safe_update(
                "tasks_task",
                {
                    "status": "DONE",
                    "next_step_text": "Aggiornato da automazione #42",
                },
                "id",
                "14",
            )

        self.assertEqual(result["rowcount"], 2)
        sql, params = cursor.execute.call_args.args
        self.assertIn("UPDATE", sql)
        self.assertIn("WHERE", sql)
        self.assertIn("%s", sql)
        self.assertEqual(params, ["DONE", "Aggiornato da automazione #42", "14"])


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

        call_command("process_automation_queue", "--limit=5", "--source-code=assenze", stdout=stdout)

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

        call_command("process_automation_queue", "--dry-run", stdout=stdout)

        mock_process.assert_called_once_with(limit=50, source_code=None, dry_run=True)
        self.assertIn("candidate_rules=rule-a", stdout.getvalue())
