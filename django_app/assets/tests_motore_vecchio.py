"""Motore vecchio spento: regole portate nei piani, prossima manutenzione dalle occorrenze. Dati sintetici."""

from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    MaintenanceRule,
    WorkMachine,
)
from assets.services.maintenance_domain import prossime_scadenze_per_asset
from assets.views._helpers_b import _prossima_manutenzione
from assets.views.maintenance_legacy import _porta_regole_nei_piani


class MotoreVecchioTests(TestCase):
    def setUp(self):
        self.cat = AssetCategory.objects.create(code="mv-cat", label="Compressori")
        self.asset = Asset.objects.create(asset_tag="MV01", name="Compressore", asset_category=self.cat,
                                          status=Asset.STATUS_IN_USE)
        self.plan_a = MaintenanceInterventionTemplate.objects.create(code="mv-a", label="Filtri")
        self.plan_b = MaintenanceInterventionTemplate.objects.create(code="mv-b", label="Cinghie")
        self.rule_a = MaintenanceRule.objects.create(
            intervention_template=self.plan_a, asset_category=self.cat, threshold_value=30,
            first_due_date=timezone.localdate() + timedelta(days=3),
        )
        self.rule_b = MaintenanceRule.objects.create(
            intervention_template=self.plan_b, asset_category=self.cat, threshold_value=60,
        )

    def test_rule_id_converte_solo_le_regole_indicate(self):
        call_command("migrate_maintenance_to_plans", rule_ids=[self.rule_a.id], stdout=StringIO())
        self.assertTrue(MaintenancePlanAssignment.objects.filter(legacy_rule=self.rule_a).exists())
        self.assertFalse(MaintenancePlanAssignment.objects.filter(legacy_rule=self.rule_b).exists())

    def test_ingloba_porta_la_regola_nei_piani_con_le_scadenze(self):
        plan_ids = _porta_regole_nei_piani([self.rule_a])
        self.assertEqual(plan_ids, {self.plan_a.id})
        self.assertTrue(
            MaintenanceOccurrence.objects.filter(plan=self.plan_a, asset=self.asset,
                                                 status=MaintenanceOccurrence.STATUS_OPEN).exists()
        )
        # Idempotente: una seconda volta non duplica l'applicazione.
        _porta_regole_nei_piani([self.rule_a])
        self.assertEqual(MaintenancePlanAssignment.objects.filter(legacy_rule=self.rule_a).count(), 1)

    def test_prossima_manutenzione_dalle_occorrenze(self):
        machine = WorkMachine.objects.create(asset=self.asset, source_key="mv-1", next_maintenance_date=date(2020, 1, 1))
        self.assertEqual(_prossima_manutenzione(self.asset, machine), date(2020, 1, 1))
        due = timezone.localdate() + timedelta(days=9)
        MaintenanceOccurrence.objects.create(plan=self.plan_a, asset=self.asset, due_date=due)
        MaintenanceOccurrence.objects.create(plan=self.plan_b, asset=self.asset, due_date=due + timedelta(days=5))
        self.assertEqual(prossime_scadenze_per_asset([self.asset.id]), {self.asset.id: due})
        self.assertEqual(_prossima_manutenzione(self.asset, machine), due)
