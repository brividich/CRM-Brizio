"""Dispositivi › Software (ricerca e pannello dei PC) e programmi WatchGuard senza versione."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import UserOnboarding
from security.models import SecurityCveImpact, SecurityCveRecord, SoftwareInstallation
from security.services import cve_impact, watchguard_api


def _sw(host, vendor, product, raw, version, fonti=("watchguard",)):
    return SoftwareInstallation.objects.create(dedup_key=f"{host}|{product}|{version}"[:64], source_kind=fonti[0], host=host,
                                               host_display=host.upper(), vendor=vendor, vendor_raw=vendor.title(), product=product,
                                               product_raw=raw, version_raw=version, fonti=list(fonti), still_detected=True)


class SoftwareSocTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(username="sw_soc", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)
        self.zip1 = _sw("pc-sw-01", "igor pavlov", "7-zip", "7-Zip 25.01 (x64)", "25.01")
        _sw("pc-sw-02", "igor pavlov", "7-zip", "7-Zip 26.05 (x64)", "26.05", fonti=("watchguard", "defender"))
        _sw("pc-sw-01", "acme", "viewer", "Acme Viewer", "1.0")
        cve = SecurityCveRecord.objects.create(cve_id="CVE-2099-8801", cvss=9.8, kev=True)
        SecurityCveImpact.objects.create(cve=cve, host="pc-sw-01", installation=self.zip1, outcome=SecurityCveImpact.IMPACTS, explanation="t")

    def test_pagina_ricerca_e_voce_di_menu(self):
        r = self.client.get(reverse("security:software_soc"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn(f'href="{reverse("security:software_soc")}"', html)  # voce «Software» del menu Dispositivi
        self.assertIn("7-Zip", html)
        self.assertIn("Acme Viewer", html)
        self.assertIn("data-cy-sw-search", html)
        r = self.client.get(reverse("security:software_soc") + "?q=7zip")  # come la ricerca del catalogo: senza trattini
        self.assertContains(r, "7-Zip")
        self.assertNotContains(r, "Acme Viewer")
        self.assertContains(self.client.get(reverse("security:software_soc") + "?f=cve"), "1 CVE")

    def test_pannello_pc_del_programma(self):
        from security.services import software_catalog as sc

        key = next(row["key"] for row in sc.catalog() if row["label"].startswith("7-Zip"))
        r = self.client.get(reverse("security:software_soc_pc") + f"?key={key}&nome=7-Zip")
        self.assertEqual(r.status_code, 200)
        for testo in ("PC-SW-01", "PC-SW-02", "25.01", "26.05", "1 · 1 grave", f'{reverse("security:pc_detail")}?nome=PC-SW-01#software'):
            self.assertContains(r, testo)
        self.assertEqual(self.client.get(reverse("security:software_soc_pc")).status_code, 404)


class SenzaVersioneTests(TestCase):
    def test_watchguard_importa_anche_i_programmi_senza_versione(self):
        preview = watchguard_api.anteprima_software([
            {"host_name": "PC-NV-01", "name": "Programma interno", "publisher": "Azienda", "version": ""},
            {"host_name": "PC-NV-01", "name": "KB500", "publisher": "Microsoft", "version": "1", "is_patch": True}])
        self.assertEqual([v["product"] for v in preview.valid], ["Programma interno"])
        self.assertEqual(preview.valid[0]["version"], "")

    def test_senza_versione_resta_fuori_dal_calcolo_cve(self):
        _sw("pc-nv-02", "acme", "viewer", "Acme Viewer", "")
        con_versione = _sw("pc-nv-03", "acme", "viewer", "Acme Viewer", "1.0")
        ctx = cve_impact.Contesto()
        self.assertEqual([i.pk for i in ctx.installs if i.product == "viewer"], [con_versione.pk])
