"""Verifiche periodiche a misure: grandezze con soglie, griglia, foglio con QR, conferma, statistiche."""

from __future__ import annotations

import io
import tempfile
from datetime import date
from decimal import Decimal

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.forms_verifiche import PeriodicCheckTypeForm
from assets.models import (
    PeriodicCheckItem,
    PeriodicCheckMeasureField,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
)
from assets.services import periodic_checks as checks
from assets.services import periodic_intake, periodic_stats
from core.qr import disponibile as qr_disponibile
from core.qr import leggi_codici

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class MisureTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        override = override_settings(ASSETS_PRIVATE_ROOT=self._tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(self._tmp.cleanup)
        self.admin = User.objects.create_superuser(username="pm-admin", password="x", email="pm@y.z")
        self.client.force_login(self.admin)
        self.system = PeriodicCheckSystem.objects.create(name="Impianto elettrico")
        self.ups = PeriodicCheckType.objects.create(system=self.system, name="UPS", frequency_months=4,
                                                    method=PeriodicCheckType.METHOD_MEASURES)
        self.b1 = PeriodicCheckItem.objects.create(check_type=self.ups, label="Pacco 1 · Batteria 1", sort_order=10)
        self.b2 = PeriodicCheckItem.objects.create(check_type=self.ups, label="Pacco 1 · Batteria 2", sort_order=20)
        self.vuoto = PeriodicCheckMeasureField.objects.create(check_type=self.ups, label="Tensione a vuoto", unit="V", sort_order=10)
        self.fine = PeriodicCheckMeasureField.objects.create(check_type=self.ups, label="Tensione fine prova", unit="V",
                                                             min_value=Decimal("11.5"), sort_order=20)

    def test_form_grandezze_con_soglie(self):
        data = {
            "system": self.system.id, "name": "Differenziali", "method": PeriodicCheckType.METHOD_MEASURES,
            "frequency_months": 12, "warning_days": 30, "sort_order": 100, "is_active": "on",
            "items_text": "", "fields_text": "Tempo di intervento | ms | | 300\nCorrente | mA | 10 | 1000",
        }
        form = PeriodicCheckTypeForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        form.save_measure_fields(saved)
        tempo = saved.measure_fields.get(label="Tempo di intervento")
        self.assertEqual((tempo.unit, tempo.min_value, tempo.max_value, tempo.range_label), ("ms", None, Decimal("300"), "≤ 300"))
        self.assertFalse(PeriodicCheckTypeForm({**data, "fields_text": "Tempo | ms | tanti |"}).is_valid())
        self.assertFalse(PeriodicCheckTypeForm({**data, "fields_text": ""}).is_valid())

    def test_registrazione_con_griglia(self):
        url = reverse("assets:periodic_check_register", args=[self.ups.id])
        page = self.client.get(url)
        self.assertContains(page, "Valori misurati")
        self.assertContains(page, f'name="m_{self.b1.id}_{self.fine.id}"')
        base = {"performed_on": timezone.localdate().isoformat(), "outcome": "OK"}
        bad = self.client.post(url, {**base, f"m_{self.b1.id}_{self.fine.id}": "dodici"})
        self.assertContains(bad, "non e&#x27; un numero")
        self.client.post(url, {
            **base,
            f"m_{self.b1.id}_{self.vuoto.id}": "13,5", f"m_{self.b1.id}_{self.fine.id}": "12,1",
            f"m_{self.b2.id}_{self.fine.id}": "11,2",
            "l_x0": "Pacco 3 · Batteria 1", "r_x0": "on", "n_x0": "gonfia",
        })
        session = PeriodicCheckSession.objects.get()
        rows = {r.label: r for r in session.results.all()}
        self.assertEqual(rows["Pacco 1 · Batteria 1"].result, "OK")
        self.assertEqual(rows["Pacco 1 · Batteria 1"].values, {str(self.vuoto.id): 13.5, str(self.fine.id): 12.1})
        self.assertEqual(rows["Pacco 1 · Batteria 2"].result, "KO")
        self.assertIn("Tensione fine prova fuori soglia", rows["Pacco 1 · Batteria 2"].note)
        self.assertEqual((rows["Pacco 3 · Batteria 1"].category, rows["Pacco 3 · Batteria 1"].note), ("Da sostituire", "Da sostituire; gonfia"))
        self.assertEqual(session.outcome, PeriodicCheckSession.OUTCOME_REMARKS)
        detail = self.client.get(reverse("assets:periodic_check_session_detail", args=[session.id]))
        self.assertContains(detail, "Valori misurati")
        self.assertContains(detail, "is-out")

    def test_foglio_scansione_e_conferma(self):
        response = self.client.post(reverse("assets:periodic_check_sheet_issue", args=[self.ups.id]))
        session = PeriodicCheckSession.objects.get(status=PeriodicCheckSession.STATUS_ISSUED)
        self.assertEqual(response.status_code, 302)
        pdf = self.client.get(reverse("assets:periodic_check_sheet_pdf", args=[session.id])).content
        with fitz.open(stream=pdf, filetype="pdf") as doc:
            text = doc[0].get_text()
            png = doc[0].get_pixmap(dpi=150).tobytes("png")
        self.assertIn("Pacco 1 · Batteria 2", text)
        self.assertIn("min 11,5", text)
        if qr_disponibile():
            self.assertIn(f"NVC-VP:{session.sheet_token}", leggi_codici(png, "foglio.png"))
            # la scansione torna dalla cartella/pagina: allegata, la verifica aspetta i valori
            logs = periodic_intake.process_file(png, "scansione.png", source="CARICAMENTO")
            self.assertEqual(logs[0].outcome, "READ")
        else:
            checks.read_scan_into(session, png, name="scansione.png")
        session.refresh_from_db()
        self.assertEqual(session.status, PeriodicCheckSession.STATUS_DRAFT)
        url = reverse("assets:periodic_check_session_detail", args=[session.id])
        self.assertContains(self.client.get(url), "Riporta i valori dal foglio")
        self.client.post(url, {"action": "confirm_measures", "performed_on": "2026-09-20", "technician": "Tecnico",
                               f"m_{self.b1.id}_{self.fine.id}": "10,9"})
        session.refresh_from_db()
        self.assertEqual((session.status, session.outcome), (PeriodicCheckSession.STATUS_CONFIRMED, PeriodicCheckSession.OUTCOME_REMARKS))
        self.ups.refresh_from_db()
        self.assertEqual(self.ups.next_due_date, date(2027, 1, 20))

    def test_foglio_bloccato_senza_grandezze(self):
        self.ups.measure_fields.all().delete()
        with self.assertRaises(checks.LayoutError):
            checks.issue_sheet(self.ups)

    def test_statistiche_misure(self):
        fields = checks.measure_fields(self.ups)
        for day, low in ((date(2025, 9, 1), "11.0"), (date(2026, 1, 10), "11.1"), (date(2026, 5, 20), "12.0")):
            checks.register_session(checks.SessionInput(self.ups, day, "OK", results=[
                checks.measure_input(self.b2.label, item=self.b2, values={self.fine.id: Decimal(low)}, fields=fields),
                checks.measure_input(self.b1.label, item=self.b1, values={self.fine.id: Decimal("12.4")}, fields=fields,
                                     replace=day.year == 2026),
            ]))
        stats = periodic_stats.type_stats(self.ups, today=date(2026, 6, 1))
        self.assertEqual([r.label for r in stats.measure_ko], [self.b1.label])
        self.assertEqual([(m["label"], m["count"]) for m in stats.measure_recurring],
                         [(self.b1.label, 2), (self.b2.label, 2)])
        page = self.client.get(reverse("assets:periodic_check_type_detail", args=[self.ups.id]))
        self.assertContains(page, "Da sistemare adesso")
        self.assertContains(page, "Punti ricorrenti")


class CatalogoMisureTests(TestCase):
    def test_seed_completa_ups(self):
        call_command("seed_periodic_checks", "--apply", stdout=io.StringIO())
        ups = PeriodicCheckType.objects.get(name="Verifica pacchi batteria gruppo UPS")
        self.assertEqual((ups.items.count(), ups.measure_fields.count()), (40, 5))
        diff = PeriodicCheckType.objects.get(name="Verifica interruttori differenziali con strumento")
        self.assertEqual(list(diff.measure_fields.values_list("unit", flat=True)), ["mA", "ms"])
        # un tipo gia' presente senza grandezze viene completato, non duplicato
        diff.measure_fields.all().delete()
        call_command("seed_periodic_checks", "--apply", stdout=io.StringIO())
        self.assertEqual(diff.measure_fields.count(), 2)
        self.assertEqual(ups.measure_fields.count(), 5)
