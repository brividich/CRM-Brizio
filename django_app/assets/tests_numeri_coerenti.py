"""Numeri coerenti fra le pagine della manutenzione. Dati sintetici."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetAdministrativeDeadline,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    WorkOrder,
)
from assets.services import deadline_feed as feed

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class NumeriCoerentiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="numeri", password="x", email="n@example.com")
        cls.asset = Asset.objects.create(asset_tag="NUM01", name="Pressa", status=Asset.STATUS_IN_USE)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="num-olio", label="Cambio olio")

    def setUp(self):
        self.client.force_login(self.admin)
        self.today = timezone.localdate()

    def _admin_rows(self):
        return feed.collect(
            start=None, end=self.today + timedelta(days=60),
            filters=feed.FeedFilters(kinds=frozenset({feed.KIND_ADMINISTRATIVE})), today=self.today,
        )

    def test_preavviso_zero_resta_zero(self):
        AssetAdministrativeDeadline.objects.create(
            asset=self.asset, title="Revisione", due_date=self.today + timedelta(days=10), warning_days=0,
        )
        rows = [r for r in self._admin_rows() if r.title == "Revisione"]
        self.assertEqual(rows[0].state, feed.STATE_OPEN)

    def test_scadenze_di_asset_dismessi_fuori_dallo_scadenzario(self):
        retired = Asset.objects.create(asset_tag="NUM-R", name="Vecchia", status=Asset.STATUS_RETIRED)
        AssetAdministrativeDeadline.objects.create(asset=retired, title="Polizza", due_date=self.today)
        self.assertFalse([r for r in self._admin_rows() if r.title == "Polizza"])
        # Stesso criterio dei cruscotti.
        self.assertFalse([d for d in feed.administrative_dues() if d.title == "Polizza"])

    def test_controlli_dopo_intervento_contati_tutti(self):
        occ = MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today)
        for i in range(52):
            WorkOrder.objects.create(asset=self.asset, title=f"Verifica {i}", follow_up_occurrence=occ)
        response = self.client.get(reverse("assets:maintenance_responsabile"))
        self.assertEqual(response.context["kpi"]["follow_ups"], 52)

    def test_da_fare_dichiara_la_lista_tagliata(self):
        assignment = MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type="ASSET", asset=self.asset, frequency="DAYS", interval=30,
        )
        for days in (1, 2, 3):
            MaintenanceOccurrence.objects.create(
                plan=self.plan, assignment=assignment, asset=self.asset, due_date=self.today - timedelta(days=days),
            )
        with mock.patch("assets.views_maintenance.DA_FARE_MAX_RIGHE", 2):
            response = self.client.get(reverse("assets:maintenance_da_fare"), {"mio": "0"})
        self.assertTrue(response.context["rows_truncated"])
        self.assertEqual(response.context["rows_total"], 3)
        self.assertContains(response, "Mostrate le prime 2 manutenzioni su 3")

    def test_mie_attivita_usa_il_nome_del_piano(self):
        from dashboard.mie_attivita_fonti import _manutenzioni

        MaintenanceInterventionTemplate.objects.filter(pk=self.plan.pk).update(default_assignee=self.admin)
        MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today)
        righe = _manutenzioni(self.admin)
        self.assertEqual(righe[0]["title"], "Cambio olio")
