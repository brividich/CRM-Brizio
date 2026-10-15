"""Rinvio delle manutenzioni e riallineamento dei piani allo scadenziario X-MINE."""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from pathlib import Path

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
from assets.services import maintenance_domain as domain
from assets.services import xmine_alignment as xa

User = get_user_model()


def _assignment(plan, **kwargs):
    defaults = {"frequency": "DAYS", "interval": 60, "warning_days": 15}
    defaults.update(kwargs)
    return MaintenancePlanAssignment.objects.create(plan=plan, **defaults)


class RinvioDominioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.asset = Asset.objects.create(asset_tag="RIN-01", name="Centro di lavoro")
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="rin-p", label="Cambio olio")

    def _occ(self, anchor=MaintenancePlanAssignment.ANCHOR_FROM_COMPLETION, due=None):
        assignment = _assignment(
            self.plan, target_type="ASSET", asset=self.asset, schedule_anchor=anchor
        )
        return MaintenanceOccurrence.objects.create(
            plan=self.plan, assignment=assignment, asset=self.asset,
            due_date=due or self.today, warning_days=15, schedule_anchor=anchor,
        )

    def test_rinvio_conserva_scadenza_originale_e_storico(self):
        occ = self._occ()
        domain.postpone_occurrence(occ, new_date=self.today + timedelta(days=10), reason="macchina in produzione")
        domain.postpone_occurrence(occ, new_date=self.today + timedelta(days=20), reason="ricambio")
        occ.refresh_from_db()
        self.assertEqual(occ.due_date, self.today + timedelta(days=20))
        self.assertEqual(occ.original_due_date, self.today)
        self.assertTrue(occ.is_postponed)
        self.assertEqual(occ.postponements.count(), 2)

    def test_tornare_alla_data_originale_annulla_il_rinvio(self):
        occ = self._occ()
        domain.postpone_occurrence(occ, new_date=self.today + timedelta(days=10))
        domain.postpone_occurrence(occ, new_date=self.today)
        occ.refresh_from_db()
        self.assertIsNone(occ.original_due_date)
        self.assertFalse(occ.is_postponed)

    def test_dopo_piu_rinvii_il_conteggio_riparte_dall_esecuzione(self):
        # Anche con ancoraggio a calendario: la rinviata riparte dall'esecuzione.
        occ = self._occ(anchor=MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR, due=self.today - timedelta(days=30))
        domain.postpone_occurrence(occ, new_date=self.today - timedelta(days=20))
        domain.postpone_occurrence(occ, new_date=self.today - timedelta(days=5))
        eseguita = self.today - timedelta(days=3)
        following = domain.complete_occurrence(occ, completed_on=eseguita)
        self.assertEqual(following.due_date, eseguita + timedelta(days=60))

    def test_senza_rinvio_l_ancoraggio_a_calendario_resta(self):
        due = self.today - timedelta(days=30)
        occ = self._occ(anchor=MaintenancePlanAssignment.ANCHOR_FIXED_CALENDAR, due=due)
        following = domain.complete_occurrence(occ, completed_on=self.today - timedelta(days=3))
        self.assertEqual(following.due_date, due + timedelta(days=60))

    def test_rifiuti(self):
        occ = self._occ()
        MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today + timedelta(days=5),
            status=MaintenanceOccurrence.STATUS_DONE, completed_on=self.today,
        )
        with self.assertRaises(domain.OccurrencePostponeError):
            domain.postpone_occurrence(occ, new_date=self.today + timedelta(days=5))
        occ.status = MaintenanceOccurrence.STATUS_DONE
        occ.save()
        with self.assertRaises(domain.OccurrencePostponeError):
            domain.postpone_occurrence(occ, new_date=self.today + timedelta(days=1))


@override_settings(LEGACY_AUTH_ENABLED=False)
class RinvioPaginaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.admin = User.objects.create_superuser(username="rin-admin", password="x", email="r@y.z")
        cls.asset = Asset.objects.create(asset_tag="RIN-02", name="Tornio")
        cls.plan = MaintenanceInterventionTemplate.objects.create(code="rin-p2", label="Filtri")

    def setUp(self):
        self.client.force_login(self.admin)
        self.occ = MaintenanceOccurrence.objects.create(
            plan=self.plan, asset=self.asset, due_date=self.today, warning_days=10
        )

    def test_pagina_rinvio(self):
        url = reverse("assets:occurrence_postpone", args=[self.occ.id])
        page = self.client.get(url)
        self.assertContains(page, "Rinvia la manutenzione")
        self.assertContains(page, "Storico rinvii")
        nuova = self.today + timedelta(days=7)
        response = self.client.post(url, {"new_date": nuova.isoformat(), "reason": "Fermo produzione"})
        self.assertEqual(response.status_code, 302)
        self.occ.refresh_from_db()
        self.assertEqual(self.occ.due_date, nuova)
        self.assertEqual(self.occ.postponements.get().reason, "Fermo produzione")
        # Il motivo e' obbligatorio nella pagina.
        response = self.client.post(url, {"new_date": nuova.isoformat(), "reason": ""})
        self.assertEqual(response.status_code, 200)

    def test_calendario_mostra_scadenza_originale_e_azione(self):
        domain.postpone_occurrence(self.occ, new_date=self.today + timedelta(days=4))
        response = self.client.get(
            reverse("assets:calendario_asset_json"),
            {"start": self.today.isoformat(), "end": (self.today + timedelta(days=10)).isoformat()},
        )
        event = next(e for e in response.json()["events"] if e["id"] == f"occ-{self.occ.id}")
        self.assertEqual(event["original_start"], self.today.isoformat())
        self.assertEqual(event["postponements"], 1)
        self.assertIn("Rinvia", [a["label"] for a in event["actions"]])

    def test_registra_mostra_rinvio(self):
        domain.postpone_occurrence(self.occ, new_date=self.today + timedelta(days=4))
        page = self.client.get(reverse("assets:occurrence_complete", args=[self.occ.id]))
        self.assertContains(page, "scadenza originale")
        self.assertContains(page, reverse("assets:occurrence_postpone", args=[self.occ.id]))


def _xmine_file(rows: list[tuple]) -> Path:
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.append(list(xa._HEADERS.values()))
    for planned, last, code, label, center, machine, machine_label in rows:
        # Stesso ordine di _HEADERS: data pianif., ult. coll., test, centro, macchina.
        sheet.append([planned, last, code, label, center, center, machine, machine_label])
    path = Path(tempfile.mkdtemp()) / "xmine.xlsx"
    book.save(path)
    return path


class XmineRiallineamentoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.cnc = AssetCategory.objects.create(code="cnc-x", label="Macchine CNC")
        cls.dm1 = Asset.objects.create(asset_tag="CNC-DM1", name="DM1 DMG", internal_number="Int.187", asset_category=cls.cnc)
        cls.dm2 = Asset.objects.create(asset_tag="CNC-DM2", name="DM2 DMG", internal_number="Int.202", asset_category=cls.cnc)
        cls.olio = MaintenanceInterventionTemplate.objects.create(code="caus-09", label="Cambio Olio")
        cls.filtri = MaintenanceInterventionTemplate.objects.create(code="caus-01", label="Filtri Esterni")
        for plan in (cls.olio, cls.filtri):
            _assignment(plan, target_type="CATEGORY", asset_category=cls.cnc, interval=182)

    def setUp(self):
        # Scadenze aperte generate dalla categoria: DM2 non fa il cambio olio in X-MINE.
        self.spuria = MaintenanceOccurrence.objects.create(
            plan=self.olio, asset=self.dm2, due_date=self.today + timedelta(days=5)
        )
        self.aperta = MaintenanceOccurrence.objects.create(
            plan=self.olio, asset=self.dm1, due_date=self.today + timedelta(days=5)
        )

    def _rows(self):
        from dateutil.relativedelta import relativedelta

        last = self.today - timedelta(days=100)
        planned = last + relativedelta(months=6)
        return [
            (planned, last, "09", "Cambio Olio", "TNF", "187", "DM1 - DMG CTX"),
            (planned, last, "01", "Filtri Esterni", "TNF", "187", "DM1 - DMG CTX"),
            (planned, last, "01", "Filtri Esterni", "TNC", "202", "DM2 - Ecoturn"),
            (planned, last, "A10", "Cliente", "900", "13", "Qualifica"),
            (planned, last, "12", "Sostituzione Liquidi", "912", "001", "Lavaggio Condotti"),
        ], planned, last

    def test_dry_run_non_scrive_e_riconosce_le_spurie(self):
        rows, planned, last = self._rows()
        plan = xa.build_plan(xa.read_xmine(_xmine_file(rows)), today=self.today)
        self.assertEqual(len(plan.pairs), 3)
        self.assertEqual(len(plan.rows_out_of_scope), 1)
        self.assertEqual(len(plan.rows_unmatched), 1)  # 912/001: codice locale al centro
        self.assertEqual([c.occurrence.id for c in plan.cancellations], [self.spuria.id])
        self.assertEqual(len(plan.category_assignments_off), 2)
        pair = next(p for p in plan.pairs if p.asset == self.dm1 and p.plan == self.olio)
        self.assertEqual((pair.frequency, pair.interval), ("MONTHS", 6))
        self.assertEqual(pair.due_change, "sposta")
        self.assertTrue(pair.record_done)
        # Nessuna scrittura.
        self.assertFalse(MaintenancePlanAssignment.objects.filter(target_type="ASSET").exists())
        self.assertEqual(MaintenanceOccurrence.objects.filter(status="CANCELED").count(), 0)
        xa.write_report(plan, Path(tempfile.mkdtemp()) / "report.xlsx")

    def test_applica_e_idempotente(self):
        rows, planned, last = self._rows()
        parsed = xa.read_xmine(_xmine_file(rows))
        counts = xa.apply_plan(xa.build_plan(parsed, today=self.today))
        self.assertEqual(counts["applicazioni create"], 3)
        self.assertFalse(MaintenancePlanAssignment.objects.filter(target_type="CATEGORY", is_active=True).exists())
        self.spuria.refresh_from_db()
        self.assertEqual(self.spuria.status, MaintenanceOccurrence.STATUS_CANCELED)
        self.aperta.refresh_from_db()
        self.assertEqual(self.aperta.due_date, planned)
        self.assertTrue(MaintenanceOccurrence.objects.filter(
            plan=self.olio, asset=self.dm1, status="DONE", completed_on=last).exists())
        # DM2 ha solo Filtri Esterni: il cambio olio non gli spetta piu'.
        resolutions = domain.build_plan_resolutions()
        self.assertNotIn((self.olio.id, self.dm2.id), resolutions)
        self.assertIn((self.filtri.id, self.dm2.id), resolutions)

        again = xa.build_plan(parsed, today=self.today)
        self.assertEqual({p.assignment_change for p in again.pairs}, {"invariata"})
        self.assertFalse(any(p.record_done for p in again.pairs))
        self.assertEqual(again.cancellations, [])

    def test_abbinamento(self):
        self.assertEqual(xa.normalize_internal("Int.056"), "56")
        self.assertEqual(xa.normalize_internal("Int. C3"), "C3")
        self.assertEqual(xa._machine_lookup_key("921", "C3", "Chiller")[0], "C3")
        self.assertIsNone(xa._machine_lookup_key("913", "001", "Forno")[0])
        self.assertEqual(xa._machine_lookup_key("904", "010", "Marcatrice (n°int. 198)")[0], "198")
        self.assertEqual(xa.infer_recurrence(date(2025, 1, 10), date(2026, 1, 10)), ("YEARS", 1))
        self.assertEqual(xa.infer_recurrence(date(2025, 1, 10), date(2025, 3, 1)), ("DAYS", 50))
