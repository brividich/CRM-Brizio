"""Verifiche periodiche: cartella di pescaggio (lo scanner deposita, il QR smista)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import (
    PeriodicCheckIntakeConfig,
    PeriodicCheckIntakeLog,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
)
from assets.services import periodic_checks as checks
from assets.services import periodic_intake
from assets.tests_periodic_layout import TITLE_BLOCK, fake_scan, synthetic_plan
from core.qr import disponibile as qr_disponibile

User = get_user_model()


def blank_page() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Pagina senza QR", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def join_pdfs(*parts: bytes) -> bytes:
    out = fitz.open()
    for part in parts:
        with fitz.open(stream=part, filetype="pdf") as src:
            out.insert_pdf(src)
    data = out.tobytes()
    out.close()
    return data


@override_settings(LEGACY_AUTH_ENABLED=False)
class CartellaTests(TestCase):
    def setUp(self):
        if not qr_disponibile():
            self.skipTest("zxing-cpp non installato")
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=str(Path(self._tmp.name) / "private"))
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)
        self.inbox = Path(self._tmp.name) / "scanner"
        self.inbox.mkdir()
        self.admin = User.objects.create_superuser(username="pi-admin", password="x", email="pi@y.z")
        system = PeriodicCheckSystem.objects.create(name="Impianto elettrico")
        self.check_type = PeriodicCheckType.objects.create(system=system, name="Luci", frequency_months=4,
                                                           method=PeriodicCheckType.METHOD_LAYOUT)
        self.layout = checks.create_layout(self.check_type, synthetic_plan(), exclude_areas=[TITLE_BLOCK])
        self.config = PeriodicCheckIntakeConfig.load()
        self.config.cartella = str(self.inbox)
        self.config.attiva = True
        self.config.save()
        stable = mock.patch("assets.services.periodic_intake.STABLE_WAIT_SECONDS", 0)
        stable.start()
        self.addCleanup(stable.stop)

    def _scan_of(self, session, **marks) -> bytes:
        pdf, geo = checks.build_sheet_for(self.layout, token=session.sheet_token)
        return fake_scan(pdf, geo, **marks)

    def test_pdf_con_due_fogli_uno_riconosciuto_uno_da_smistare(self):
        session = checks.issue_sheet(self.check_type)
        (self.inbox / "scanner_001.pdf").write_bytes(join_pdfs(self._scan_of(session, highlight=("4",)), blank_page()))
        result = periodic_intake.process_folder()
        self.assertEqual((result["esaminati"], result["pagine"], result["letti"], result["da_smistare"]), (1, 2, 1, 1))
        session.refresh_from_db()
        self.assertEqual(session.status, PeriodicCheckSession.STATUS_DRAFT)
        self.assertEqual(list(session.results.values_list("point__code", flat=True)), ["4"])
        unmatched = PeriodicCheckIntakeLog.objects.get(outcome=PeriodicCheckIntakeLog.OUTCOME_UNMATCHED)
        self.assertTrue(unmatched.scan)
        self.assertEqual(unmatched.file_name, "scanner_001-p2.pdf")
        # il file non e' letto del tutto: finisce in «errori», la cartella resta pulita
        self.assertFalse((self.inbox / "scanner_001.pdf").exists())
        self.assertTrue((self.inbox / "errori" / "scanner_001.pdf").exists())
        self.config.refresh_from_db()
        self.assertIn("1 da smistare", self.config.ultimo_esito)

    def test_spenta_non_legge_ma_il_comando_forzato_si(self):
        self.config.attiva = False
        self.config.save()
        session = checks.issue_sheet(self.check_type)
        (self.inbox / "foglio.pdf").write_bytes(self._scan_of(session))
        self.assertEqual(periodic_intake.process_folder()["riepilogo"], "Acquisizione da cartella spenta.")
        call_command("intake_verifiche_periodiche", "--forza", stdout=open(Path(self._tmp.name) / "out.txt", "w"))
        session.refresh_from_db()
        self.assertEqual(session.status, PeriodicCheckSession.STATUS_DRAFT)
        self.assertTrue((self.inbox / "elaborati" / "foglio.pdf").exists())

    def test_foglio_di_verifica_gia_confermata_da_smistare(self):
        session = checks.issue_sheet(self.check_type)
        checks.confirm_session(session)
        (self.inbox / "tardi.pdf").write_bytes(self._scan_of(session))
        periodic_intake.process_folder()
        log = PeriodicCheckIntakeLog.objects.get()
        self.assertEqual(log.outcome, PeriodicCheckIntakeLog.OUTCOME_UNMATCHED)
        self.assertIn("gia' confermata", log.message)

    def test_pagina_carica_smista_e_associa_a_mano(self):
        self.client.force_login(self.admin)
        url = reverse("assets:periodic_check_intake")
        session = checks.issue_sheet(self.check_type)
        other = checks.issue_sheet(self.check_type)
        self.client.post(url, {"action": "upload", "scan": SimpleUploadedFile(
            "caricato.pdf", join_pdfs(self._scan_of(session, highlight=("2",)), blank_page()), content_type="application/pdf")})
        session.refresh_from_db()
        self.assertEqual(session.status, PeriodicCheckSession.STATUS_DRAFT)
        page = self.client.get(url)
        self.assertContains(page, "Da smistare")
        self.assertContains(page, "caricato-p2.pdf")
        self.assertNotContains(page, "{#")
        log = PeriodicCheckIntakeLog.objects.get(outcome=PeriodicCheckIntakeLog.OUTCOME_UNMATCHED)
        self.assertEqual(self.client.get(reverse("assets:periodic_check_intake_scan", args=[log.id])).status_code, 200)
        response = self.client.post(url, {"action": "assign", "log_id": log.id, "session_id": other.id})
        self.assertRedirects(response, reverse("assets:periodic_check_session_detail", args=[other.id]),
                             fetch_redirect_response=False)
        log.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((log.outcome, log.session_id), (PeriodicCheckIntakeLog.OUTCOME_ASSIGNED, other.id))
        self.assertEqual(other.status, PeriodicCheckSession.STATUS_DRAFT)

    def test_configurazione_solo_per_chi_configura(self):
        self.client.force_login(self.admin)
        url = reverse("assets:periodic_check_intake")
        self.client.post(url, {"action": "config", "cartella": r"\\server\scansioni\verifiche", "attiva": "on",
                               "sposta_elaborati": "on", "max_file_per_giro": 10})
        self.config.refresh_from_db()
        self.assertEqual((self.config.cartella, self.config.max_file_per_giro), (r"\\server\scansioni\verifiche", 10))
        with mock.patch("assets.views_verifiche.can_manage_maintenance_plans", return_value=False):
            self.client.post(url, {"action": "config", "cartella": "altro", "max_file_per_giro": 5})
        self.config.refresh_from_db()
        self.assertEqual(self.config.max_file_per_giro, 10)
