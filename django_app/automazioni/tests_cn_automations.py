"""CN Automations: le regole esistenti (condizioni, Se sì / Se no, Ripeti finché) si aprono e restano identiche."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from automazioni.forms import AutomationActionForm
from automazioni.models import (
    AutomationAction,
    AutomationActionType,
    AutomationCondition,
    AutomationConditionOperator,
    AutomationRule,
)

VERO = [{"action_type": "write_log", "description": "Log sì", "config_json": {"message_template": "ok {id}"}}]
FALSO = [{"action_type": "send_email", "description": "Avvisa", "config_json": {"to": "a@x.local", "subject_template": "KO {id}", "body_text_template": "No"}}]


class RegoleEsistentiTests(TestCase):
    def setUp(self):
        self.rule = AutomationRule.objects.create(code="cn-prova", name="Prova CN", source_code="assenze",
                                                  operation_type="update", trigger_scope="all_updates",
                                                  is_active=False, is_draft=True)
        AutomationCondition.objects.create(rule=self.rule, order=1, field_name="id", operator="is_not_empty",
                                           expected_value="", value_type="string", is_enabled=True)
        self.branch = AutomationAction.objects.create(
            rule=self.rule, order=1, action_type=AutomationActionType.BRANCH, is_enabled=True,
            config_json={"condition_field": "id", "condition_operator": "equals", "condition_value": "1",
                         "condition_value_type": "string", "compare_with_old": False,
                         "if_true_actions": VERO, "if_false_actions": FALSO})
        self.client.force_login(get_user_model().objects.create_superuser("cn_admin", "cn@x.local", "x"))

    def test_designer_mostra_rami_e_righe_di_condizione(self):
        r = self.client.get(reverse("admin_portale:automazioni_rule_designer", args=[self.rule.id]))
        self.assertEqual(r.status_code, 200)
        for testo in ("✓ Se sì", "✕ Se no", "Ripeti finché questa condizione non è vera", "+ Aggiungi riga",
                      "Condizione · tutte vere", 'data-inline-json-add="update_trigger_record"'):
            self.assertContains(r, testo)

    def test_rami_salvati_restano_identici(self):
        form = AutomationActionForm(instance=self.branch, source_code="assenze")
        self.assertEqual(json.loads(form.initial["branch_if_true_actions_json"]), VERO)
        self.assertEqual(json.loads(form.initial["branch_if_false_actions_json"]), FALSO)

    def test_operatori_cambiano_solo_etichetta(self):
        self.assertEqual(AutomationConditionOperator.IS_NOT_EMPTY.value, "is_not_empty")
        self.assertEqual(AutomationConditionOperator.IS_NOT_EMPTY.label, "non è vuoto")
        self.assertEqual(AutomationActionType.BRANCH.value, "branch")
