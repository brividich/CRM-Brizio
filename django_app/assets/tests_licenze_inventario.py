"""Licenze e inventario: conteggio per programma, collegamento in blocco, report PC/posti. Dati sintetici."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import SoftwareCatalogEntry, SoftwareLicense
from assets.services.report_catalog import _licenze
from assets.services.software_licenze import collega_proposte, coverage_report
from security.models import SoftwareInstallation


def _sw(host, vendor, product, version="1.0"):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{vendor}|{product}|{version}", source_kind="watchguard", host=host, host_display=host,
        vendor=vendor, vendor_raw=vendor, product=product, product_raw=product, version_raw=version,
        still_detected=True, seen_at=now, last_seen_at=now,
    )


class CoperturaPerProgrammaTests(TestCase):
    def test_licenza_su_altro_nome_copre_il_programma(self):
        _sw("pc1", "demo", "demo cad 2024", "24")
        _sw("pc2", "demo", "demo cad 2025", "25")
        SoftwareCatalogEntry.objects.create(inventory_key="demo|demo cad 2024", licensing="a_pagamento")
        SoftwareLicense.objects.create(product_name="Demo CAD", inventory_key="demo|demo cad 2025", seats_total=1)
        report = coverage_report()
        self.assertEqual(report["unlicensed"], [])
        self.assertEqual([(r["hosts"], r["seats"]) for r in report["over_seats"]], [(2, 1)])

    def test_senza_licenza_resta_segnalato(self):
        _sw("pc1", "demo", "demo cad 2024")
        SoftwareCatalogEntry.objects.create(inventory_key="demo|demo cad 2024", licensing="a_pagamento", display_name="Demo CAD")
        self.assertEqual([r["hosts"] for r in coverage_report()["unlicensed"]], [1])


class CollegaProposteTests(TestCase):
    def setUp(self):
        _sw("pc1", "demo", "demo cad")
        _sw("pc1", "acme", "acme tool")
        self.a = SoftwareLicense.objects.create(product_name="Demo CAD")
        self.b = SoftwareLicense.objects.create(product_name="Acme Tool")
        self.c = SoftwareLicense.objects.create(product_name="Prodotto sconosciuto")

    def test_collega_solo_le_univoche(self):
        self.assertEqual(sorted(collega_proposte()), sorted([self.a.pk, self.b.pk]))
        self.a.refresh_from_db()
        self.c.refresh_from_db()
        self.assertEqual(self.a.inventory_key, "demo|demo cad")
        self.assertEqual(self.c.inventory_key, "")

    def test_la_somiglianza_non_si_collega_in_blocco(self):
        _sw("pc1", "microsoft", "microsoft 365")
        lic = SoftwareLicense.objects.create(product_name="Microsoft 365 Business Premium", seats_total=65)
        self.assertEqual(next(r for r in coverage_report()["unlinked"] if r["license"].pk == lic.pk)["suggestion"]["key"], "microsoft|microsoft 365")
        collega_proposte()
        lic.refresh_from_db()
        self.assertEqual(lic.inventory_key, "")

    def test_dalla_pagina(self):
        from core.models import UserOnboarding

        user = get_user_model().objects.create_superuser("lic-demo", "lic@example.test", "x")
        self.client.force_login(user)
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True})
        url = reverse("assets:software_license_list")
        self.assertContains(self.client.get(url), "Collega le 2 con il nome uguale")
        self.client.post(url, {"action": "link_software_inventory_proposte"})
        self.assertEqual(SoftwareLicense.objects.exclude(inventory_key="").count(), 2)


class ReportTests(TestCase):
    def test_colonne_pc_e_posti(self):
        _sw("pc1", "demo", "demo cad")
        _sw("pc2", "demo", "demo cad")
        SoftwareLicense.objects.create(product_name="Oltre", inventory_key="demo|demo cad", seats_total=1)
        SoftwareLicense.objects.create(product_name="Scollegata", seats_total=3)
        risultato = _licenze({})
        righe = {r[1]: r for r in risultato.righe}
        self.assertEqual(righe["Oltre"][12:], [2, -1])
        self.assertEqual(righe["Scollegata"][12:], ["non collegata", ""])
        self.assertEqual(risultato.totali[13], "Oltre i posti 1")
