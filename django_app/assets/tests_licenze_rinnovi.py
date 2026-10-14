from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from anagrafica.models import Fornitore

from .models import SoftwareLicense, SoftwareLicenseRenewal

User = get_user_model()


class SoftwareLicenseRenewalTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="lic-rinnovi-admin",
            email="lic-rinnovi-admin@test.local",
            password="pass12345",
        )
        self.license = SoftwareLicense.objects.create(
            category=SoftwareLicense.CATEGORY_SOFTWARE,
            vendor="Fornitore Demo",
            product_name="Suite Demo",
            license_reference="DEMO-001",
            seats_total=5,
            seats_used=3,
            expiry_date=date(2026, 12, 31),
            is_active=False,
        )
        self.supplier = Fornitore.objects.create(ragione_sociale="Rivenditore Sintetico Srl")
        self.url = reverse("assets:software_license_list")

    def _renew_payload(self, **overrides):
        prefix = f"renew-{self.license.id}"
        payload = {
            "action": "renew_software_license",
            "license_id": str(self.license.id),
            f"{prefix}-period_end": "2027-12-31",
            f"{prefix}-renewed_on": "2026-12-15",
            f"{prefix}-period_start": "2027-01-01",
            f"{prefix}-seats_total": "8",
            f"{prefix}-cost_eur": "1200.50",
            f"{prefix}-supplier": str(self.supplier.id),
            f"{prefix}-reference": "ORD-2026-77",
            f"{prefix}-notes": "Rinnovo annuale",
        }
        for key, value in overrides.items():
            payload[f"{prefix}-{key}"] = value
        return payload

    def test_rinnovo_crea_storico_e_aggiorna_licenza(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, self._renew_payload())
        self.assertEqual(response.status_code, 302)

        renewal = SoftwareLicenseRenewal.objects.get(license=self.license)
        self.assertEqual(renewal.previous_expiry, date(2026, 12, 31))
        self.assertEqual(renewal.period_end, date(2027, 12, 31))
        self.assertEqual(renewal.period_start, date(2027, 1, 1))
        self.assertEqual(renewal.renewed_on, date(2026, 12, 15))
        self.assertEqual(renewal.seats_total, 8)
        self.assertEqual(renewal.cost_eur, Decimal("1200.50"))
        self.assertEqual(renewal.supplier, self.supplier)
        self.assertEqual(renewal.reference, "ORD-2026-77")
        self.assertEqual(renewal.created_by, self.admin)

        self.license.refresh_from_db()
        self.assertEqual(self.license.expiry_date, date(2027, 12, 31))
        self.assertEqual(self.license.renewal_date, date(2026, 12, 15))
        self.assertEqual(self.license.seats_total, 8)
        self.assertTrue(self.license.is_active)

    def test_rinnovo_senza_posti_non_cambia_i_posti(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, self._renew_payload(seats_total="", cost_eur="", supplier=""))
        self.license.refresh_from_db()
        self.assertEqual(self.license.seats_total, 5)
        renewal = SoftwareLicenseRenewal.objects.get(license=self.license)
        self.assertIsNone(renewal.cost_eur)
        self.assertIsNone(renewal.supplier)

    def test_validazione_scadenza_prima_di_inizio_periodo(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self.url,
            self._renew_payload(period_start="2027-06-01", period_end="2027-01-31"),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rinnovo non salvato")
        self.assertFalse(SoftwareLicenseRenewal.objects.exists())
        self.license.refresh_from_db()
        self.assertEqual(self.license.expiry_date, date(2026, 12, 31))
        self.assertFalse(self.license.is_active)

    def test_nuova_scadenza_obbligatoria(self):
        self.client.force_login(self.admin)
        self.client.post(self.url, self._renew_payload(period_end=""))
        self.assertFalse(SoftwareLicenseRenewal.objects.exists())

    def test_utente_senza_permesso_non_puo_rinnovare(self):
        user = User.objects.create_user(username="lic-rinnovi-base", password="pass12345")
        self.client.force_login(user)
        self.client.post(self.url, self._renew_payload())
        self.assertFalse(SoftwareLicenseRenewal.objects.exists())
        self.license.refresh_from_db()
        self.assertEqual(self.license.expiry_date, date(2026, 12, 31))

    def test_modifica_scadenza_dal_form_registra_storico(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self.url,
            {
                "action": "update_software_license",
                "edit_id": str(self.license.id),
                "category": SoftwareLicense.CATEGORY_SOFTWARE,
                "vendor": "Fornitore Demo",
                "product_name": "Suite Demo",
                "license_reference": "DEMO-001",
                "seats_total": "5",
                "seats_used": "3",
                "expiry_date": "2027-06-30",
                "is_active": "on",
                "assigned_employee_id": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        renewal = SoftwareLicenseRenewal.objects.get(license=self.license)
        self.assertEqual(renewal.previous_expiry, date(2026, 12, 31))
        self.assertEqual(renewal.period_end, date(2027, 6, 30))
        self.assertEqual(renewal.notes, "Scadenza modificata dalla scheda licenza")

    def test_modifica_senza_cambio_scadenza_non_registra_storico(self):
        self.client.force_login(self.admin)
        self.client.post(
            self.url,
            {
                "action": "update_software_license",
                "edit_id": str(self.license.id),
                "category": SoftwareLicense.CATEGORY_SOFTWARE,
                "vendor": "Fornitore Demo",
                "product_name": "Suite Demo modificata",
                "license_reference": "DEMO-001",
                "seats_total": "5",
                "seats_used": "3",
                "expiry_date": "2026-12-31",
                "assigned_employee_id": "",
            },
        )
        self.license.refresh_from_db()
        self.assertEqual(self.license.product_name, "Suite Demo modificata")
        self.assertFalse(SoftwareLicenseRenewal.objects.exists())

    def test_storico_visibile_nella_pagina(self):
        SoftwareLicenseRenewal.objects.create(
            license=self.license,
            renewed_on=date(2025, 12, 20),
            period_end=date(2026, 12, 31),
            previous_expiry=date(2025, 12, 31),
            cost_eur=Decimal("100.00"),
            supplier=self.supplier,
            reference="FATT-0042",
            created_by=self.admin,
        )
        SoftwareLicenseRenewal.objects.create(
            license=self.license,
            renewed_on=date(2024, 12, 20),
            period_end=date(2025, 12, 31),
            cost_eur=Decimal("90.00"),
        )
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2 rinnovi")
        self.assertContains(response, "speso € 190,00")
        self.assertContains(response, "FATT-0042")
        self.assertContains(response, "Rivenditore Sintetico Srl")
        self.assertContains(response, "Salva rinnovo")


class CoperturaLicenzeSoftwareTests(TestCase):
    def test_licenza_senza_chiave_e_stati(self):
        from datetime import timedelta

        from assets.models import SoftwareLicense
        from assets.services.software_licenze import coverage_report, license_status

        oggi = timezone.localdate()
        scaduta = SoftwareLicense.objects.create(product_name="Tool Demo", expiry_date=oggi - timedelta(days=1))
        valida = SoftwareLicense.objects.create(product_name="Altro Demo", expiry_date=oggi + timedelta(days=90))
        self.assertEqual(license_status(scaduta, oggi), "expired")
        self.assertEqual(license_status(valida, oggi), "active")
        report = coverage_report(oggi)
        self.assertEqual(len(report["unlinked"]), 2)
        self.assertEqual(report["unlicensed"], [])

    def test_pagina_mostra_da_sistemare_e_collega_proposto(self):
        from unittest import mock

        admin = User.objects.create_superuser(username="lic-cov-admin", email="c@test.local", password="pass12345")
        lic = SoftwareLicense.objects.create(product_name="Editor Demo", vendor="Demo Soft")
        voce = {"key": "demosoft|editordemo", "label": "Editor Demo", "vendor_label": "Demo Soft", "hosts": 3}
        self.client.force_login(admin)
        with mock.patch("security.services.software_catalog.catalog", return_value=[voce]):
            response = self.client.get(reverse("assets:software_license_list"))
            self.assertContains(response, "Da sistemare: licenze e software installato")
            self.assertContains(response, "Collega a «Editor Demo» (3 PC)")
            response = self.client.post(reverse("assets:software_license_list"), {
                "action": "link_software_inventory", "license_id": lic.id, "inventory_key": voce["key"],
            })
        self.assertEqual(response.status_code, 302)
        lic.refresh_from_db()
        self.assertEqual(lic.inventory_key, voce["key"])
