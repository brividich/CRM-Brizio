"""Eliminazione definitiva di un piano: verifica, spostamento su altro piano, cancellazione."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    MaintenanceChecklistStep,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    WorkOrder,
)
from assets.services import plan_delete

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class PlanDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="admin-elimina", password="x", email="a@b.c")
        cat = AssetCategory.objects.create(code="macc-del", label="Macchine")
        cls.a1 = Asset.objects.create(asset_tag="DEL01", name="Pressa 1", asset_category=cat,
                                      status=Asset.STATUS_IN_USE)
        cls.a2 = Asset.objects.create(asset_tag="DEL02", name="Pressa 2", asset_category=cat,
                                      status=Asset.STATUS_IN_USE)

    def setUp(self):
        self.client.force_login(self.admin)
        self.today = timezone.localdate()
        self.plan = MaintenanceInterventionTemplate.objects.create(code="vecchio", label="Piano vecchio")
        self.target = MaintenanceInterventionTemplate.objects.create(code="nuovo", label="Piano nuovo")
        MaintenanceChecklistStep.objects.create(intervention_template=self.plan, step_number=1, description="Passo")
        self.assignment = MaintenancePlanAssignment.objects.create(
            plan=self.plan, target_type="ASSET", asset=self.a1, frequency="DAYS", interval=30,
        )
        self.wo = WorkOrder.objects.create(asset=self.a1, title="OdL prova")
        self.done = MaintenanceOccurrence.objects.create(
            plan=self.plan, assignment=self.assignment, asset=self.a1,
            due_date=self.today - timedelta(days=30), status=MaintenanceOccurrence.STATUS_DONE,
            completed_on=self.today - timedelta(days=29), work_order=self.wo,
        )
        self.open = MaintenanceOccurrence.objects.create(
            plan=self.plan, assignment=self.assignment, asset=self.a1, due_date=self.today + timedelta(days=5),
        )

    def _url(self):
        return reverse("assets:maintenance_plan_delete", args=[self.plan.pk])

    def test_pagina_mostra_la_verifica(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manutenzioni eseguite (storico)")
        self.assertContains(response, "Piano nuovo")
        detail = self.client.get(reverse("assets:maintenance_plan_detail", args=[self.plan.pk]))
        self.assertContains(detail, self._url())

    def test_nome_sbagliato_non_elimina(self):
        self.client.post(self._url(), {"mode": "cancella", "confirm": "altro"})
        self.assertTrue(MaintenanceInterventionTemplate.objects.filter(pk=self.plan.pk).exists())

    def test_sposta_tutto_su_altro_piano(self):
        # Stessa applicazione e stessa scadenza aperta gia' sul piano di destinazione: si uniscono.
        existing = MaintenancePlanAssignment.objects.create(
            plan=self.target, target_type="ASSET", asset=self.a1, frequency="DAYS", interval=60,
        )
        twin = MaintenanceOccurrence.objects.create(
            plan=self.target, assignment=existing, asset=self.a1, due_date=self.open.due_date,
        )
        response = self.client.post(
            self._url(), {"mode": "sposta", "target": self.target.pk, "confirm": "piano vecchio"}
        )
        self.assertRedirects(response, reverse("assets:maintenance_plan_detail", args=[self.target.pk]),
                             fetch_redirect_response=False)
        self.assertFalse(MaintenanceInterventionTemplate.objects.filter(pk=self.plan.pk).exists())
        self.done.refresh_from_db()
        self.assertEqual(self.done.plan_id, self.target.pk)
        self.assertEqual(self.done.assignment_id, existing.pk)
        self.assertEqual(self.done.work_order_id, self.wo.pk)
        self.assertFalse(MaintenanceOccurrence.objects.filter(pk=self.open.pk).exists())
        self.assertTrue(MaintenanceOccurrence.objects.filter(pk=twin.pk).exists())
        self.assertEqual(MaintenancePlanAssignment.objects.filter(plan=self.target).count(), 1)

    def test_sposta_bloccato_da_storico_in_conflitto(self):
        MaintenanceOccurrence.objects.create(plan=self.target, asset=self.a1, due_date=self.done.due_date)
        response = self.client.post(
            self._url(), {"mode": "sposta", "target": self.target.pk, "confirm": "Piano vecchio"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "in conflitto")
        self.assertTrue(MaintenanceInterventionTemplate.objects.filter(pk=self.plan.pk).exists())
        self.done.refresh_from_db()
        self.assertEqual(self.done.plan_id, self.plan.pk)

    def test_cancella_tutto_lascia_gli_odl(self):
        response = self.client.post(self._url(), {"mode": "cancella", "confirm": "Piano vecchio"})
        self.assertRedirects(response, reverse("assets:maintenance_plan_list"), fetch_redirect_response=False)
        self.assertFalse(MaintenanceInterventionTemplate.objects.filter(pk=self.plan.pk).exists())
        self.assertFalse(MaintenanceOccurrence.objects.filter(plan_id=self.plan.pk).exists())
        self.assertFalse(MaintenancePlanAssignment.objects.filter(plan_id=self.plan.pk).exists())
        self.assertFalse(MaintenanceChecklistStep.objects.filter(intervention_template_id=self.plan.pk).exists())
        self.assertTrue(WorkOrder.objects.filter(pk=self.wo.pk).exists())
        self.assertTrue(MaintenanceInterventionTemplate.objects.filter(pk=self.target.pk).exists())

    def test_verifica_conta_i_collegamenti(self):
        impact = plan_delete.plan_delete_impact(self.plan)
        counts = {row.key: row.count for row in impact.rows}
        self.assertEqual(counts["assignments"], 1)
        self.assertEqual(counts["occ_open"], 1)
        self.assertEqual(counts["occ_done"], 1)
        self.assertEqual(counts["workorders"], 1)
        self.assertEqual(counts["checklist"], 1)
        self.assertEqual(impact.unknown_blockers, [])

    def test_senza_permesso_non_elimina(self):
        user = User.objects.create_user(username="semplice-del", password="x")
        self.client.force_login(user)
        self.client.post(self._url(), {"mode": "cancella", "confirm": "Piano vecchio"})
        self.assertTrue(MaintenanceInterventionTemplate.objects.filter(pk=self.plan.pk).exists())
