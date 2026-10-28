"""Release di Windows riconosciuta dalla build (services.windows_build). Dati sintetici."""
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from security.models import SecurityCveImpact, SecurityCveRecord, SecurityCveRisoluzione, SoftwareInstallation
from security.services import cve_gestione, cve_impact
from security.services import windows_build as wb
from security.services.configuration import set_setting


def _crit(product, end=None, version="*"):
    return {"vendor": "microsoft", "product": product, "version": version, "start_including": "", "start_excluding": "",
            "end_including": "", "end_excluding": end or "", "requires_platform": False}


class RegoleTests(SimpleTestCase):
    def test_build_dalla_versione(self):
        self.assertEqual(wb.build_da_versione("10.0.26200.6899"), 26200)
        self.assertEqual(wb.build_da_versione("6.2.9200.25000"), 9200)
        self.assertIsNone(wb.build_da_versione("526.21100.40"))
        self.assertIsNone(wb.build_da_versione(""))

    def test_build_del_criterio_dalle_versioni_o_dalla_tabella(self):
        self.assertEqual(wb.build_criterio(_crit("windows_11_23h2", "10.0.22631.5472")), 22631)
        self.assertEqual(wb.build_criterio(_crit("windows_server_2008", version="-")), 6003)
        self.assertEqual(wb.build_criterio(_crit("windows_server_2008", version="r2")), 7601)
        # la versione del criterio vince sulla tabella
        self.assertEqual(wb.build_criterio(_crit("windows_11_24h2", "10.0.26999.1")), 26999)
        # range che attraversa più release: niente deduzioni
        crit = _crit("windows_10", "10.0.19045.1")
        crit["start_including"] = "10.0.10240.0"
        self.assertIsNone(wb.build_criterio(crit))
        self.assertIsNone(wb.build_criterio(_crit("windows_99_xx", version="-")))

    def test_supporto(self):
        from datetime import date

        self.assertTrue(wb.supportata(wb.CLIENT, 26100, date(2026, 10, 28)))
        self.assertFalse(wb.supportata(wb.CLIENT, 19042, date(2026, 10, 28)))        # 20H2
        self.assertTrue(wb.supportata(wb.CLIENT, 22631, date(2026, 11, 10)))         # ultimo giorno incluso
        self.assertFalse(wb.supportata(wb.CLIENT, 22631, date(2026, 11, 11)))
        self.assertTrue(wb.supportata(wb.CLIENT, 26300, date(2030, 1, 1)))           # data non ancora fissata
        self.assertIsNone(wb.supportata(wb.CLIENT, 26999))

    def test_famiglia(self):
        self.assertEqual(wb.famiglia_cpe("windows_10_21h2"), wb.CLIENT)
        self.assertEqual(wb.famiglia_cpe("windows_server_2022"), wb.SERVER)
        self.assertIsNone(wb.famiglia_cpe("windows_defender"))
        self.assertIsNone(wb.famiglia_cpe("edge"))

    def test_abbina(self):
        criteri = wb.criteri_windows([_crit("windows_11_24h2", "10.0.26100.4270"), _crit("windows_11_23h2", "10.0.22631.5472"),
                                      _crit("windows_server_2019", "10.0.17763.7434")])
        stessi, motivo = wb.abbina(criteri, wb.CLIENT, 26100)
        self.assertEqual([c.criterio["product"] for c in stessi], ["windows_11_24h2"])
        from datetime import date

        oggi = date(2026, 10, 28)
        self.assertEqual(wb.abbina(criteri, wb.CLIENT, 26200, oggi), ([], None))  # non elencata, supportata
        # non elencata e fuori supporto: Microsoft non la elenca più anche se vulnerabile
        stessi, motivo = wb.abbina(criteri, wb.CLIENT, 19042, oggi)
        self.assertEqual(stessi, [])
        self.assertIn("fuori supporto", motivo)
        self.assertIn("non presente nella tabella", wb.abbina(criteri, wb.CLIENT, 26999, oggi)[1])
        # stessa build del server 2019 ma famiglia client: Windows 10 1809 non è colpito da questi criteri
        self.assertEqual(wb.abbina(criteri, wb.CLIENT, 17763, oggi), ([], None))
        self.assertEqual(wb.abbina(criteri, wb.CLIENT, None)[1], "versione di Windows non leggibile")
        ignoti = wb.criteri_windows([_crit("windows_11_99h9", version="-"), _crit("windows_11_24h2", "10.0.26100.4270")])
        self.assertIsNone(ignoti[0].build)
        stessi, motivo = wb.abbina(ignoti, wb.CLIENT, 26200, oggi)
        self.assertEqual(stessi, [])
        self.assertIn("windows_11_99h9", motivo)


class CalcoloTests(TestCase):
    def setUp(self):
        self.record = SecurityCveRecord.objects.create(
            cve_id="CVE-2099-0301", description="Sintetica Windows.", cvss=9.8,
            configurations=[_crit("windows_11_24h2", "10.0.26100.4270"), _crit("windows_10_21h2", "10.0.19044.5965"),
                            _crit("windows_server_2019", "10.0.17763.7434")],
        )
        self._inst("pc-win-01", "windows 11", "Windows 11", "10.0.26100.4000")          # 24H2 non aggiornato
        self._inst("pc-win-02", "windows 11", "Windows 11", "10.0.26100.4300")          # 24H2 aggiornato
        self._inst("pc-win-03", "windows 11 pro 64 bits version 25h2", "Windows 11 Pro 64 bits Version 25H2", "10.0.26200.6899")
        self._inst("pc-win-04", "windows 10", "Windows 10", "10.0.17763.1000")          # 1809: non elencata per il client
        self._inst("srv-win-01", "windows server 2019 standard", "Windows Server 2019 Standard", "10.0.17763.7000")
        self._inst("pc-win-05", "windows defender", "Windows Defender", "4.18.1")        # non è il sistema operativo
        self._inst("pc-win-06", "windows 11", "Windows 11", "10.0.26100.1000", vecchio=True)
        self._inst("pc-win-07", "windows 10", "Windows 10", "10.0.19042.4123")        # 20H2, fuori supporto

    def _inst(self, host, product, raw, version, vecchio=False):
        now = timezone.now()
        data = timezone.localdate() - timezone.timedelta(days=120 if vecchio else 0)
        return SoftwareInstallation.objects.create(
            dedup_key=f"{host}|{product}|{version}", source_kind="defender", host=host, host_display=host.upper(),
            vendor="microsoft", vendor_raw="Microsoft", product=product, product_raw=raw, version_raw=version,
            fonti=["defender"], still_detected=True, seen_at=now, last_seen_at=now, last_inventory_date=data,
        )

    def _accendi(self, valore=True):
        set_setting("cve.windows.per_build", valore, category="soc")

    def _esiti(self):
        cve_impact.recompute(self.record)
        return dict(self.record.impacts.values_list("host", "outcome"))

    def test_spento_resta_come_prima(self):
        esiti = self._esiti()
        self.assertEqual(esiti.get("pc-win-01"), SecurityCveImpact.TO_VERIFY)
        self.assertNotIn("pc-win-05", esiti)
        # Il nome lungo di WatchGuard non somiglia a «windows_11_25h2»: senza l'algoritmo il PC è invisibile.
        self.assertNotIn("pc-win-03", esiti)

    def test_acceso_abbina_per_release(self):
        self._accendi()
        esiti = self._esiti()
        self.assertEqual(esiti["pc-win-01"], SecurityCveImpact.IMPACTS)
        self.assertEqual(esiti["pc-win-02"], SecurityCveImpact.NOT_IMPACTED)
        self.assertEqual(esiti["pc-win-03"], SecurityCveImpact.NOT_IMPACTED)   # 25H2 non elencata
        self.assertEqual(esiti["pc-win-04"], SecurityCveImpact.NOT_IMPACTED)   # client 17763 ≠ server 2019
        self.assertEqual(esiti["srv-win-01"], SecurityCveImpact.IMPACTS)        # server 2019 sotto la 7434
        self.assertEqual(esiti["pc-win-06"], SecurityCveImpact.TO_VERIFY)       # inventario vecchio
        self.assertNotIn("pc-win-05", esiti)                                    # Defender non è Windows
        self.assertEqual(esiti["pc-win-07"], SecurityCveImpact.TO_VERIFY)       # 20H2 non elencata ma fuori supporto
        self.assertIn("fuori supporto", self.record.impacts.get(host="pc-win-07").explanation)
        spiegazione = self.record.impacts.get(host="pc-win-03").explanation
        self.assertIn("Windows 11 25H2", spiegazione)
        self.assertIn("la CVE non riguarda questa release", spiegazione)
        self.assertIn("Release riconosciuta dalla build: Windows 11 24H2", self.record.impacts.get(host="pc-win-01").explanation)

    def test_release_ignota_resta_da_verificare(self):
        self.record.configurations = self.record.configurations + [_crit("windows_11_99h9", version="-")]
        self.record.save()
        self._accendi()
        esiti = self._esiti()
        self.assertEqual(esiti["pc-win-03"], SecurityCveImpact.TO_VERIFY)
        self.assertIn("non si riconosce la release", self.record.impacts.get(host="pc-win-03").explanation)

    def test_uscita_per_rivalutazione_non_e_una_correzione(self):
        self.assertEqual(self._esiti()["pc-win-02"], SecurityCveImpact.TO_VERIFY)       # spento
        self._accendi()
        self.assertEqual(self._esiti()["pc-win-02"], SecurityCveImpact.NOT_IMPACTED)    # acceso: già aggiornato
        r = SecurityCveRisoluzione.objects.get(host="pc-win-02")
        self.assertEqual(r.come, SecurityCveRisoluzione.RIVALUTATA)
        self.assertNotIn(r, cve_gestione.correzioni_valide(timezone.now() - timezone.timedelta(days=1)))

    def test_anteprima_non_scrive(self):
        prima = list(self.record.impacts.values_list("host", "outcome"))
        d = wb.anteprima()
        self.assertEqual(list(self.record.impacts.values_list("host", "outcome")), prima)
        self.assertEqual(d["cve"], 1)
        self.assertIn("CVE-2099-0301", d["cve_con_nuovo_alert"])
