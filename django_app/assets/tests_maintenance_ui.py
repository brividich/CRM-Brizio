"""Test delle pagine del nuovo dominio manutenzione.

Coprono che ogni pagina renda davvero (non solo che l'URL esista), e i flussi che
la specifica considera irrinunciabili: creare un OdL massivo da una selezione,
toglierne un asset senza chiudere la manutenzione, distribuire su piu' giornate,
chiudere una scadenza amministrativa solo col documento, aprire un follow-up
agganciato all'asset giusto.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetCategory,
    AssetGroup,
    AssetGroupMembership,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
    WorkOrder,
)
from assets.services import maintenance_domain as domain

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class MaintenanceUITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="admin-manut", password="x", email="a@b.c")
        cls.category = AssetCategory.objects.create(code="macchine", label="Macchine")
        cls.assets = [
            Asset.objects.create(
                asset_tag=f"TORNIO0{i}",
                name=f"Tornio {i}",
                asset_category=cls.category,
                reparto="Officina",
                status=Asset.STATUS_IN_USE,
            )
            for i in (1, 2, 3)
        ]
        cls.group = AssetGroup.objects.create(code="torni", label="TORNI")
        for asset in cls.assets:
            AssetGroupMembership.objects.create(group=cls.group, asset=asset)

        cls.plan = MaintenanceInterventionTemplate.objects.create(
            code="cambio-olio", label="Cambio olio", maintenance_type=MaintenanceInterventionTemplate.TYPE_ROUTINE
        )
        cls.assignment = MaintenancePlanAssignment.objects.create(
            plan=cls.plan,
            target_type=MaintenancePlanAssignment.TARGET_GROUP,
            asset_group=cls.group,
            frequency=MaintenancePlanAssignment.FREQ_DAYS,
            interval=30,
            warning_days=30,
            first_due_date=timezone.localdate() + timedelta(days=10),
        )

    def setUp(self):
        self.client.force_login(self.admin)
        domain.generate_occurrences(today=timezone.localdate())
        self.occurrences = list(MaintenanceOccurrence.objects.order_by("asset__asset_tag"))


class MaintenancePagesRenderTests(MaintenanceUITestCase):
    def test_tutte_le_pagine_rendono(self):
        urls = [
            reverse("assets:maintenance_da_fare"),
            reverse("assets:maintenance_scadenze"),
            reverse("assets:maintenance_responsabile"),
            reverse("assets:maintenance_plan_list"),
            reverse("assets:maintenance_plan_detail", args=[self.plan.pk]),
            reverse("assets:maintenance_plan_create"),
            reverse("assets:maintenance_plan_edit", args=[self.plan.pk]),
            reverse("assets:maintenance_assignment_create", args=[self.plan.pk]),
            reverse("assets:maintenance_assignment_edit", args=[self.plan.pk, self.assignment.pk]),
            reverse("assets:asset_group_list"),
            reverse("assets:asset_group_create"),
            reverse("assets:asset_group_edit", args=[self.group.pk]),
            reverse("assets:maintenance_coverage"),
            reverse("assets:asset_maintenance_plans", args=[self.assets[0].pk]),
            reverse("assets:asset_plan_customize", args=[self.assets[0].pk, self.plan.pk]),
            reverse("assets:occurrence_complete", args=[self.occurrences[0].pk]),
            reverse("assets:occurrence_followup_create", args=[self.occurrences[0].pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, f"{url} -> {response.status_code}")

    def test_da_fare_mostra_le_manutenzioni_dovute(self):
        response = self.client.get(reverse("assets:maintenance_da_fare"))
        self.assertContains(response, "TORNIO01")
        self.assertContains(response, "Cambio olio")

    def test_da_fare_raggruppa_per_famiglia_e_asset(self):
        for mode in ("plan", "group", "asset"):
            with self.subTest(mode=mode):
                response = self.client.get(reverse("assets:maintenance_da_fare"), {"by": mode})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["view_mode"], mode)

    def test_filtro_per_gruppo(self):
        other = Asset.objects.create(
            asset_tag="FRESA01", name="Fresa", asset_category=self.category, status=Asset.STATUS_IN_USE
        )
        MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=other, due_date=timezone.localdate(), warning_days=30
        )
        response = self.client.get(reverse("assets:maintenance_scadenze"), {"group": self.group.pk, "window": ""})
        tags = {row["occurrence"].asset.asset_tag for row in response.context["rows"]}
        self.assertNotIn("FRESA01", tags)
        self.assertIn("TORNIO01", tags)

    def test_matrice_copertura_marca_ereditato(self):
        response = self.client.get(reverse("assets:maintenance_coverage"))
        cells = response.context["rows"][0]["cells"]
        self.assertTrue(any(cell["tone"] == "inherited" for cell in cells))

    def test_scheda_asset_dichiara_l_origine_e_non_dice_override(self):
        response = self.client.get(reverse("assets:asset_maintenance_plans", args=[self.assets[0].pk]))
        self.assertContains(response, "Ereditato dal gruppo")
        self.assertNotContains(response, "verride")


class WorkOrderFlowTests(MaintenanceUITestCase):
    def _create_workorder(self, occurrences=None):
        response = self.client.post(
            reverse("assets:occurrence_create_workorder"),
            {
                "occurrence_ids": [str(occ.pk) for occ in (occurrences or self.occurrences)],
                "title": "",
                "assigned_to": "",
                "supplier": "",
                "due_at": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        return WorkOrder.objects.latest("id")

    def test_crea_odl_massivo_da_selezione(self):
        work_order = self._create_workorder()
        self.assertTrue(work_order.is_massive)
        self.assertEqual(work_order.occurrences.count(), 3)

    def test_dettaglio_odl_mostra_il_pannello_manutenzioni(self):
        work_order = self._create_workorder()
        response = self.client.get(reverse("assets:wo_view", args=[work_order.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manutenzioni raccolte")
        self.assertEqual(response.context["wo_occurrence_progress"]["total"], 3)

    def test_rimuovere_un_asset_non_chiude_la_manutenzione(self):
        work_order = self._create_workorder()
        removed = self.occurrences[1]

        response = self.client.post(
            reverse("assets:workorder_occurrence_remove", args=[work_order.pk, removed.pk]),
            {"reason": "macchina in produzione"},
        )
        self.assertEqual(response.status_code, 302)

        removed.refresh_from_db()
        self.assertIsNone(removed.work_order_id)
        self.assertEqual(removed.status, MaintenanceOccurrence.STATUS_OPEN)

        # E torna a comparire fra le manutenzioni da pianificare.
        page = self.client.get(reverse("assets:maintenance_da_fare"))
        pending = {row["occurrence"].pk for group in page.context["groups"] for row in group["rows"]}
        self.assertIn(removed.pk, pending)
        state = next(
            row["state"]
            for group in page.context["groups"]
            for row in group["rows"]
            if row["occurrence"].pk == removed.pk
        )
        self.assertIn(state, {MaintenanceOccurrence.VIEW_TO_PLAN, MaintenanceOccurrence.VIEW_DUE_SOON})

    def test_distribuzione_su_piu_giornate(self):
        work_order = self._create_workorder()
        target = timezone.localdate() + timedelta(days=3)
        response = self.client.post(
            reverse("assets:workorder_distribute_day", args=[work_order.pk]),
            {
                "occurrence_ids": [str(self.occurrences[0].pk), str(self.occurrences[1].pk)],
                "execution_date": target.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(work_order.execution_days.get(execution_date=target).occurrences.count(), 2)

    def test_completamento_parziale_resta_tracciato(self):
        work_order = self._create_workorder()
        domain.complete_occurrence(self.occurrences[0], completed_on=timezone.localdate())

        response = self.client.get(reverse("assets:wo_view", args=[work_order.pk]))
        progress = response.context["wo_occurrence_progress"]
        self.assertEqual(progress["done"], 1)
        self.assertEqual(progress["todo"], 2)
        self.assertTrue(progress["is_partial"])

    def test_aggiunta_esplicita_di_una_nuova_manutenzione(self):
        work_order = self._create_workorder(self.occurrences[:2])
        orphan = self.occurrences[2]

        response = self.client.post(
            reverse("assets:workorder_occurrence_add", args=[work_order.pk]),
            {"occurrence_ids": [str(orphan.pk)]},
        )
        self.assertEqual(response.status_code, 302)
        orphan.refresh_from_db()
        self.assertEqual(orphan.work_order_id, work_order.pk)


class OccurrenceCompletionViewTests(MaintenanceUITestCase):
    def test_registrazione_avanza_la_scadenza(self):
        occurrence = self.occurrences[0]
        response = self.client.post(
            reverse("assets:occurrence_complete", args=[occurrence.pk]),
            {"completed_on": timezone.localdate().isoformat(), "notes": "olio sostituito", "downtime_minutes": "30"},
        )
        self.assertEqual(response.status_code, 302)

        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, MaintenanceOccurrence.STATUS_DONE)
        self.assertEqual(occurrence.downtime_minutes, 30)
        self.assertTrue(
            MaintenanceOccurrence.objects.filter(
                plan=self.plan, asset=occurrence.asset, status=MaintenanceOccurrence.STATUS_OPEN
            ).exists(),
            "la chiusura deve generare la scadenza successiva",
        )

    def test_amministrativa_senza_documento_viene_rifiutata_dal_form(self):
        plan = MaintenanceInterventionTemplate.objects.create(
            code="assicurazione",
            label="Rinnovo assicurazione",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
            attachment_required=True,
        )
        occurrence = MaintenanceOccurrence.objects.create(
            plan=plan,
            asset=self.assets[0],
            due_date=timezone.localdate(),
            warning_days=30,
            schedule_anchor=MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
        )

        response = self.client.post(
            reverse("assets:occurrence_complete", args=[occurrence.pk]),
            {"completed_on": timezone.localdate().isoformat(), "notes": "", "downtime_minutes": "0"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "obbligatorio allegare il documento")
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, MaintenanceOccurrence.STATUS_OPEN)

    def test_amministrativa_con_documento_si_chiude(self):
        plan = MaintenanceInterventionTemplate.objects.create(
            code="assicurazione2",
            label="Rinnovo assicurazione",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
            attachment_required=True,
        )
        occurrence = MaintenanceOccurrence.objects.create(
            plan=plan,
            asset=self.assets[0],
            due_date=date(2026, 12, 31),
            warning_days=30,
            schedule_anchor=MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR,
        )
        response = self.client.post(
            reverse("assets:occurrence_complete", args=[occurrence.pk]),
            {
                "completed_on": timezone.localdate().isoformat(),
                "notes": "",
                "downtime_minutes": "0",
                "attachment": SimpleUploadedFile("polizza.pdf", b"contenuto"),
            },
        )
        self.assertEqual(response.status_code, 302)
        occurrence.refresh_from_db()
        self.assertEqual(occurrence.status, MaintenanceOccurrence.STATUS_DONE)
        self.assertTrue(occurrence.attachments.exists())

    def test_follow_up_si_aggancia_all_asset_dell_occorrenza(self):
        occurrence = self.occurrences[2]
        response = self.client.post(
            reverse("assets:occurrence_followup_create", args=[occurrence.pk]),
            {"title": "Perdita olio", "reason": "trafilamento dal carter", "assigned_to": "", "due_at": ""},
        )
        self.assertEqual(response.status_code, 302)

        follow_up = WorkOrder.objects.filter(follow_up_occurrence=occurrence).first()
        self.assertIsNotNone(follow_up)
        self.assertEqual(follow_up.asset_id, occurrence.asset_id)
        self.assertEqual(follow_up.kind, WorkOrder.KIND_CORRECTIVE)


class PlanConfigurationViewTests(MaintenanceUITestCase):
    def test_creazione_piano_amministrativo_forza_documento_e_ancoraggio(self):
        response = self.client.post(
            reverse("assets:maintenance_plan_create"),
            {
                "label": "Revisione annuale",
                "code": "",
                "maintenance_type": MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE,
                "description": "",
                "estimated_duration_minutes": "0",
                "required_materials": "",
                "execution_mode": MaintenanceInterventionTemplate.MODE_INTERNAL,
                "default_supplier": "",
                "default_assignee": "",
                "attachment_required": "",
                "schedule_anchor": "",
                "asset_category": "",
                "sort_order": "100",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        plan = MaintenanceInterventionTemplate.objects.get(label="Revisione annuale")
        self.assertTrue(plan.attachment_required)
        self.assertEqual(plan.default_schedule_anchor, "FIXED_CALENDAR")

    def test_applicazione_con_preset_di_periodicita(self):
        response = self.client.post(
            reverse("assets:maintenance_assignment_create", args=[self.plan.pk]),
            {
                "target_type": MaintenancePlanAssignment.TARGET_ASSET,
                "asset": str(self.assets[0].pk),
                "asset_group": "",
                "asset_category": "",
                "recurrence_preset": "quarterly",
                "frequency": MaintenancePlanAssignment.FREQ_DAYS,
                "interval": "1",
                "weekday": "",
                "week_of_month": "",
                "day_of_month": "",
                "month_of_year": "",
                "warning_days": "20",
                "schedule_anchor": "",
                "first_due_date": timezone.localdate().isoformat(),
                "execution_mode": "",
                "supplier": "",
                "assigned_to": "",
                "auto_generate": "on",
                "is_active": "on",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        assignment = MaintenancePlanAssignment.objects.get(
            plan=self.plan, asset=self.assets[0], target_type=MaintenancePlanAssignment.TARGET_ASSET
        )
        self.assertEqual(assignment.frequency, MaintenancePlanAssignment.FREQ_MONTHS)
        self.assertEqual(assignment.interval, 3)

    def test_esclusione_di_un_asset_dalla_scheda(self):
        response = self.client.post(
            reverse("assets:asset_plan_customize", args=[self.assets[1].pk, self.plan.pk]),
            {
                "mode": "exclude",
                "recurrence_preset": "monthly",
                "frequency": MaintenancePlanAssignment.FREQ_DAYS,
                "interval": "30",
                "weekday": "",
                "week_of_month": "",
                "day_of_month": "",
                "month_of_year": "",
                "warning_days": "30",
                "first_due_date": "",
                "notes": "macchina dismessa dal ciclo",
            },
        )
        self.assertEqual(response.status_code, 302)
        assignment = MaintenancePlanAssignment.objects.get(
            plan=self.plan, asset=self.assets[1], target_type=MaintenancePlanAssignment.TARGET_ASSET
        )
        self.assertTrue(assignment.is_excluded)

        resolution = domain.resolve_plan_for_asset(plan_id=self.plan.pk, asset=self.assets[1])
        self.assertTrue(resolution.is_excluded)

    def test_anteprima_impatto(self):
        response = self.client.get(
            reverse("assets:maintenance_assignment_preview"),
            {
                "plan": self.plan.pk,
                "target_type": MaintenancePlanAssignment.TARGET_GROUP,
                "target_id": self.group.pk,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["assets"], 3)
        self.assertEqual(payload["already"], 3)

    def test_applicazione_con_storico_viene_disattivata_non_cancellata(self):
        response = self.client.post(
            reverse("assets:maintenance_assignment_delete", args=[self.plan.pk, self.assignment.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assignment.refresh_from_db()
        self.assertFalse(self.assignment.is_active)

    def test_creazione_gruppo_con_membri(self):
        response = self.client.post(
            reverse("assets:asset_group_create"),
            {
                "label": "FRESE",
                "code": "",
                "description": "",
                "sort_order": "100",
                "is_active": "on",
                "members": [str(self.assets[0].pk), str(self.assets[1].pk)],
            },
        )
        self.assertEqual(response.status_code, 302)
        group = AssetGroup.objects.get(label="FRESE")
        self.assertEqual(group.assets.count(), 2)


@override_settings(LEGACY_AUTH_ENABLED=False)
class MaintenancePermissionTests(TestCase):
    """Un utente senza permessi vede le liste ma non tocca la configurazione."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="operatore", password="x")
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="p", label="Pulizia filtri")

    def setUp(self):
        self.client.force_login(self.user)

    def test_configurazione_negata_senza_permesso(self):
        response = self.client.get(reverse("assets:maintenance_plan_create"))
        self.assertEqual(response.status_code, 302)

    def test_anteprima_impatto_negata_senza_permesso(self):
        response = self.client.get(
            reverse("assets:maintenance_assignment_preview"),
            {"plan": self.plan.pk, "target_type": "GROUP", "target_id": "1"},
        )
        self.assertEqual(response.status_code, 403)
