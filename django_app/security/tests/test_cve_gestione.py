"""Gestione delle CVE: elenco arricchito e registro delle correzioni. Dati sintetici."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import SecurityCveImpact, SecurityCveRecord, SecurityCveRisoluzione, SoftwareCpeMapping, SoftwareInstallation
from security.services import cve_gestione, cve_impact


class CveGestioneTests(TestCase):
    def setUp(self):
        SoftwareCpeMapping.objects.create(vendor="acme", product="viewer", cpe_vendor="acme", cpe_product="viewer", confirmed=True)
        self.record = SecurityCveRecord.objects.create(
            cve_id="CVE-2099-0201", description="Sintetica per la gestione.", cvss=9.1,
            configurations=[{"vendor": "acme", "product": "viewer", "end_excluding": "2.0"}],
        )
        self.vecchia = self._inst("pc-ges-01", "1.0")
        self._inst("pc-ges-02", "1.5")
        cve_impact.recompute(self.record)
        self.admin = get_user_model().objects.create(username="ges_admin", is_staff=True, is_superuser=True)

    def _inst(self, host, version):
        now = timezone.now()
        return SoftwareInstallation.objects.create(
            dedup_key=f"{host}|viewer|{version}", source_kind="watchguard", host=host, host_display=host.upper(),
            vendor="acme", vendor_raw="Acme", product="viewer", product_raw="Acme Viewer", version_raw=version,
            fonti=["watchguard"], still_detected=True, seen_at=now, last_seen_at=now, last_inventory_date=timezone.localdate(),
        )

    def _aggiorna_pc1(self):
        SoftwareInstallation.objects.filter(pk=self.vecchia.pk).update(still_detected=False)
        self._inst("pc-ges-01", "2.1")
        cve_impact.recompute(self.record)

    def test_elenco_con_programmi_classe_e_termine(self):
        riga = cve_gestione.elenco_cve()["righe"][0]
        self.assertEqual(riga["cve_id"], "CVE-2099-0201")
        self.assertEqual(riga["classe"], "critica")
        self.assertEqual(riga["impatta"], 2)
        self.assertIn("Acme Viewer 1.0", riga["programmi"])
        self.assertIsNotNone(riga["termine"])

    def test_filtri_dell_elenco(self):
        self.assertEqual(len(cve_gestione.elenco_cve(q="viewer")["righe"]), 1)
        self.assertEqual(len(cve_gestione.elenco_cve(q="pc-ges-02")["righe"]), 1)
        self.assertEqual(cve_gestione.elenco_cve(q="niente-del-genere")["righe"], [])
        self.assertEqual(cve_gestione.elenco_cve(classe="bassa")["righe"], [])
        self.assertEqual(cve_gestione.elenco_cve(solo_kev=True)["righe"], [])
        self.assertEqual(cve_gestione.elenco_cve(termine="scaduta")["righe"], [])

    def test_correzione_da_aggiornamento_e_cve_ancora_aperta(self):
        self._aggiorna_pc1()
        d = cve_gestione.correzioni()
        self.assertEqual(d["kpi"]["corretti"], 1)
        self.assertEqual(d["kpi"]["aggiornati"], 1)
        x = d["righe"][0]
        self.assertEqual((x["r"].versione_prima, x["r"].versione_dopo), ("1.0", "2.1"))
        self.assertTrue(x["nel_termine"])
        g = d["gruppi"][0]
        self.assertFalse(g["chiusa"])
        self.assertEqual(g["ancora"], 1)
        self.assertEqual(cve_gestione.elenco_cve()["righe"][0]["corretti_90"], 1)

    def test_cve_chiusa_su_tutti_i_pc(self):
        self._aggiorna_pc1()
        SoftwareInstallation.objects.filter(host="pc-ges-02").update(still_detected=False)
        self._inst("pc-ges-02", "3.0")
        cve_impact.recompute(self.record)
        self.assertFalse(SecurityCveImpact.objects.filter(cve=self.record, outcome=SecurityCveImpact.IMPACTS).exists())
        d = cve_gestione.correzioni()
        self.assertTrue(d["gruppi"][0]["chiusa"])
        self.assertEqual(d["kpi"]["cve_chiuse"], 1)

    def test_uscite_non_correttive_escluse_di_default(self):
        SecurityCveRisoluzione.objects.create(cve=self.record, host="pc-ges-09", come=SecurityCveRisoluzione.PC_ASSENTE)
        self.assertEqual(cve_gestione.correzioni()["righe"], [])
        self.assertEqual(len(cve_gestione.correzioni(come="altro")["righe"]), 1)

    def test_pagine_e_csv(self):
        self._aggiorna_pc1()
        self.client.force_login(self.admin)
        page = self.client.get(reverse("security:vulnerabilities"), {"q": "viewer"})
        self.assertContains(page, "CVE-2099-0201")
        self.assertContains(page, "Acme Viewer 1.5")
        for vista in ("cve", "pc"):
            page = self.client.get(reverse("security:cve_correzioni"), {"vista": vista})
            self.assertContains(page, "CVE-2099-0201")
        page = self.client.get(reverse("security:cve_correzioni"), {"vista": "pc"})
        self.assertContains(page, "2.1")
        csv = self.client.get(reverse("security:cve_correzioni"), {"formato": "csv"})
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("PC-GES-01", csv.content.decode("utf-8"))

    def test_correzioni_negata_senza_permesso(self):
        utente = get_user_model().objects.create(username="ges_nessuno")
        self.client.force_login(utente)
        page = self.client.get(reverse("security:cve_correzioni"))
        self.assertNotEqual(page.status_code, 200)
