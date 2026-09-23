"""Flusso della manutenzione dall'inizio alla fine: applicare un piano, vedere le
scadenze, registrare e tornare dove si era. Dall'audit dei link del 23/09/2026."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class FlussoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="flow-admin", password="x", email="f@l.w")
        cls.category = AssetCategory.objects.create(code="flow-cat", label="Flow")
        cls.asset = Asset.objects.create(asset_tag="FLOW-1", name="Pressa", asset_category=cls.category,
                                         status=Asset.STATUS_IN_USE)
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="flow-plan", label="Ingrassaggio flow")

    def setUp(self):
        self.client.force_login(self.admin)

    def _apply(self, first_due):
        return self.client.post(
            reverse("assets:maintenance_assignment_create", args=[self.plan.id]),
            {
                "target_type": MaintenancePlanAssignment.TARGET_CATEGORY,
                "asset_category": self.category.id,
                "frequency": MaintenancePlanAssignment.FREQ_DAYS,
                "interval": 30,
                "warning_days": 15,
                "first_due_date": first_due.isoformat(),
                "schedule_anchor": MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
                "auto_generate": "on",
                "is_active": "on",
            },
            follow=True,
        )

    def test_applicare_un_piano_crea_subito_le_scadenze_in_preavviso(self):
        response = self._apply(self.today + timedelta(days=5))
        self.assertTrue(MaintenancePlanAssignment.objects.filter(plan=self.plan).exists(), response.content[:500])
        self.assertTrue(MaintenanceOccurrence.objects.filter(plan=self.plan, asset=self.asset).exists())
        self.assertContains(response, "1 scadenza creata ora")

    def test_scadenza_lontana_compare_come_prevista_nel_calendario(self):
        self._apply(self.today + timedelta(days=60))
        self.assertFalse(MaintenanceOccurrence.objects.filter(plan=self.plan).exists())
        events = self.client.get(
            reverse("assets:calendario_asset_json"),
            {"start": self.today.isoformat(), "end": (self.today + timedelta(days=130)).isoformat()},
        ).json()["events"]
        forecasts = [e for e in events if e["state"] == "forecast" and e["title"] == "Ingrassaggio flow"]
        # La serie continua: 60, 90, 120 giorni.
        self.assertGreaterEqual(len(forecasts), 3)
        self.assertFalse(any(e.get("movable") or e.get("plannable") for e in forecasts))
        spente = self.client.get(
            reverse("assets:calendario_asset_json"),
            {"start": self.today.isoformat(), "end": (self.today + timedelta(days=130)).isoformat(), "forecast": "0"},
        ).json()["events"]
        self.assertFalse(any(e["state"] == "forecast" for e in spente))

    def test_registrare_riporta_alla_pagina_di_partenza(self):
        occ = MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today, warning_days=10)
        partenza = reverse("assets:calendario_asset") + "?kinds=ordinary"
        page = self.client.get(reverse("assets:occurrence_complete", args=[occ.id]), HTTP_REFERER="http://testserver" + partenza)
        self.assertContains(page, f'value="http://testserver{partenza}"', html=False)
        response = self.client.post(
            reverse("assets:occurrence_complete", args=[occ.id]),
            {"completed_on": self.today.isoformat(), "next": partenza},
        )
        self.assertRedirects(response, partenza, fetch_redirect_response=False)
        # Un "next" esterno non viene mai seguito.
        occ2 = MaintenanceOccurrence.objects.create(plan=self.plan, asset=self.asset, due_date=self.today + timedelta(days=1), warning_days=10)
        response = self.client.post(
            reverse("assets:occurrence_complete", args=[occ2.id]),
            {"completed_on": self.today.isoformat(), "next": "https://evil.example/"},
        )
        self.assertEqual(response["Location"], reverse("assets:maintenance_da_fare"))

    def test_link_della_scheda_asset_vanno_alle_pagine_nuove(self):
        from assets.views import _asset_maintenance_rule_list_page_url, _maintenance_schedule_page_url

        self.assertEqual(
            _maintenance_schedule_page_url(asset_id=self.asset.id, status="due"),
            f"{reverse('assets:maintenance_scadenze')}?asset={self.asset.id}&window=30",
        )
        self.assertEqual(
            _asset_maintenance_rule_list_page_url(self.asset.id),
            reverse("assets:asset_maintenance_plans", args=[self.asset.id]),
        )
