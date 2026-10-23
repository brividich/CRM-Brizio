"""Scadenze amministrative: periodicita', serie e comando ``riordina_scadenze_amministrative``."""

from __future__ import annotations

import io
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetAdministrativeDeadline,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenancePlanAssignment,
)

User = get_user_model()
AD = AssetAdministrativeDeadline


@override_settings(LEGACY_AUTH_ENABLED=False)
class RegistraScadenzaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(username="riord-admin", password="x", email="r@b.c")
        cls.asset = Asset.objects.create(asset_tag="CRP-R1", name="Carroponte riordino")

    def setUp(self):
        self.client.force_login(self.admin)

    def _registra(self, deadline, **extra):
        data = {
            "action": "complete_administrative_deadline",
            "deadline_id": str(deadline.id),
            "execution_date": "2026-04-28",
            **extra,
        }
        return self.client.post(reverse("assets:asset_administrative_deadline_list"), data)

    def test_periodica_si_rinnova_da_sola(self):
        d = AD.objects.create(asset=self.asset, title="Verifica periodica", due_date=date(2026, 4, 30), recurrence_months=12)
        response = self._registra(d)
        self.assertEqual(response.status_code, 302)
        d.refresh_from_db()
        self.assertTrue(d.is_active)
        self.assertEqual(d.due_date, date(2027, 4, 28))
        self.assertEqual(d.completions.get().next_due_date, date(2027, 4, 28))

    def test_data_indicata_vince_sulla_periodicita(self):
        d = AD.objects.create(asset=self.asset, title="Verifica periodica", due_date=date(2026, 4, 30), recurrence_months=12)
        self._registra(d, execution_next_due="2028-01-15")
        d.refresh_from_db()
        self.assertEqual(d.due_date, date(2028, 1, 15))

    def test_serie_chiude_la_riga_e_non_crea_doppioni(self):
        prima = AD.objects.create(asset=self.asset, title="Controllo batterie", due_date=date(2026, 4, 22))
        seconda = AD.objects.create(asset=self.asset, title="Controllo batterie", due_date=date(2026, 7, 22))
        self._registra(prima, execution_next_due="2026-07-22")
        prima.refresh_from_db()
        seconda.refresh_from_db()
        self.assertFalse(prima.is_active)
        self.assertEqual(prima.due_date, date(2026, 4, 22))
        self.assertTrue(seconda.is_active)
        self.assertEqual(AD.objects.filter(asset=self.asset, is_active=True).count(), 1)

    def test_form_mostra_periodicita(self):
        response = self.client.get(reverse("assets:asset_administrative_deadline_create"))
        self.assertContains(response, "Si ripete ogni (mesi)")


class RiordinoComandoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.carrello = Asset.objects.create(asset_tag="MOV-R1", name="Carrello riordino")
        cls.forno = Asset.objects.create(asset_tag="IMT-R1", name="Forno riordino")
        cls.gru = Asset.objects.create(asset_tag="GRU-R1", name="Gru riordino")
        start = cls.today - timedelta(days=1)
        cls.serie = [
            AD.objects.create(
                asset=cls.carrello, deadline_type=AD.TYPE_TECHNICAL, title="Controllo Batterie",
                due_date=d, warning_days=30,
            )
            for d in (start, start + timedelta(days=92), start + timedelta(days=184))
        ]
        cls.senza_serie = AD.objects.create(
            asset=cls.gru, deadline_type=AD.TYPE_TECHNICAL, title="Verifica VFC_MOP", due_date=cls.today + timedelta(days=200)
        )
        cls.legge = AD.objects.create(
            asset=cls.gru, deadline_type=AD.TYPE_ADMINISTRATIVE, title="Verifica Periodica", due_date=cls.today + timedelta(days=90)
        )
        piano_vts = MaintenanceInterventionTemplate.objects.create(code="r-vts", label="Verifica Termocoppia Sicurezza - VTS")
        MaintenancePlanAssignment.objects.create(
            plan=piano_vts, target_type=MaintenancePlanAssignment.TARGET_ASSET, asset=cls.forno,
            frequency=MaintenancePlanAssignment.FREQ_MONTHS, interval=1,
        )
        cls.doppione = AD.objects.create(
            asset=cls.forno, deadline_type=AD.TYPE_ADMINISTRATIVE, title="Verifica VTS", due_date=cls.today + timedelta(days=10)
        )
        # Vecchio piano «copia» con la stessa etichetta: non va riusato.
        cls.vecchio = MaintenanceInterventionTemplate.objects.create(
            code="controllo-batterie", label="Controllo Batterie",
            maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE, is_active=False,
        )
        MaintenanceOccurrence.objects.create(
            plan=cls.vecchio, asset=cls.carrello, due_date=start, status=MaintenanceOccurrence.STATUS_CANCELED
        )

    def test_prova_a_vuoto_non_scrive(self):
        out = io.StringIO()
        call_command("riordina_scadenze_amministrative", stdout=out)
        self.assertIn("PROVA A VUOTO", out.getvalue())
        self.assertIn("ogni 3 mesi", out.getvalue())
        self.assertIn("Verifica VFC_MOP", out.getvalue())
        self.assertEqual(AD.objects.filter(is_active=True).count(), 6)
        self.assertFalse(MaintenancePlanAssignment.objects.filter(asset=self.carrello).exists())

    def test_applica(self):
        call_command("riordina_scadenze_amministrative", apply=True, stdout=io.StringIO())
        for d in self.serie:
            d.refresh_from_db()
            self.assertFalse(d.is_active)
            self.assertIn("Spostata nel piano", d.notes)
        assignment = MaintenancePlanAssignment.objects.get(asset=self.carrello)
        self.assertEqual(assignment.plan.maintenance_type, MaintenanceInterventionTemplate.TYPE_ROUTINE)
        self.assertNotEqual(assignment.plan_id, self.vecchio.id)
        self.assertEqual((assignment.frequency, assignment.interval), (MaintenancePlanAssignment.FREQ_MONTHS, 3))
        self.assertEqual(assignment.first_due_date, self.serie[0].due_date)
        occ = MaintenanceOccurrence.objects.get(plan=assignment.plan, asset=self.carrello, status=MaintenanceOccurrence.STATUS_OPEN)
        self.assertEqual(occ.due_date, self.serie[0].due_date)
        self.doppione.refresh_from_db()
        self.assertFalse(self.doppione.is_active)
        for d in (self.senza_serie, self.legge):
            d.refresh_from_db()
            self.assertTrue(d.is_active)

    def test_mesi_per_titoli_senza_serie_e_ripetibile(self):
        call_command("riordina_scadenze_amministrative", apply=True, mesi=["Verifica VFC_MOP=12"], stdout=io.StringIO())
        self.senza_serie.refresh_from_db()
        self.assertFalse(self.senza_serie.is_active)
        a = MaintenancePlanAssignment.objects.get(asset=self.gru)
        self.assertEqual(a.interval, 12)
        out = io.StringIO()
        call_command("riordina_scadenze_amministrative", apply=True, stdout=out)
        self.assertIn("Fatto: 0 applicazioni", out.getvalue())
