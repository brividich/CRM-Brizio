"""Manutenzione > Verifiche periodiche (impianti): dominio, pagine, import storico."""

from __future__ import annotations

import io
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.maintenance_nav import HELP_TEXTS, find_active
from assets.models import (
    Asset,
    PeriodicCheckAttachment,
    PeriodicCheckItem,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
    WorkOrder,
)
from assets.services import periodic_checks as checks
from assets.services import periodic_checks_import as importer
from assets.services.periodic_checks_catalog import ArchiveSource, CatalogType

User = get_user_model()

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _make_type(**kwargs) -> PeriodicCheckType:
    system = kwargs.pop("system", None) or PeriodicCheckSystem.objects.create(name=kwargs.pop("system_name", "Impianto elettrico"))
    defaults = {"name": "Verifica quadri elettrici", "frequency_months": 6, "method": PeriodicCheckType.METHOD_CHECKLIST}
    defaults.update(kwargs)
    return PeriodicCheckType.objects.create(system=system, **defaults)


class DateParsingTests(SimpleTestCase):
    def test_formati_dei_nomi_file(self):
        cases = {
            "Verifica plafoniere d'emergenza 14-10-24": (date(2024, 10, 14), importer.PRECISION_DAY),
            "29_10_2025 Verifica Impianto messa a Terra": (date(2025, 10, 29), importer.PRECISION_DAY),
            "11.11.2023_Verifica USL": (date(2023, 11, 11), importer.PRECISION_DAY),
            "Y2020_CABINA_20230227_BRUSCHI": (date(2023, 2, 27), importer.PRECISION_DAY),
            "Verifica cabine MT-BT 01-2026": (date(2026, 1, 1), importer.PRECISION_MONTH),
            "2024 prove differenziali": (date(2024, 1, 1), importer.PRECISION_YEAR),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(importer.parse_date(text), expected)
        self.assertIsNone(importer.parse_date("Pacco1"))
        self.assertIsNone(importer.parse_date("1881_001"))

    def test_data_dalla_cartella_se_il_nome_non_basta(self):
        root = Path("C:/archivio")
        path = root / "2026" / "01-2026" / "Pacco1.pdf"
        self.assertEqual(importer.date_for(path, root), (date(2026, 1, 1), importer.PRECISION_MONTH))
        path = root / "2023" / "12-04-2023" / "20230412141435.pdf"
        self.assertEqual(importer.date_for(path, root), (date(2023, 4, 12), importer.PRECISION_DAY))


class ScanTests(SimpleTestCase):
    def test_raggruppa_per_data_ed_esclude_i_documenti_non_esito(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "Verifica UPS"
            (base / "2026" / "01-2026").mkdir(parents=True)
            (base / "2026" / "01-2026" / "Pacco1.pdf").write_bytes(PDF_BYTES)
            (base / "2026" / "01-2026" / "Pacco 2.pdf").write_bytes(PDF_BYTES)
            (base / "05-2025.pdf").write_bytes(PDF_BYTES)
            (base / "PLANIMETRIA UPS.pdf").write_bytes(PDF_BYTES)
            (base / "note.msg").write_bytes(b"x")
            (base / "Senza data.pdf").write_bytes(PDF_BYTES)
            entry = CatalogType("Impianto elettrico", "Verifica UPS", 4, PeriodicCheckType.METHOD_MEASURES,
                                sources=[ArchiveSource("Verifica UPS")])
            report = importer.scan(root, [entry])
        dates = [(s.performed_on, len(s.files)) for s in report.sessions]
        self.assertEqual(dates, [(date(2025, 5, 1), 1), (date(2026, 1, 1), 2)])
        reasons = {p.name: r for p, r in report.skipped}
        self.assertIn("PLANIMETRIA UPS.pdf", reasons)
        self.assertEqual(reasons["Senza data.pdf"], "data non riconoscibile")
        self.assertNotIn("note.msg", reasons)


@override_settings(LEGACY_AUTH_ENABLED=False)
class DominioTests(TestCase):
    def test_prossima_scadenza_dalla_frequenza_e_dal_verbale(self):
        check_type = _make_type()
        checks.register_session(checks.SessionInput(check_type, date(2026, 1, 12), PeriodicCheckSession.OUTCOME_OK))
        check_type.refresh_from_db()
        self.assertEqual(check_type.next_due_date, date(2026, 7, 12))
        # Il verbale indica una data diversa: vince quella.
        checks.register_session(checks.SessionInput(
            check_type, date(2026, 7, 10), PeriodicCheckSession.OUTCOME_OK, next_due_date=date(2027, 1, 31)
        ))
        check_type.refresh_from_db()
        self.assertEqual(check_type.next_due_date, date(2027, 1, 31))
        # Una verifica piu' vecchia registrata dopo non sposta la scadenza.
        checks.register_session(checks.SessionInput(check_type, date(2025, 7, 1), PeriodicCheckSession.OUTCOME_OK))
        check_type.refresh_from_db()
        self.assertEqual(check_type.next_due_date, date(2027, 1, 31))

    def test_bozza_non_sposta_la_scadenza_finche_non_confermata(self):
        check_type = _make_type(next_due_date=date(2026, 1, 1))
        session = checks.register_session(checks.SessionInput(
            check_type, date(2026, 1, 5), PeriodicCheckSession.OUTCOME_OK, status=PeriodicCheckSession.STATUS_DRAFT
        ))
        check_type.refresh_from_db()
        self.assertEqual(check_type.next_due_date, date(2026, 1, 1))
        checks.confirm_session(session)
        check_type.refresh_from_db()
        self.assertEqual(check_type.next_due_date, date(2026, 7, 5))

    def test_voce_non_ok_rende_la_verifica_con_rilievi(self):
        check_type = _make_type()
        session = checks.register_session(checks.SessionInput(
            check_type, date(2026, 1, 5), PeriodicCheckSession.OUTCOME_OK,
            results=[checks.ResultInput("Esame a vista"), checks.ResultInput("Serraggio", result=PeriodicCheckResult.RESULT_KO)],
        ))
        self.assertEqual(session.outcome, PeriodicCheckSession.OUTCOME_REMARKS)

    def test_stato(self):
        today = date(2026, 9, 25)
        check_type = _make_type(warning_days=30)
        self.assertEqual(checks.type_state(check_type, today), checks.STATE_UNSCHEDULED)
        check_type.next_due_date = today - timedelta(days=1)
        self.assertEqual(checks.type_state(check_type, today), checks.STATE_OVERDUE)
        check_type.next_due_date = today + timedelta(days=30)
        self.assertEqual(checks.type_state(check_type, today), checks.STATE_DUE_SOON)
        check_type.next_due_date = today + timedelta(days=31)
        self.assertEqual(checks.type_state(check_type, today), checks.STATE_OK)


@override_settings(LEGACY_AUTH_ENABLED=False)
class PagineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="pc-admin", password="x", email="pc@y.z")
        cls.asset = Asset.objects.create(asset_tag="QG-01", name="Quadro generale")
        cls.system = PeriodicCheckSystem.objects.create(name="Impianto elettrico", asset=cls.asset)
        cls.check_type = _make_type(system=cls.system, next_due_date=timezone.localdate() - timedelta(days=3))
        cls.item_ok = PeriodicCheckItem.objects.create(check_type=cls.check_type, label="Esame a vista", sort_order=10)
        cls.item_ko = PeriodicCheckItem.objects.create(check_type=cls.check_type, label="Controllo temperature", sort_order=20)

    def setUp(self):
        self.client.force_login(self.admin)
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)

    def test_elenco_raggruppato_per_impianto_con_stato(self):
        response = self.client.get(reverse("assets:periodic_check_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Impianto elettrico")
        self.assertContains(response, "Verifica quadri elettrici")
        self.assertContains(response, "pc-state is-overdue")
        self.assertContains(response, reverse("assets:periodic_check_register", args=[self.check_type.id]))
        self.assertNotContains(response, "{#")

    def test_registra_checklist_con_voce_ko_e_documento(self):
        performed = timezone.localdate()
        response = self.client.post(
            reverse("assets:periodic_check_register", args=[self.check_type.id]),
            {
                "performed_on": performed.isoformat(),
                "outcome": PeriodicCheckSession.OUTCOME_OK,
                "technician": "Tecnico prova",
                f"item_{self.item_ok.id}": "OK",
                f"item_{self.item_ko.id}": "KO",
                f"item_note_{self.item_ko.id}": "Morsetto caldo",
                "remarks_text": "Sostituire etichette\n\n",
                "files": [SimpleUploadedFile("rapportino.pdf", PDF_BYTES, content_type="application/pdf")],
            },
        )
        session = PeriodicCheckSession.objects.get(check_type=self.check_type)
        self.assertRedirects(response, reverse("assets:periodic_check_session_detail", args=[session.id]))
        self.assertEqual(session.outcome, PeriodicCheckSession.OUTCOME_REMARKS)
        self.assertEqual(session.results.filter(result=PeriodicCheckResult.RESULT_KO).count(), 2)
        self.assertEqual(session.results.get(item=self.item_ko).note, "Morsetto caldo")
        self.assertEqual(session.attachments.count(), 1)
        self.check_type.refresh_from_db()
        self.assertEqual(self.check_type.next_due_date, self.check_type.next_due_from(performed))

        detail = self.client.get(reverse("assets:periodic_check_session_detail", args=[session.id]))
        self.assertContains(detail, "Crea OdL")
        self.assertContains(detail, "Morsetto caldo")

        attachment = session.attachments.get()
        download = self.client.get(reverse("assets:periodic_check_attachment_download", args=[attachment.id]))
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), PDF_BYTES)

    def test_odl_dal_rilievo_con_asset_dell_impianto(self):
        session = checks.register_session(checks.SessionInput(
            self.check_type, timezone.localdate(), PeriodicCheckSession.OUTCOME_KO,
            results=[checks.ResultInput("Quadro Q3 senza targhetta", kind=PeriodicCheckResult.KIND_REMARK,
                                        result=PeriodicCheckResult.RESULT_KO)],
        ))
        result = session.results.get()
        url = reverse("assets:periodic_check_session_detail", args=[session.id])
        self.client.post(url, {"action": "work_order", "result_id": result.id, "asset": self.asset.id, "title": "Targhetta Q3"})
        result.refresh_from_db()
        self.assertIsNotNone(result.work_order_id)
        work_order = result.work_order
        self.assertEqual((work_order.asset_id, work_order.title, work_order.kind),
                         (self.asset.id, "Targhetta Q3", WorkOrder.KIND_CORRECTIVE))
        # Un secondo invio non apre un altro OdL.
        self.client.post(url, {"action": "work_order", "result_id": result.id, "asset": self.asset.id, "title": "X"})
        self.assertEqual(WorkOrder.objects.filter(periodic_check_results=result).count(), 1)

    def test_senza_permessi_non_registra_ne_scarica(self):
        session = checks.register_session(checks.SessionInput(self.check_type, timezone.localdate(), "OK"))
        attachment = checks.add_attachment(session, SimpleUploadedFile("v.pdf", PDF_BYTES))
        with mock.patch("assets.views_verifiche.can_execute_maintenance", return_value=False):
            response = self.client.post(
                reverse("assets:periodic_check_register", args=[self.check_type.id]),
                {"performed_on": timezone.localdate().isoformat(), "outcome": "OK"},
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(PeriodicCheckSession.objects.count(), 1)
            download = self.client.get(reverse("assets:periodic_check_attachment_download", args=[attachment.id]))
            self.assertEqual(download.status_code, 403)
        with mock.patch("assets.views_verifiche.can_manage_maintenance_plans", return_value=False):
            response = self.client.get(reverse("assets:periodic_check_type_create"))
            self.assertEqual(response.status_code, 302)

    def test_configura_tipo_con_voci_di_checklist(self):
        response = self.client.post(reverse("assets:periodic_check_type_create"), {
            "system": self.system.id,
            "name": "Verifica cabine MT/BT",
            "method": PeriodicCheckType.METHOD_CHECKLIST,
            "frequency_months": 12,
            "warning_days": 30,
            "items_text": "Pulizia cabine\nEsame a vista\n",
            "sort_order": 100,
            "is_active": "on",
        })
        created = PeriodicCheckType.objects.get(name="Verifica cabine MT/BT")
        self.assertRedirects(response, reverse("assets:periodic_check_type_detail", args=[created.id]))
        self.assertEqual(list(created.items.values_list("label", flat=True)), ["Pulizia cabine", "Esame a vista"])
        # Togliere una voce la spegne, non la cancella.
        self.client.post(reverse("assets:periodic_check_type_edit", args=[created.id]), {
            "system": self.system.id, "name": created.name, "method": created.method, "frequency_months": 12,
            "warning_days": 30, "items_text": "Esame a vista", "sort_order": 100, "is_active": "on",
        })
        self.assertEqual(list(created.items.filter(is_active=True).values_list("label", flat=True)), ["Esame a vista"])
        self.assertEqual(created.items.count(), 2)

    def test_pagine_config_e_dettaglio_rispondono(self):
        for name, args in (
            ("periodic_check_systems", []),
            ("periodic_check_type_detail", [self.check_type.id]),
            ("periodic_check_type_edit", [self.check_type.id]),
            ("periodic_check_register", [self.check_type.id]),
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(f"assets:{name}", args=args))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "{#")

    def test_voce_di_menu_e_spiegazione(self):
        self.assertIn("verifiche", HELP_TEXTS)
        group, item = find_active("periodic_check_session_detail")
        self.assertEqual(item.key, "verifiche")


@override_settings(LEGACY_AUTH_ENABLED=False)
class ComandiTests(TestCase):
    def test_seed_a_vuoto_non_scrive_e_apply_e_idempotente(self):
        call_command("seed_periodic_checks", stdout=io.StringIO())
        self.assertFalse(PeriodicCheckType.objects.exists())
        call_command("seed_periodic_checks", "--apply", stdout=io.StringIO())
        count = PeriodicCheckType.objects.count()
        self.assertGreaterEqual(count, 10)
        quadri = PeriodicCheckType.objects.get(name="Verifica quadri elettrici")
        self.assertEqual((quadri.frequency_months, quadri.reference_code, quadri.items.count()), (6, "005", 5))
        call_command("seed_periodic_checks", "--apply", stdout=io.StringIO())
        self.assertEqual(PeriodicCheckType.objects.count(), count)

    def test_import_storico_idempotente(self):
        call_command("seed_periodic_checks", "--apply", stdout=io.StringIO())
        with tempfile.TemporaryDirectory() as archive, tempfile.TemporaryDirectory() as private:
            base = Path(archive) / "_Impianto Elettrico" / "Verifiche impianto elettrico" / "Verifica quadri elettrici (semestrale)"
            (base / "2025").mkdir(parents=True)
            (base / "2025" / "Verifica quadri elettrici 07-2025.pdf").write_bytes(PDF_BYTES)
            (base / "2026").mkdir()
            (base / "2026" / "Verifica quadri elettrici 01-2026.pdf").write_bytes(PDF_BYTES)
            with override_settings(ASSETS_PRIVATE_ROOT=private):
                call_command("import_periodic_checks", archive, stdout=io.StringIO())
                self.assertFalse(PeriodicCheckSession.objects.exists())
                call_command("import_periodic_checks", archive, "--apply", stdout=io.StringIO())
                call_command("import_periodic_checks", archive, "--apply", stdout=io.StringIO())
                sessions = PeriodicCheckSession.objects.filter(check_type__name="Verifica quadri elettrici")
                self.assertEqual(sessions.count(), 2)
                self.assertTrue(all(s.outcome == PeriodicCheckSession.OUTCOME_ARCHIVE for s in sessions))
                self.assertEqual(PeriodicCheckAttachment.objects.count(), 2)
                quadri = PeriodicCheckType.objects.get(name="Verifica quadri elettrici")
                self.assertEqual(quadri.next_due_date, date(2026, 7, 1))
