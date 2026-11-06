"""Calcolo CVE ibrido: le CVE di Defender nel calcolo del SOC. Dati sintetici; Graph e NVD simulati."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from security.models import DefenderVulnerabilita as D, SecurityCveImpact as Imp, SecurityCveRecord as R, SecurityCveRisoluzione, SoftwareCpeMapping, SoftwareInstallation
from security.services import cve_feeds, cve_impact, defender_vuln, soc_settings, software_catalog as sc


def _sw(host, vendor, product, version="1.0", fonti=("watchguard",)):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{vendor}|{product}|{version}", source_kind=fonti[0], fonti=list(fonti), host=host, host_display=host.upper(),
        vendor=vendor, vendor_raw=vendor, product=product, product_raw=product, version_raw=version, still_detected=True, seen_at=now,
        last_seen_at=now, last_inventory_date=timezone.localdate(),
    )


def _def(host, cve, prodotto, produttore="demo", versione="1.0", severita="Critical", kb=""):
    return D.objects.create(host=host, cve_id=cve, prodotto=prodotto, produttore=produttore, versione=versione, severita=severita, kb=kb)


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        soc_settings.save({"defender.vulnerabilita.attivo": True, "defender.vulnerabilita.ibrido": True}, None)

    def esito(self, cve, host):
        return Imp.objects.filter(cve__cve_id=cve, host=host).values_list("outcome", flat=True).first()


class CalcoloTests(_Base):
    def test_defender_vale_impatta_senza_cpe(self):
        _sw("pc1", "demo", "demo tool")
        _def("pc1", "CVE-2099-0001", "demo_tool", kb="KB1")
        record = R.objects.create(cve_id="CVE-2099-0001", severity="high")
        cve_impact.recompute(record)
        self.assertEqual(self.esito("CVE-2099-0001", "pc1"), Imp.IMPACTS)
        self.assertIn("Defender la segnala", Imp.objects.get(host="pc1").explanation)
        self.assertIn("KB1", Imp.objects.get(host="pc1").explanation)

    def test_spento_non_conta(self):
        soc_settings.save({"defender.vulnerabilita.ibrido": False}, None)
        _sw("pc1", "demo", "demo tool")
        _def("pc1", "CVE-2099-0001", "demo_tool")
        record = R.objects.create(cve_id="CVE-2099-0001", severity="high")
        cve_impact.recompute(record)
        self.assertIsNone(self.esito("CVE-2099-0001", "pc1"))

    def test_senza_programma_corrispondente_niente_impatto(self):
        _sw("pc1", "demo", "altro tool xyz")
        _def("pc1", "CVE-2099-0001", "prodotto_ignoto", produttore="ignoto")
        record = R.objects.create(cve_id="CVE-2099-0001", severity="high")
        cve_impact.recompute(record)
        self.assertIsNone(self.esito("CVE-2099-0001", "pc1"))

    def test_non_applicabile_rispettato(self):
        _sw("pc1", "demo", "demo tool")
        SoftwareCpeMapping.objects.create(vendor="demo", product="demo tool", not_applicable=True)
        _def("pc1", "CVE-2099-0001", "demo_tool")
        record = R.objects.create(cve_id="CVE-2099-0001", severity="high")
        cve_impact.recompute(record)
        self.assertIsNone(self.esito("CVE-2099-0001", "pc1"))

    def test_versione_a_posto_diventa_da_verificare(self):
        _sw("pc1", "demo", "demo tool", "3.0")
        SoftwareCpeMapping.objects.create(vendor="demo", product="demo tool", cpe_vendor="demo", cpe_product="tool", confirmed=True)
        _def("pc1", "CVE-2099-0001", "demo_tool", versione="3.0")
        record = R.objects.create(cve_id="CVE-2099-0001", severity="high", nvd_fetched_at=timezone.now(), configurations=[
            {"part": "a", "vendor": "demo", "product": "tool", "version": "*", "start_including": "", "start_excluding": "",
             "end_including": "", "end_excluding": "2.0", "requires_platform": False}])
        cve_impact.recompute(record)
        self.assertEqual(self.esito("CVE-2099-0001", "pc1"), Imp.TO_VERIFY)

    def test_stessa_cve_anche_sul_pc_che_defender_non_vede(self):
        _sw("pc1", "demo", "demo tool")
        _sw("pc2", "demo", "demo tool")
        SoftwareCpeMapping.objects.create(vendor="demo", product="demo tool", cpe_vendor="demo", cpe_product="tool", confirmed=True)
        _def("pc1", "CVE-2099-0001", "demo_tool")
        record = R.objects.create(cve_id="CVE-2099-0001", severity="high", nvd_fetched_at=timezone.now(), configurations=[
            {"part": "a", "vendor": "demo", "product": "tool", "version": "*", "start_including": "", "start_excluding": "",
             "end_including": "", "end_excluding": "2.0", "requires_platform": False}])
        cve_impact.recompute(record)
        self.assertEqual({self.esito("CVE-2099-0001", "pc1"), self.esito("CVE-2099-0001", "pc2")}, {Imp.IMPACTS})

    def test_windows_riconosciuto(self):
        _sw("pc1", "microsoft", "windows 11 pro 64 bits version 25h2", "10.0.26200.1")
        _def("pc1", "CVE-2099-0002", "windows_11", produttore="microsoft", versione="10.0.26200.1")
        record = R.objects.create(cve_id="CVE-2099-0002", severity="high")
        cve_impact.recompute(record)
        self.assertEqual(self.esito("CVE-2099-0002", "pc1"), Imp.IMPACTS)

    def test_quando_defender_non_la_vede_piu_esce_e_resta_la_risoluzione(self):
        _sw("pc1", "demo", "demo tool")
        riga = _def("pc1", "CVE-2099-0001", "demo_tool")
        record = R.objects.create(cve_id="CVE-2099-0001", severity="high")
        cve_impact.recompute(record)
        riga.delete()
        cve_impact.recompute(record)
        self.assertIsNone(self.esito("CVE-2099-0001", "pc1"))
        self.assertEqual(SecurityCveRisoluzione.objects.filter(cve=record, host="pc1").count(), 1)


class SincronizzaTests(_Base):
    PC = [{"id": "m1", "computerDnsName": "pc1.demo.local"}]

    def righe(self, *voci):
        return [{"machineId": "m1", "cveId": c, "productName": "demo_tool", "productVendor": "demo", "productVersion": "1.0", "severity": s} for c, s in voci]

    def test_solo_le_gravi_entrano_con_la_severita_di_defender(self):
        with patch("security.services.cve_feeds.queue_recompute", return_value="in coda") as ricalcolo:
            esito = defender_vuln.sincronizza(pc=self.PC, righe=self.righe(("CVE-2099-0001", "Critical"), ("CVE-2099-0002", "High"), ("CVE-2099-0003", "Medium")))
        self.assertEqual(esito["cve_nuove"], 2)
        ricalcolo.assert_called_once()
        self.assertEqual(R.objects.get(cve_id="CVE-2099-0001").severity, "critical")
        self.assertFalse(R.objects.filter(cve_id="CVE-2099-0003").exists())
        self.assertEqual(D.objects.count(), 3)

    def test_spento_resta_solo_confronto(self):
        soc_settings.save({"defender.vulnerabilita.ibrido": False}, None)
        with patch("security.services.cve_feeds.queue_recompute") as ricalcolo:
            defender_vuln.sincronizza(pc=self.PC, righe=self.righe(("CVE-2099-0001", "Critical")))
        ricalcolo.assert_not_called()
        self.assertFalse(R.objects.exists())

    def test_non_tocca_una_cve_gia_nota(self):
        R.objects.create(cve_id="CVE-2099-0001", severity="medium")
        with patch("security.services.cve_feeds.queue_recompute", return_value=""):
            self.assertEqual(defender_vuln.sincronizza(pc=self.PC, righe=self.righe(("CVE-2099-0001", "Critical")))["cve_nuove"], 0)
        self.assertEqual(R.objects.get().severity, "medium")


class NvdTests(_Base):
    def test_defender_prima_nella_coda_nvd(self):
        R.objects.create(cve_id="CVE-2000-0001")
        _def("pc1", "CVE-2099-0002", "demo_tool", severita="High")
        _def("pc1", "CVE-2099-0003", "demo_tool", severita="Critical")
        self.assertEqual(cve_feeds.stale_cve_ids(3), ["CVE-2099-0003", "CVE-2099-0002", "CVE-2000-0001"])

    def test_spento_non_si_chiede_a_nvd(self):
        soc_settings.save({"defender.vulnerabilita.ibrido": False}, None)
        _def("pc1", "CVE-2099-0002", "demo_tool", severita="High")
        self.assertEqual(cve_feeds.stale_cve_ids(3), [])


class CoperturaTests(_Base):
    def test_programmi_letti_da_defender_sono_controllati(self):
        _sw("pc1", "demo", "demo tool", fonti=("defender",))
        _sw("pc1", "acme", "acme tool")
        self.assertEqual(sc.stati_cve()["demo|demo tool"], sc.NON_CONTROLLATO)  # Defender acceso ma ancora senza dati
        _def("pc1", "CVE-2099-0001", "demo_tool")
        stati = sc.stati_cve()
        self.assertEqual(stati["demo|demo tool"], sc.CONTROLLATO)
        self.assertEqual(stati["acme|acme tool"], sc.NON_CONTROLLATO)

    def test_spento_torna_non_controllato(self):
        _sw("pc1", "demo", "demo tool", fonti=("defender",))
        _def("pc1", "CVE-2099-0001", "demo_tool")
        soc_settings.save({"defender.vulnerabilita.attivo": False}, None)
        self.assertEqual(sc.stati_cve()["demo|demo tool"], sc.NON_CONTROLLATO)
