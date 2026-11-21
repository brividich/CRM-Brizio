"""«Scadute» = data passata, anche se la manutenzione e' gia' in un OdL aperto.

Panoramica e Da fare contano come lo Scadenzario (window=overdue). Dati sintetici.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    WorkOrder,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class ScaduteInOdlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="scad", password="x", email="s@example.com")
        cls.asset = Asset.objects.create(asset_tag="SCA01", name="Tornio", status=Asset.STATUS_IN_USE)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="sca-ingr", label="Ingrassaggio")
        cls.assignment = MaintenancePlanAssignment.objects.create(
            plan=cls.plan, target_type="ASSET", asset=cls.asset, frequency="DAYS", interval=30,
        )
        today = timezone.localdate()
        cls.wo = WorkOrder.objects.create(asset=cls.asset, title="Intervento programmato")
        # Una scaduta gia' nell'OdL, una scaduta senza OdL, una futura nell'OdL.
        cls.late_in_wo = MaintenanceOccurrence.objects.create(
            plan=cls.plan, assignment=cls.assignment, asset=cls.asset,
            due_date=today - timedelta(days=5), work_order=cls.wo,
        )
        cls.late_free = MaintenanceOccurrence.objects.create(
            plan=cls.plan, assignment=cls.assignment, asset=cls.asset, due_date=today - timedelta(days=2),
        )
        cls.future_in_wo = MaintenanceOccurrence.objects.create(
            plan=cls.plan, assignment=cls.assignment, asset=cls.asset,
            due_date=today + timedelta(days=20), work_order=cls.wo,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def _ids(self, rows):
        return {row["occurrence"].id for row in rows}

    def test_da_fare_scaduta_in_odl_va_in_scadute_non_in_programmate(self):
        response = self.client.get(reverse("assets:maintenance_da_fare"), {"mio": "0"})
        blocks = {block["key"]: block for block in response.context["blocks"]}
        self.assertEqual(self._ids(blocks["overdue"]["rows"]), {self.late_in_wo.id, self.late_free.id})
        self.assertEqual(self._ids(blocks["planned"]["rows"]), {self.future_in_wo.id})
        self.assertEqual(response.context["summary"]["overdue"], 2)
        # Il riferimento all'OdL resta visibile sulla riga.
        self.assertContains(response, f"OdL n. {self.wo.id}")

    def test_panoramica_conta_le_scadute_in_odl(self):
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        self.assertEqual(response.context["kpi"]["overdue"], 2)
        self.assertEqual(response.context["headline"]["scadute"], 2)
        # «Non pianificate» resta solo per quelle senza OdL.
        self.assertEqual(response.context["kpi"]["unplanned"], 1)
        tipi = {t["kind"]: t for t in response.context["panoramica"]["types"]}
        self.assertEqual(tipi["ordinary"]["overdue"], 2)

    def test_coincide_con_lo_scadenzario(self):
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        today = timezone.localdate()
        scadenzario = MaintenanceOccurrence.objects.filter(
            status=MaintenanceOccurrence.STATUS_OPEN, due_date__lt=today
        ).count()
        self.assertEqual(response.context["kpi"]["overdue"], scadenzario)
