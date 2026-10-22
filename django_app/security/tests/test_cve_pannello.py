"""Pannello laterale delle CVE: per programma, per PC (asset) e scheda breve. Dati sintetici."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from security.models import SecurityCveImpact, SecurityCveRecord, SoftwareInstallation
from security.services import cve_pannello, software_catalog


class CvePannelloTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create(username="cvp_admin", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)
        self.pc1 = Asset.objects.create(asset_tag="CVP-1", name="PC-CVP-01")
        now = timezone.now()

        def inst(host, product, raw, version, hub=None, vendor="acme"):
            return SoftwareInstallation.objects.create(
                dedup_key=f"{host}|{product}|{version}", source_kind="watchguard", host=host, host_display=host.upper(),
                hub_asset=hub, vendor=vendor, vendor_raw=vendor, product=product, product_raw=raw, version_raw=version,
                fonti=["watchguard"], still_detected=True, seen_at=now, last_seen_at=now,
            )

        # due nomi dello stesso programma (raggruppati), versioni diverse
        self.v1 = inst("pc-cvp-01", "acme viewer", "Acme Viewer", "1.0", hub=self.pc1)
        self.v2 = inst("pc-cvp-02", "acme viewer", "Acme Viewer", "2.0")
        self.v3 = inst("pc-cvp-03", "viewer", "viewer", "1.0")
        self.altro = inst("pc-cvp-01", "acme editor", "Acme Editor", "5.0", hub=self.pc1)
        self.kev = SecurityCveRecord.objects.create(
            cve_id="CVE-2099-0001", description="Esecuzione di codice remoto sintetica.", cvss=7.5, kev=True,
            configurations=[{"vendor": "acme", "product": "viewer", "end_excluding": "2.0"}],
        )
        self.media = SecurityCveRecord.objects.create(cve_id="CVE-2099-0002", description="Lettura sintetica.", cvss=5.0)
        self.dubbia = SecurityCveRecord.objects.create(cve_id="CVE-2099-0003", description="Senza range.", cvss=9.8)
        self.editor = SecurityCveRecord.objects.create(cve_id="CVE-2099-0004", description="Editor.", cvss=9.1)

        def imp(record, install, outcome=SecurityCveImpact.IMPACTS):
            SecurityCveImpact.objects.create(cve=record, host=install.host, installation=install, hub_asset=install.hub_asset,
                                             outcome=outcome, explanation="Versione nel range (sintetico).")

        imp(self.kev, self.v1)
        imp(self.kev, self.v3)
        imp(self.kev, self.v2, SecurityCveImpact.NOT_IMPACTED)
        imp(self.media, self.v1)
        imp(self.dubbia, self.v2, SecurityCveImpact.TO_VERIFY)
        imp(self.editor, self.altro)
        self.key = next(c["key"] for c in software_catalog.catalog() if "viewer" in c["key"])

    def test_programma_ordina_per_pericolo_e_separa_da_verificare(self):
        dati = cve_pannello.per_programma(self.key)
        self.assertEqual([r["record"].cve_id for r in dati["colpiscono"]], ["CVE-2099-0001", "CVE-2099-0002"])
        self.assertEqual([r["record"].cve_id for r in dati["da_verificare"]], ["CVE-2099-0003"])
        kev = dati["colpiscono"][0]
        self.assertEqual(kev["pc"], 2)  # pc-cvp-01 e pc-cvp-03 (nomi diversi, stesso programma); pc-cvp-02 non impatta
        self.assertEqual(kev["tono"], "critical")
        self.assertEqual(kev["correzione"], "corretta dalla versione 2.0")
        self.assertEqual(dati["gravi"], 1)

    def test_numero_del_catalogo_uguale_al_pannello(self):
        self.assertEqual(software_catalog.cve_by_key()[self.key], len(cve_pannello.per_programma(self.key)["colpiscono"]))

    def test_cve_per_versione(self):
        self.assertEqual(cve_pannello.cve_per_versione(self.key), {"1.0": 2})

    def test_pc_raggruppa_per_software(self):
        dati = cve_pannello.per_asset(self.pc1)
        self.assertEqual(dati["colpiscono"], 3)
        self.assertEqual(dati["gravi"], 2)  # KEV + CVSS 9.1
        self.assertEqual(len(dati["software"]), 2)
        self.assertEqual(dati["software"][0]["gravi"], 1)

    def test_installazione_rimossa_esce_dal_pannello(self):
        SoftwareInstallation.objects.filter(pk=self.altro.pk).update(still_detected=False)
        self.assertEqual(cve_pannello.per_asset(self.pc1)["colpiscono"], 2)

    def test_pagine_del_pannello(self):
        url = reverse("security:cve_pannello_programma")
        page = self.client.get(url, {"k": self.key})
        self.assertContains(page, "CVE-2099-0001")
        self.assertContains(page, "Sfruttata")
        self.assertContains(page, "Da verificare (1)")
        page = self.client.get(reverse("security:cve_pannello_asset", args=[self.pc1.pk]), {"sw": self.key})
        self.assertContains(page, "Acme Viewer")
        self.assertContains(page, "is-focus")
        page = self.client.get(reverse("security:cve_pannello_cve", args=["cve-2099-0001"]), {"asset": self.pc1.pk, "da": url + "?k=x"})
        self.assertContains(page, "Torna all'elenco")
        self.assertContains(page, "questo PC")
        self.assertContains(page, "corretta dalla versione 2.0")
        self.assertContains(page, "https://nvd.nist.gov/vuln/detail/CVE-2099-0001")

    def test_ritorno_solo_verso_il_pannello(self):
        page = self.client.get(reverse("security:cve_pannello_cve", args=["CVE-2099-0001"]), {"da": "https://esempio.invalid/x"})
        self.assertNotContains(page, "esempio.invalid")
        self.assertNotContains(page, "Torna all")

    def test_cve_sconosciuta_e_chiave_non_valida(self):
        self.assertEqual(self.client.get(reverse("security:cve_pannello_cve", args=["CVE-2099-9999"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("security:cve_pannello_programma"), {"k": "senza-barra"}).status_code, 404)

    def test_senza_accesso_al_soc_niente_cve(self):
        user = get_user_model().objects.create(username="cvp_base")
        self.client.force_login(user)
        resp = self.client.get(reverse("security:cve_pannello_programma"), {"k": self.key}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertIn(resp.status_code, (302, 403))
        self.assertNotIn(b"CVE-2099-0001", resp.content)

    def test_bottoni_nelle_pagine_asset(self):
        page = self.client.get(reverse("assets:software_catalog"))
        self.assertContains(page, 'class="cvp-open"')
        self.assertContains(page, "soc-ui.js")
        page = self.client.get(reverse("assets:software_catalog_detail"), {"k": self.key})
        self.assertContains(page, "2 CVE colpiscono questo programma")
        self.assertContains(page, reverse("security:cve_pannello_programma"))
