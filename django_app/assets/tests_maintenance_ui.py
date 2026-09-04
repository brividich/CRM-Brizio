"""Test delle pagine del nuovo dominio manutenzione.

Coprono che ogni pagina renda davvero (non solo che l'URL esista), e i flussi che
la specifica considera irrinunciabili: creare un OdL massivo da una selezione,
toglierne un asset senza chiudere la manutenzione, distribuire su piu' giornate,
chiudere una scadenza amministrativa solo col documento, aprire un follow-up
agganciato all'asset giusto.
"""

from __future__ import annotations

import io
import json
import re
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
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
            reverse("assets:maintenance_history_import"),
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


class HistoryImportTests(MaintenanceUITestCase):
    """L'import iniziale dello storico: senza, ogni piano risulterebbe dovuto subito."""

    def _xlsx(self, rows, headers=None):
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers or ["asset", "piano", "ultima esecuzione", "note"])
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return SimpleUploadedFile(
            "storico.xlsx",
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_anteprima_calcola_la_prossima_scadenza_senza_scrivere(self):
        eseguita = timezone.localdate() - timedelta(days=5)
        response = self.client.post(
            reverse("assets:maintenance_history_import"),
            {"file": self._xlsx([["TORNIO01", "Cambio olio", eseguita.strftime("%d/%m/%Y"), "ok"]])},
        )

        self.assertEqual(response.status_code, 200)
        report = response.context["report"]
        self.assertEqual(len(report.valid_rows), 1)
        self.assertEqual(report.valid_rows[0].next_due, eseguita + timedelta(days=30))
        self.assertFalse(
            MaintenanceOccurrence.objects.filter(source=MaintenanceOccurrence.SOURCE_IMPORT).exists(),
            "l'anteprima non deve scrivere nulla",
        )

    def test_le_righe_in_errore_non_bloccano_le_altre(self):
        eseguita = timezone.localdate() - timedelta(days=5)
        response = self.client.post(
            reverse("assets:maintenance_history_import"),
            {
                "file": self._xlsx(
                    [
                        ["TORNIO01", "Cambio olio", eseguita.strftime("%d/%m/%Y"), ""],
                        ["FANTASMA", "Cambio olio", eseguita.strftime("%d/%m/%Y"), ""],
                        ["TORNIO02", "Piano inesistente", eseguita.strftime("%d/%m/%Y"), ""],
                        ["TORNIO03", "Cambio olio", "domani", ""],
                    ]
                )
            },
        )

        report = response.context["report"]
        self.assertEqual(len(report.valid_rows), 1)
        self.assertEqual(len(report.error_rows), 3)
        errori = " ".join(row.error for row in report.error_rows)
        self.assertIn("FANTASMA", errori)
        self.assertIn("Piano inesistente", errori)

    def test_la_conferma_scrive_storico_e_prossima_scadenza(self):
        eseguita = timezone.localdate() - timedelta(days=5)
        payload = json.dumps([["TORNIO01", "Cambio olio", eseguita.isoformat(), "revisione"]])

        response = self.client.post(
            reverse("assets:maintenance_history_import"),
            {"confirm": "1", "payload": payload},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        storico = MaintenanceOccurrence.objects.get(
            asset=self.assets[0], status=MaintenanceOccurrence.STATUS_DONE
        )
        self.assertEqual(storico.due_date, eseguita)
        self.assertEqual(storico.completed_on, eseguita)
        self.assertEqual(storico.completion_notes, "revisione")

    def test_import_ripetibile_non_duplica(self):
        eseguita = timezone.localdate() - timedelta(days=5)
        upload = lambda: self.client.post(  # noqa: E731
            reverse("assets:maintenance_history_import"),
            {"file": self._xlsx([["TORNIO01", "Cambio olio", eseguita.strftime("%d/%m/%Y"), ""]])},
        )
        payload = json.dumps([["TORNIO01", "Cambio olio", eseguita.isoformat(), ""]])
        self.client.post(
            reverse("assets:maintenance_history_import"), {"confirm": "1", "payload": payload}
        )

        report = upload().context["report"]

        self.assertEqual(len(report.valid_rows), 0)
        self.assertEqual(len(report.duplicate_rows), 1)

    def test_il_conflitto_si_chiama_conflitto(self):
        # Un piano che arriva da due gruppi con periodicita' diverse NON e' un piano
        # "che non si applica": dirlo cosi' manderebbe l'utente a cercare la causa
        # sbagliata. La risoluzione in conflitto non ha applicazione, quindi l'ordine
        # dei controlli e' l'unica cosa che tiene in piedi il messaggio giusto.
        altro_gruppo = AssetGroup.objects.create(code="reparto2", label="REPARTO 2")
        AssetGroupMembership.objects.create(group=altro_gruppo, asset=self.assets[0])
        MaintenancePlanAssignment.objects.create(
            plan=self.plan,
            target_type=MaintenancePlanAssignment.TARGET_GROUP,
            asset_group=altro_gruppo,
            frequency=MaintenancePlanAssignment.FREQ_DAYS,
            interval=90,
            warning_days=30,
        )
        eseguita = timezone.localdate() - timedelta(days=5)

        response = self.client.post(
            reverse("assets:maintenance_history_import"),
            {"file": self._xlsx([["TORNIO01", "Cambio olio", eseguita.strftime("%d/%m/%Y"), ""]])},
        )

        errori = " ".join(row.error for row in response.context["report"].error_rows)
        self.assertIn("conflitto", errori.lower())
        self.assertNotIn("non si applica", errori)

    def test_intestazioni_sbagliate_lo_dicono(self):
        response = self.client.post(
            reverse("assets:maintenance_history_import"),
            {"file": self._xlsx([["x", "y", "z"]], headers=["colonna1", "colonna2", "colonna3"])},
        )

        self.assertTrue(response.context["report"].header_error)

    def test_il_modello_excel_si_scarica(self):
        response = self.client.get(reverse("assets:maintenance_history_template"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])

    def test_senza_permesso_la_pagina_non_si_apre(self):
        # La route e' registrata in acl_bootstrap: la nega gia' il middleware (302),
        # e se anche passasse il gate della view risponderebbe 404.
        operatore = User.objects.create_user(username="operatore-import", password="x")
        self.client.force_login(operatore)

        response = self.client.get(reverse("assets:maintenance_history_import"))

        self.assertIn(response.status_code, (302, 403, 404))


class ChecklistFollowUpTests(MaintenanceUITestCase):
    """Il follow-up si apre da dove l'anomalia si vede: lo step della checklist."""

    def setUp(self):
        super().setUp()
        self.workorder = domain.create_workorder_from_occurrences(
            [self.occurrences[0]], user=self.admin
        )
        self.step = self.workorder.checklist_items.create(
            step_number=1,
            description="Gioco assiale mandrino",
            step_type="MEASURE",
            unit="mm",
            range_min=0,
            range_max=2,
            value_numeric=7,
        )

    def test_uno_step_fuori_range_offre_il_follow_up(self):
        response = self.client.get(reverse("assets:wo_view", args=[self.workorder.pk]))

        self.assertContains(response, "Apri follow-up")
        self.assertContains(
            response,
            f"{reverse('assets:occurrence_followup_create', args=[self.occurrences[0].pk])}?step={self.step.pk}",
        )

    def test_su_odl_massivo_chiede_su_quale_macchina(self):
        domain.add_occurrences_to_workorder(
            self.workorder, [self.occurrences[1]], user=self.admin
        )

        response = self.client.get(reverse("assets:wo_view", args=[self.workorder.pk]))

        self.assertContains(response, "su quale macchina?")
        for occurrence in self.occurrences[:2]:
            self.assertContains(
                response,
                f"{reverse('assets:occurrence_followup_create', args=[occurrence.pk])}?step={self.step.pk}",
            )

    def test_un_follow_up_gia_aperto_non_ne_propone_un_altro(self):
        follow_up = WorkOrder.objects.create(
            asset=self.assets[0],
            kind=WorkOrder.KIND_CORRECTIVE,
            status=WorkOrder.STATUS_OPEN,
            title="Sostituzione cuscinetti",
            follow_up_occurrence=self.occurrences[0],
            follow_up_checklist_item=self.step,
        )

        response = self.client.get(reverse("assets:wo_view", args=[self.workorder.pk]))

        self.assertContains(response, "Follow-up aperto")
        self.assertContains(response, f"#{follow_up.pk}")
        self.assertNotContains(response, "Apri follow-up")

    def test_uno_step_fuori_range_non_e_marcato_come_risolto(self):
        # Compilato non vuol dire a posto: barrarlo in verde nasconde l'anomalia
        # proprio nella riga che la contiene. Nessuno degli step di questo OdL e'
        # completo, quindi la classe "done" non deve comparire affatto.
        response = self.client.get(reverse("assets:wo_view", args=[self.workorder.pk]))

        # Solo la marcatura delle righe, non il CSS che definisce le classi.
        classi = re.findall(r'class="(wod-cl-item[^"]*)"', response.content.decode())
        self.assertTrue(classi, "nessuno step renderizzato")
        self.assertTrue(any("wod-cl-item--blocking" in c for c in classi))
        self.assertFalse([c for c in classi if "wod-cl-item--done" in c])

    def test_uno_step_nei_limiti_non_propone_nulla(self):
        self.step.value_numeric = 1
        self.step.save(update_fields=["value_numeric"])

        response = self.client.get(reverse("assets:wo_view", args=[self.workorder.pk]))

        self.assertNotContains(response, "Apri follow-up")


class AssetDetailPlansTests(MaintenanceUITestCase):
    """I piani vivono anche nella scheda della macchina, non solo in una pagina a parte."""

    def test_la_scheda_asset_elenca_i_piani_che_lo_riguardano(self):
        response = self.client.get(reverse("assets:asset_view", args=[self.assets[0].pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Piani di manutenzione")
        self.assertContains(response, "Cambio olio")
        self.assertContains(response, "Gestisci i piani di questo asset")

    def test_quando_ci_sono_piani_il_blocco_a_regole_tace(self):
        # Due fonti sulla stessa scheda direbbero la stessa manutenzione due volte,
        # con due date diverse.
        response = self.client.get(reverse("assets:asset_view", args=[self.assets[0].pk]))

        self.assertNotContains(response, "Nessuna regola manutenzione pianificata")

    def test_un_asset_senza_piani_mostra_ancora_il_blocco_storico(self):
        orfano = Asset.objects.create(
            asset_tag="SENZA01",
            name="Asset senza piani",
            asset_category=self.category,
            status=Asset.STATUS_IN_USE,
        )

        response = self.client.get(reverse("assets:asset_view", args=[orfano.pk]))

        self.assertNotContains(response, "Piani di manutenzione")
        self.assertContains(response, "Manutenzione pianificata")


class AssignmentPreviewFirstDueTests(MaintenanceUITestCase):
    """L'anteprima dice quanti asset, e anche quando arriva il lavoro."""

    def test_l_anteprima_raggruppa_le_prime_scadenze_per_mese(self):
        MaintenanceOccurrence.objects.all().delete()
        fra_un_mese = timezone.localdate() + timedelta(days=30)

        response = self.client.get(
            reverse("assets:maintenance_assignment_preview"),
            {
                "plan": self.plan.pk,
                "target_type": "GROUP",
                "target_id": self.group.pk,
                "frequency": "DAYS",
                "interval": "30",
                "first_due_date": fra_un_mese.isoformat(),
            },
        )

        payload = response.json()
        self.assertEqual(payload["assets"], 3)
        self.assertTrue(payload["first_due"], "senza le prime scadenze l'anteprima non dice quando arriva il lavoro")
        self.assertEqual(sum(bucket["count"] for bucket in payload["first_due"]), 3)

    def test_il_preset_vince_sui_campi_grezzi(self):
        # Scegliendo "ogni trimestre" i sei campi grezzi restano ai valori iniziali
        # del form: se l'anteprima leggesse quelli, calcolerebbe le date con una
        # periodicita' che nessuno ha scelto.
        MaintenanceOccurrence.objects.all().delete()
        eseguita = timezone.localdate() - timedelta(days=1)
        MaintenanceOccurrence.objects.create(
            plan=self.plan,
            assignment=self.assignment,
            asset=self.assets[0],
            due_date=eseguita,
            status=MaintenanceOccurrence.STATUS_DONE,
            completed_on=eseguita,
        )

        response = self.client.get(
            reverse("assets:maintenance_assignment_preview"),
            {
                "plan": self.plan.pk,
                "target_type": "ASSET",
                "target_id": self.assets[0].pk,
                "recurrence_preset": "quarterly",
                "frequency": "DAYS",
                "interval": "1",
            },
        )

        from assets.views_maintenance import _MESI

        payload = response.json()
        atteso = eseguita + relativedelta(months=3)
        sbagliato = eseguita + relativedelta(days=1)
        self.assertEqual(len(payload["first_due"]), 1)
        self.assertEqual(
            payload["first_due"][0]["label"], f"{_MESI[atteso.month - 1]} {atteso.year}"
        )
        self.assertNotEqual(
            payload["first_due"][0]["label"],
            f"{_MESI[sbagliato.month - 1]} {sbagliato.year}",
            "l'anteprima ha usato i campi grezzi invece del preset",
        )

    def test_gli_asset_con_una_scadenza_aperta_non_sono_ricontati(self):
        response = self.client.get(
            reverse("assets:maintenance_assignment_preview"),
            {
                "plan": self.plan.pk,
                "target_type": "GROUP",
                "target_id": self.group.pk,
                "frequency": "DAYS",
                "interval": "30",
            },
        )

        payload = response.json()
        self.assertEqual(payload["already"], 3)
        self.assertEqual(payload["first_due"], [])


class CaporepartoScopeTests(MaintenanceUITestCase):
    """Lo scope per reparto e' una preimpostazione dichiarata, non una barriera."""

    def test_senza_reparti_guidati_non_si_filtra_nulla(self):
        response = self.client.get(reverse("assets:maintenance_da_fare"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scoped_reparti"], [])
        self.assertEqual(response.context["total"], 3)

    def test_un_reparto_esplicito_in_query_string_disattiva_lo_scope(self):
        from assets import views_maintenance

        original = views_maintenance.user_reparti
        views_maintenance.user_reparti = lambda request: ["Officina"]
        try:
            scoped = self.client.get(reverse("assets:maintenance_da_fare"))
            esplicito = self.client.get(reverse("assets:maintenance_da_fare"), {"reparto": ""})
        finally:
            views_maintenance.user_reparti = original

        self.assertEqual(scoped.context["scoped_reparti"], ["Officina"])
        self.assertEqual(esplicito.context["scoped_reparti"], [])

    def test_un_reparto_che_non_esiste_sugli_asset_non_svuota_la_pagina(self):
        # Il reparto sull'asset e' testo libero: un disallineamento di nomi non deve
        # produrre una pagina vuota, che verrebbe letta come "non c'e' lavoro".
        from assets import views_maintenance

        original = views_maintenance.user_reparti
        views_maintenance.user_reparti = lambda request: ["Reparto Inesistente"]
        try:
            response = self.client.get(reverse("assets:maintenance_da_fare"))
        finally:
            views_maintenance.user_reparti = original

        self.assertEqual(response.context["scoped_reparti"], [])
        self.assertEqual(response.context["total"], 3)
