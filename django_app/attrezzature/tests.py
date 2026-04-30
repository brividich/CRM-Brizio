from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook

from .models import (
    Attrezzatura,
    AttrezzaturaAvanzamento,
    AttrezzaturaImportRow,
    AttrezzaturaPartNumber,
    AttrezzaturaStato,
    AttrezzaturaTask,
    AttrezzaturaTaskStato,
    AttrezzaturaTaskTipo,
    DisponibilitaStato,
)
from .services import excel_import, kickoff_integration, workflow
from core.legacy_models import Permesso, Pulsante, Ruolo
from core.models import NavigationItem, PermissionDefinition, RolePermissionGrant, RoutePermissionBinding

User = get_user_model()


def make_workbook(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "ATTREZZI"
    ws.append(["legacy", "intro"])
    ws.append(["", ""])
    ws.append([
        "Finiti",
        "Ordine",
        "Codice",
        "N. Pezzi",
        "Avanzamento",
        "Note e consegna",
        "Data consegna",
        "Particolare",
        "Descrizione",
        "N. OG",
        "Note Rocco",
        "OG",
    ])
    for row in rows:
        ws.append(row)
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    stream.name = "Avanzamento attrezzi.xlsx"
    return stream


class AttrezzaturaModelTests(TestCase):
    def test_attrezzatura_properties(self):
        late = timezone.localdate() - timedelta(days=1)
        tool = Attrezzatura.objects.create(
            codice="A1",
            part_number="PN-1",
            stato=AttrezzaturaStato.IN_CORSO,
            data_consegna_prevista=late,
        )
        self.assertFalse(tool.is_finita)
        self.assertFalse(tool.is_pronta_produzione)
        self.assertTrue(tool.is_in_ritardo)
        tool.stato = AttrezzaturaStato.FINITA
        self.assertTrue(tool.is_finita)
        self.assertFalse(tool.is_in_ritardo)
        tool.stato = AttrezzaturaStato.PRONTA_PRODUZIONE
        self.assertTrue(tool.is_pronta_produzione)

    def test_task_can_exist_without_and_with_attrezzatura(self):
        task = AttrezzaturaTask.objects.create(
            part_number="PN-2",
            tipo=AttrezzaturaTaskTipo.CREAZIONE_ATTREZZO,
            titolo="Creare attrezzo",
        )
        self.assertIsNone(task.attrezzatura)
        tool = Attrezzatura.objects.create(codice="T2", part_number="PN-2")
        task.attrezzatura = tool
        task.save()
        self.assertEqual(task.attrezzatura, tool)

    def test_attrezzatura_part_number_unique(self):
        tool = Attrezzatura.objects.create(codice="T3")
        AttrezzaturaPartNumber.objects.create(attrezzatura=tool, part_number="PN-3")
        with self.assertRaises(IntegrityError):
            from django.db import transaction

            with transaction.atomic():
                AttrezzaturaPartNumber.objects.create(attrezzatura=tool, part_number="PN-3")


class PartNumberServiceTests(TestCase):
    def test_normalize_part_number_and_lookup(self):
        tool = Attrezzatura.objects.create(codice="T4", part_number="PN 4")
        AttrezzaturaPartNumber.objects.create(attrezzatura=tool, part_number="ALT-4")
        self.assertEqual(kickoff_integration.normalize_part_number(" pn  4 "), "PN 4")
        self.assertEqual(list(kickoff_integration.get_attrezzature_for_part_number("alt-4")), [tool])


class ExcelImportTests(TestCase):
    def test_maps_particolare_and_preserves_og_payload(self):
        stream = make_workbook([["", "", "C1", 2, "75%", "note", "01/05/2026", "pn-1", "Desc", "OG123", "Rocco", "OG raw"]])
        preview = excel_import.build_import_preview(stream, filename=stream.name)
        row = preview["row_previews"][0]
        self.assertEqual(row["normalized"]["part_number"], "PN-1")
        self.assertIn("n_og", row["payload_originale_json"])
        self.assertIn("og", row["payload_originale_json"])

    def test_excel_datetime_date_does_not_block_import(self):
        stream = make_workbook([["", "", "CISO", 1, "75%", "", datetime(2026, 4, 28), "PN-ISO", "Desc", "", "", ""]])
        preview = excel_import.build_import_preview(stream, filename=stream.name)
        row = preview["row_previews"][0]
        self.assertEqual(row["normalized"]["part_number"], "PN-ISO")
        self.assertEqual(row["normalized"]["data_consegna_prevista"].isoformat(), "2026-04-28")
        self.assertEqual(row["warnings"], [])
        self.assertEqual(row["proposed_action"], "created")

    def test_ordine_mapping(self):
        cases = [
            ("x", AttrezzaturaStato.FINITA, "created"),
            ("o", AttrezzaturaStato.DA_CLASSIFICARE, "skipped"),
            (3, AttrezzaturaStato.IN_CORSO, "created"),
            ("", AttrezzaturaStato.DA_CLASSIFICARE, "created"),
            ("z", AttrezzaturaStato.ECCEZIONE, "created"),
        ]
        for ordine, expected_stato, expected_action in cases:
            stream = make_workbook([["", ordine, f"C{ordine}", 1, "", "", "", "PN", "Desc", "", "", ""]])
            row = excel_import.build_import_preview(stream, filename=stream.name)["row_previews"][0]
            self.assertEqual(row["normalized"]["stato"], expected_stato)
            self.assertEqual(row["proposed_action"], expected_action)
            if ordine == 3:
                self.assertEqual(row["normalized"]["ordine_visuale"], 3)

    def test_progress_mapping(self):
        for raw, expected in [(0.75, 75), ("75%", 75), (".", None)]:
            value, warnings = excel_import.normalize_progress(raw)
            self.assertEqual(value, expected)
            self.assertEqual(warnings, [])

    def test_dry_run_does_not_write_and_confirm_creates(self):
        stream = make_workbook([["", "", "C2", 1, 75, "", "", "PN-2", "Desc", "OG", "", "OG raw"]])
        preview = excel_import.build_import_preview(stream, filename=stream.name)
        self.assertEqual(preview["summary"]["created"], 1)
        self.assertEqual(Attrezzatura.objects.count(), 0)
        stream.seek(0)
        result = excel_import.confirm_import(stream, filename=stream.name)
        self.assertEqual(result["summary"]["created"], 1)
        self.assertEqual(Attrezzatura.objects.get().part_number, "PN-2")
        self.assertEqual(AttrezzaturaImportRow.objects.get().payload_originale_json["og"], "OG raw")

    def test_duplicate_codice_different_part_number_does_not_overwrite(self):
        existing = Attrezzatura.objects.create(codice="DUP", part_number="PN-A", descrizione="Old")
        stream = make_workbook([["", "", "DUP", 1, "", "", "", "PN-B", "New", "", "", ""]])
        excel_import.confirm_import(stream, filename=stream.name)
        existing.refresh_from_db()
        self.assertEqual(existing.part_number, "PN-A")
        self.assertEqual(Attrezzatura.objects.filter(codice="DUP").count(), 2)

    def test_ambiguous_match_creates_warning(self):
        Attrezzatura.objects.create(codice="AMB", part_number="PN-A", descrizione="Same")
        Attrezzatura.objects.create(codice="AMB", part_number="PN-A", descrizione="Same")
        stream = make_workbook([["", "", "AMB", 1, "", "", "", "PN-A", "Same", "", "", ""]])
        row = excel_import.build_import_preview(stream, filename=stream.name)["row_previews"][0]
        self.assertEqual(row["proposed_action"], "warning")
        self.assertTrue(row["warnings"])


class WorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")

    def test_complete_and_block_task(self):
        task = AttrezzaturaTask.objects.create(tipo=AttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA, titolo="Check", part_number="PN")
        workflow.complete_task(task, user=self.user, note="ok")
        task.refresh_from_db()
        self.assertEqual(task.stato, AttrezzaturaTaskStato.COMPLETATA)
        self.assertEqual(task.completed_by, self.user)
        self.assertIsNotNone(task.completed_at)
        workflow.block_task(task, user=self.user, reason="blocked")
        task.refresh_from_db()
        self.assertEqual(task.stato, AttrezzaturaTaskStato.BLOCCATA)
        self.assertEqual(task.blocked_reason, "blocked")

    def test_confirm_ready_creates_avanzamento(self):
        tool = Attrezzatura.objects.create(codice="R1", part_number="PN-R", stato=AttrezzaturaStato.IN_CORSO)
        AttrezzaturaTask.objects.create(attrezzatura=tool, tipo=AttrezzaturaTaskTipo.CONFERMA_PRONTA_PRODUZIONE, titolo="Ready")
        workflow.confirm_ready_for_production(tool, user=self.user, note="ready")
        tool.refresh_from_db()
        self.assertEqual(tool.stato, AttrezzaturaStato.PRONTA_PRODUZIONE)
        self.assertEqual(tool.disponibilita_stato, DisponibilitaStato.DISPONIBILE)
        self.assertTrue(AttrezzaturaAvanzamento.objects.filter(attrezzatura=tool).exists())
        self.assertEqual(tool.tasks.get().stato, AttrezzaturaTaskStato.COMPLETATA)

    def test_delay_check_task_deduplicates(self):
        tool = Attrezzatura.objects.create(codice="L1", data_consegna_prevista=timezone.localdate() - timedelta(days=1))
        first = workflow.create_delay_check_task(tool, user=self.user)
        second = workflow.create_delay_check_task(tool, user=self.user)
        self.assertEqual(first.pk, second.pk)


class KickoffBoundaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester")

    def test_embedded_context_and_plain_refs(self):
        tool = Attrezzatura.objects.create(codice="K1", part_number="PN-K")
        task = AttrezzaturaTask.objects.create(
            attrezzatura=tool,
            part_number="PN-K",
            tipo=AttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
            titolo="Check",
            external_kickoff_id="10",
            external_kickoff_activity_id="20",
        )
        ctx = kickoff_integration.build_kickoff_attrezzatura_context("pn-k", kickoff_ref="10", kickoff_activity_ref="20")
        self.assertIn(tool, ctx["attrezzature"])
        self.assertIn(task, ctx["tasks"])
        self.assertEqual(task.external_kickoff_id, "10")

    def test_draft_update_complete_and_ready_from_kickoff(self):
        tool = kickoff_integration.create_draft_attrezzatura_from_kickoff(
            part_number="pn-x",
            description="Draft",
            kickoff_ref="k1",
            kickoff_activity_ref="a1",
            user=self.user,
        )
        self.assertEqual(tool.part_number, "PN-X")
        kickoff_integration.update_attrezzatura_progress_from_kickoff(tool, percentuale=50, stato=AttrezzaturaStato.IN_CORSO, user=self.user, kickoff_activity_ref="a2")
        self.assertTrue(AttrezzaturaAvanzamento.objects.filter(attrezzatura=tool).exists())
        task = AttrezzaturaTask.objects.filter(external_kickoff_activity_id="a2").get()
        kickoff_integration.complete_attrezzatura_task_from_kickoff(task, user=self.user, note="done")
        task.refresh_from_db()
        self.assertEqual(task.stato, AttrezzaturaTaskStato.COMPLETATA)
        kickoff_integration.confirm_attrezzatura_ready_from_kickoff(tool, user=self.user, kickoff_activity_ref="a3")
        tool.refresh_from_db()
        self.assertEqual(tool.stato, AttrezzaturaStato.PRONTA_PRODUZIONE)
        ctx = kickoff_integration.build_kickoff_attrezzatura_context("PN-X")
        self.assertEqual(ctx["summary"]["ready_count"], 1)


class RouteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="admin", password="x")
        self.client.force_login(self.user)
        self.tool = Attrezzatura.objects.create(codice="WEB", part_number="PN-W")

    def test_main_routes_work_for_authenticated_users(self):
        routes = [
            reverse("attrezzature:list"),
            reverse("attrezzature:detail", kwargs={"pk": self.tool.pk}),
            reverse("attrezzature:import"),
            reverse("attrezzature:task_list"),
            reverse("attrezzature:embedded_preview"),
        ]
        for url in routes:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_superuser_can_delete_single_attrezzatura(self):
        response = self.client.post(reverse("attrezzature:delete", kwargs={"pk": self.tool.pk}))
        self.assertRedirects(response, reverse("attrezzature:list"))
        self.assertFalse(Attrezzatura.objects.filter(pk=self.tool.pk).exists())

    def test_superuser_can_delete_multiple_attrezzature(self):
        other = Attrezzatura.objects.create(codice="WEB2", part_number="PN-W2")
        response = self.client.post(
            reverse("attrezzature:bulk_delete"),
            {"selected_ids": [str(self.tool.pk), str(other.pk)]},
        )
        self.assertRedirects(response, reverse("attrezzature:list"))
        self.assertFalse(Attrezzatura.objects.filter(pk__in=[self.tool.pk, other.pk]).exists())

    def test_non_admin_cannot_delete_attrezzatura(self):
        self.client.force_login(User.objects.create_user(username="user", password="x"))
        response = self.client.post(reverse("attrezzature:delete", kwargs={"pk": self.tool.pk}))
        self.assertIn(response.status_code, {302, 403})
        self.assertTrue(Attrezzatura.objects.filter(pk=self.tool.pk).exists())


class AttrezzaturaAclBootstrapTests(TestCase):
    def setUp(self):
        Ruolo.objects.create(id=1, nome="admin")
        Ruolo.objects.create(id=2, nome="caporeparto")
        Ruolo.objects.create(id=3, nome="utente")

    def test_create_attrezzature_nav_bootstraps_permissions_buttons_and_access(self):
        call_command("create_attrezzature_nav", verbosity=0)

        self.assertTrue(Pulsante.objects.filter(modulo="attrezzature", codice="attrezzature_view").exists())
        self.assertTrue(Permesso.objects.filter(modulo="attrezzature", azione="attrezzature_view").exists())
        self.assertTrue(PermissionDefinition.objects.filter(code="attrezzature.attrezzature.view").exists())
        self.assertTrue(
            RoutePermissionBinding.objects.filter(
                route_name="attrezzature:list",
                permission_id="attrezzature.attrezzature.view",
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            RoutePermissionBinding.objects.filter(
                route_name="attrezzature:bulk_delete",
                permission_id="attrezzature.attrezzature.delete",
                is_active=True,
            ).exists()
        )
        self.assertTrue(
            RolePermissionGrant.objects.filter(
                legacy_role_id=1,
                permission_id="attrezzature.attrezzature.delete",
                enabled=True,
            ).exists()
        )
        self.assertTrue(
            RolePermissionGrant.objects.filter(
                legacy_role_id=2,
                permission_id="attrezzature.tasks.manage",
                enabled=True,
            ).exists()
        )
        self.assertFalse(
            RolePermissionGrant.objects.filter(
                legacy_role_id=3,
                permission_id="attrezzature.attrezzature.view",
                enabled=True,
            ).exists()
        )
        nav = NavigationItem.objects.get(code="gestione-attrezzatura")
        self.assertEqual(nav.required_permission_code, "attrezzature.attrezzature.view")
