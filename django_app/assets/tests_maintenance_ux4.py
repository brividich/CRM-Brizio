"""Manutenzione round 3: calendario gestibile, "Cosa posso fare qui", tour guidati."""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.maintenance_nav import HELP_TEXTS, MAINTENANCE_NAV
from assets.models import Asset, MaintenanceInterventionTemplate, MaintenanceOccurrence

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class SpostaScadenzaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="ux4-admin", password="x", email="x@y.z")
        cls.asset = Asset.objects.create(asset_tag="UX4-01", name="Pressa")
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="ux4-p", label="Controllo ux4")

    def setUp(self):
        self.client.force_login(self.admin)
        self.occ = MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today + timedelta(days=3), warning_days=10
        )

    def _move(self, occ_id, iso):
        return self.client.post(reverse("assets:occurrence_reschedule", args=[occ_id]), {"due_date": iso})

    def test_sposta_e_scrive_audit(self):
        from core.models import AuditLog

        nuova = self.today + timedelta(days=9)
        response = self._move(self.occ.id, nuova.isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["old_date"], (self.today + timedelta(days=3)).isoformat())
        self.occ.refresh_from_db()
        self.assertEqual(self.occ.due_date, nuova)
        self.assertTrue(AuditLog.objects.filter(azione="ASSET_OCCORRENZA_SPOSTATA", oggetto_id=str(self.occ.id)).exists())

    def test_rifiuti(self):
        self.assertEqual(self._move(self.occ.id, "non-una-data").status_code, 400)
        MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today - timedelta(days=30), warning_days=10,
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=self.today - timedelta(days=30),
        )
        self.assertEqual(self._move(self.occ.id, (self.today - timedelta(days=30)).isoformat()).status_code, 409)
        with mock.patch("assets.views_maintenance.can_plan_maintenance", return_value=False):
            self.assertEqual(self._move(self.occ.id, self.today.isoformat()).status_code, 403)
        MaintenanceOccurrence.objects.filter(pk=self.occ.pk).update(
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=self.today
        )
        self.assertEqual(self._move(self.occ.id, self.today.isoformat()).status_code, 400)
        self.assertEqual(self.client.get(reverse("assets:occurrence_reschedule", args=[self.occ.id])).status_code, 405)

    def test_calendario_segnala_cosa_si_trascina(self):
        response = self.client.get(
            reverse("assets:calendario_asset_json"),
            {"start": self.today.isoformat(), "end": (self.today + timedelta(days=10)).isoformat()},
        )
        event = next(e for e in response.json()["events"] if e["id"] == f"occ-{self.occ.id}")
        self.assertTrue(event["movable"])
        page = self.client.get(reverse("assets:calendario_asset"))
        self.assertContains(page, 'data-can-plan="1"', html=False)
        self.assertContains(page, "Clicca un giorno")


@override_settings(LEGACY_AUTH_ENABLED=False)
class CosaPossoFareTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username="ux4-help", password="x", email="h@y.z"))

    def test_ogni_voce_del_menu_ha_la_sua_spiegazione(self):
        for group in MAINTENANCE_NAV:
            for item in group.items:
                self.assertTrue(HELP_TEXTS.get(item.key), f"Manca 'Cosa posso fare qui' per {item.key}")

    def test_pannello_e_tour_nelle_pagine(self):
        for route in ("maintenance_responsabile", "maintenance_da_fare", "calendario_asset", "maintenance_scadenze",
                      "maintenance_setup", "maintenance_plan_list", "wo_list", "software_license_list"):
            response = self.client.get(reverse(f"assets:{route}"))
            self.assertEqual(response.status_code, 200, route)
            self.assertContains(response, "Cosa posso fare qui", msg_prefix=route)
            self.assertContains(response, 'data-tour-start', html=False, msg_prefix=route)
        for route in ("maintenance_responsabile", "calendario_asset", "maintenance_scadenze", "maintenance_setup"):
            self.assertContains(self.client.get(reverse(f"assets:{route}")), 'data-tour-step="1"', html=False, msg_prefix=route)
