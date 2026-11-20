"""Cancellazioni sicure: categorie ancora usate, applicazioni doppie. Dati sintetici."""

from __future__ import annotations

from django.test import TestCase, override_settings

from assets.forms_maintenance import MaintenancePlanAssignmentForm
from assets.models import (
    AssetCategory,
    AssetCategoryField,
    MaintenanceInterventionTemplate,
    MaintenancePlanAssignment,
)
from assets.views._helpers_c import _category_delete_blockers


@override_settings(LEGACY_AUTH_ENABLED=False)
class CancellazioniSicureTests(TestCase):
    def setUp(self):
        self.cat = AssetCategory.objects.create(code="cs-cat", label="Compressori")
        self.plan = MaintenanceInterventionTemplate.objects.create(code="cs-olio", label="Olio")

    def test_categoria_libera_si_puo_eliminare(self):
        AssetCategoryField.objects.create(category=self.cat, code="cs-campo", label="Campo")
        self.assertEqual(_category_delete_blockers(self.cat), [])

    def test_categoria_con_sottocategoria_o_applicazione_bloccata(self):
        AssetCategory.objects.create(code="cs-figlia", label="Compressori a vite", parent=self.cat)
        MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type="CATEGORY", asset_category=self.cat, frequency="DAYS", interval=30,
        )
        blockers = " ".join(_category_delete_blockers(self.cat))
        self.assertIn("(1)", blockers)
        self.assertEqual(len(_category_delete_blockers(self.cat)), 2)

    def test_applicazione_doppia_anche_se_disattivata_rifiutata(self):
        MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type="CATEGORY", asset_category=self.cat, frequency="DAYS", interval=30,
            is_active=False,
        )
        form = MaintenancePlanAssignmentForm(
            data={"target_type": "CATEGORY", "asset_category": self.cat.pk, "frequency": "DAYS", "interval": 30,
                  "warning_days": 30},
            plan=self.plan,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("già applicato", str(form.errors))
