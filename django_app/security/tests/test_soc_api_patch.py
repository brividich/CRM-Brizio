"""WatchGuard API (PC, patch, software), confronto Defender, priorità CVE, tabella MAC, Windows indietro. Dati sintetici."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, DispositivoIntune
from security.models import (
    DefenderVulnerabilita,
    SecurityCenterSetting,
    SecurityCveRecord,
    SoftwareCpeMapping,
    SoftwareInstallation,
    WatchGuardDispositivo,
    WatchGuardPatch,
)
from security.services import cve_impact, cve_pannello, defender_vuln, soc_settings, watchguard_api

CRED = {"url_api": "https://api.deu.cloud.watchguard.com", "account_id": "ACC-1234567", "access_id": "id-sintetico",
        "password": "pw-sintetica", "api_key": "chiave-sintetica"}


def _inst(host, version, hub=None, fonti=("watchguard",)):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|viewer|{version}", source_kind=fonti[0], host=host, host_display=host.upper(), hub_asset=hub,
        vendor="acme", vendor_raw="Acme", product="viewer", product_raw="Acme Viewer", version_raw=version, fonti=list(fonti),
        still_detected=True, seen_at=now, last_seen_at=now, last_inventory_date=timezone.localdate())


class CredenzialiTests(TestCase):
    def test_salva_cifrate_e_tiene_i_segreti_se_vuoti(self):
        self.assertEqual(watchguard_api.salva_credenziali(CRED), [])
        grezzo = SecurityCenterSetting.objects.get(key=watchguard_api.SETTING).value
        self.assertNotIn("pw-sintetica", grezzo)
        self.assertTrue(watchguard_api.configurato())
        self.assertEqual(watchguard_api.salva_credenziali({**CRED, "password": "", "api_key": "", "access_id": "nuovo"}), [])
        cfg = watchguard_api.credenziali()
        self.assertEqual((cfg["access_id"], cfg["password"], cfg["api_key"]), ("nuovo", "pw-sintetica", "chiave-sintetica"))
        riepilogo = watchguard_api.riepilogo()
        self.assertEqual((riepilogo["password"], riepilogo["api_key"]), (True, True))
        self.assertNotIn("pw-sintetica", str(riepilogo))

    def test_url_copiato_da_managed_access(self):
        for incollato in ("https://api.deu.cloud.watchguard.com/rest/", "https://api.deu.cloud.watchguard.com/oauth/token"):
            self.assertEqual(watchguard_api.salva_credenziali({**CRED, "url_api": incollato}), [])
            self.assertEqual(watchguard_api.credenziali()["url_api"], "https://api.deu.cloud.watchguard.com")
        self.assertTrue(watchguard_api.salva_credenziali({**CRED, "url_api": "https://api.deu.cloud.watchguard.com/altro"}))

    def test_url_fuori_da_watchguard_rifiutato(self):
        errori = watchguard_api.salva_credenziali({**CRED, "url_api": "https://example.com"})
        self.assertTrue(any("URL API" in e for e in errori))
        self.assertFalse(watchguard_api.configurato())

    def test_pagina_impostazioni_e_post_solo_per_chi_configura(self):
        admin = get_user_model().objects.create(username="wg_admin", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        page = self.client.get(reverse("security:soc_settings"))
        self.assertContains(page, "Credenziali API WatchGuard")
        self.assertContains(page, "WatchGuard Endpoint Security (API)")
        self.client.post(reverse("security:watchguard_credenziali"), {**CRED, "azione": "salva"})
        self.assertTrue(watchguard_api.configurato())
        page = self.client.get(reverse("security:soc_settings"))
        self.assertNotContains(page, "pw-sintetica")
        self.assertNotContains(page, "chiave-sintetica")
        utente = get_user_model().objects.create(username="wg_utente")
        self.client.force_login(utente)
        self.client.post(reverse("security:watchguard_credenziali"), {"azione": "cancella"})
        self.assertTrue(watchguard_api.configurato())


class WatchGuardSyncTests(TestCase):
    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="WG-1", name="pc-wg-01")

    def test_dispositivi_protezione_e_senza_agente(self):
        out = watchguard_api.sincronizza_dispositivi(
            dispositivi=[{"device_id": "d1", "host_name": "PC-WG-01.dominio.local", "mac_addresses": ["AA-BB-CC-00-00-01"],
                          "agent_version": "1.2", "last_connection": "2026-10-22T08:00:00Z"},
                         {"device_id": "d2", "host_name": "PC-WG-02"}],
            protezione=[{"device_id": "d1", "accumulated_protection_status": 1, "protection_engine_update_status": 2},
                        {"device_id": "d2", "accumulated_protection_status": 3}],
            non_gestiti=[{"device_id": "u1", "host_name": "", "ip_address": "10.0.0.50", "mac_address": "aa:bb:cc:00:00:99"}])
        self.assertEqual(out, {"pc": 2, "senza_agente": 1, "spariti": 0})
        d1 = WatchGuardDispositivo.objects.get(device_id="d1")
        self.assertEqual((d1.host, d1.hub_asset, d1.mac_lista, d1.protetto), ("pc-wg-01", self.pc, ["aa:bb:cc:00:00:01"], True))
        self.assertFalse(WatchGuardDispositivo.objects.get(device_id="d2").protetto)
        self.assertFalse(WatchGuardDispositivo.objects.get(device_id="unmanaged:u1").gestito)
        out = watchguard_api.sincronizza_dispositivi(dispositivi=[], protezione=[], non_gestiti=[])
        self.assertEqual(out["spariti"], 3)

    def test_patch_aperte_chiuse_ed_esito(self):
        riga = {"device_id": "d1", "patch_id": "p1", "host_name": "PC-WG-01", "patch_name": "Acme Viewer 2.0",
                "program_name": "Acme Viewer", "program_version": "1.0", "patch_criticality": 201,
                "patch_installation_availability": 1, "patch_cve_ids": ["cve-2099-0201", "CVE-2099-0202"],
                "patch_release_date": "2026-10-01T00:00:00Z"}
        self.assertEqual(watchguard_api.sincronizza_patch(righe=[riga]), {"patch": 1, "chiuse": 0})
        p = WatchGuardPatch.objects.get()
        self.assertEqual((p.cve_lista, p.criticita_label, p.hub_asset), (["CVE-2099-0201", "CVE-2099-0202"], "Critica", self.pc))
        self.assertIn(("CVE-2099-0201", "pc-wg-01"), watchguard_api.patch_aperte_per_cve({"CVE-2099-0201"}))
        WatchGuardPatch.objects.update(esito=4)
        self.assertTrue(WatchGuardPatch.objects.get().esito_errore)
        self.assertEqual(watchguard_api.sincronizza_patch(righe=[]), {"patch": 0, "chiuse": 1})
        p.refresh_from_db()
        self.assertFalse(p.presente)
        self.assertIsNotNone(p.chiusa_il)
        self.assertEqual(watchguard_api.patch_aperte_per_cve({"CVE-2099-0201"}), {})

    def test_software_salta_le_patch_e_lettura_vuota_non_importa(self):
        preview = watchguard_api.anteprima_software([
            {"host_name": "PC-WG-01", "name": "Acme Viewer", "publisher": "Acme", "version": "1.0"},
            {"host_name": "PC-WG-01", "name": "KB500", "publisher": "Microsoft", "version": "1", "is_patch": True}])
        self.assertEqual((len(preview.valid), len(preview.skipped)), (1, 1))
        self.assertEqual(watchguard_api.sincronizza_software(righe=[])["importate"], 0)

    def test_run_spento_e_senza_credenziali(self):
        self.assertEqual(watchguard_api.run(), {"attivo": False})
        soc_settings.save({"watchguard.api.patch": True}, None)
        self.assertFalse(watchguard_api.run()["ok"])

    def test_pagina_patch_e_protezione(self):
        watchguard_api.sincronizza_patch(righe=[{"device_id": "d1", "patch_id": "p1", "host_name": "PC-WG-01",
                                                 "patch_name": "Acme Viewer 2.0", "patch_criticality": 202,
                                                 "patch_cve_ids": ["CVE-2099-0201"]}])
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0201", kev=True)
        admin = get_user_model().objects.create(username="wg_pag", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        page = self.client.get(reverse("security:watchguard_pc"))
        self.assertContains(page, "Acme Viewer 2.0")
        self.assertContains(page, "CVE sfruttata")
        self.assertContains(page, "Credenziali API WatchGuard non configurate")


class PannelloCveTests(TestCase):
    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="CVP-1", name="pc-cvp-01")
        SoftwareCpeMapping.objects.create(vendor="acme", product="viewer", cpe_vendor="acme", cpe_product="viewer", confirmed=True)
        self.record = SecurityCveRecord.objects.create(
            cve_id="CVE-2099-0201", description="Sintetica.", cvss=7.5, epss=0.4,
            configurations=[{"vendor": "acme", "product": "viewer", "end_excluding": "2.0"}])
        _inst("pc-cvp-01", "1.0", hub=self.pc, fonti=("watchguard", "defender"))
        _inst("pc-cvp-02", "1.0", fonti=("watchguard", "defender"))
        cve_impact.recompute(self.record)

    def test_priorita(self):
        rec = SecurityCveRecord(cvss=5.0, epss=0.0)
        self.assertEqual(cve_pannello.priorita(rec)[0], "normale")
        rec.cvss = 9.1
        self.assertEqual(cve_pannello.priorita(rec)[0], "presto")
        rec.kev = True
        self.assertEqual(cve_pannello.priorita(rec)[0], "subito")
        self.assertEqual(cve_pannello.priorita(self.record)[:2], ("subito", "Subito"))

    def test_patch_e_defender_nel_dettaglio(self):
        WatchGuardPatch.objects.create(device_id="d1", patch_id="p1", host="pc-cvp-01", nome="Acme Viewer 2.0",
                                       cve="|CVE-2099-0201|", disponibilita=1)
        soc_settings.save({"defender.vulnerabilita.attivo": True}, None)
        defender_vuln.sincronizza(pc=[{"id": "m1", "computerDnsName": "pc-cvp-01.dominio.local"},
                                      {"id": "m3", "computerDnsName": "pc-cvp-03"}],
                                  righe=[{"machineId": "m1", "cveId": "CVE-2099-0201", "productName": "viewer", "productVersion": "1.0"},
                                         {"machineId": "m3", "cveId": "CVE-2099-0201", "productName": "viewer", "productVersion": "1.0"}])
        self.assertEqual(DefenderVulnerabilita.objects.count(), 2)
        d = cve_pannello.dettaglio(self.record.cve_id)
        self.assertEqual(d["pc_con_patch"], 1)
        self.assertEqual((d["defender"]["comuni"], d["defender"]["solo_soc"], d["defender"]["solo_defender"]),
                         (1, ["pc-cvp-02"], ["pc-cvp-03"]))
        righe = cve_pannello.per_programma("acme|viewer")["colpiscono"]
        self.assertEqual((righe[0]["priorita"], righe[0]["pc_con_patch"]), ("subito", 1))
        self.assertEqual(cve_pannello.per_asset(self.pc)["defender"]["comuni"], 1)
        admin = get_user_model().objects.create(username="cvp_admin", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        page = self.client.get(reverse("security:cve_pannello_cve", args=[self.record.cve_id]))
        self.assertContains(page, "WatchGuard ha già la patch per 1 PC")
        self.assertContains(page, "Defender conferma")
        self.assertContains(page, "Defender non la vede")
        self.assertContains(page, "Solo Defender: 1 PC")
        self.assertContains(page, "Probabile attacco")

    def test_defender_spento_niente_confronto(self):
        DefenderVulnerabilita.objects.create(host="pc-cvp-01", cve_id="CVE-2099-0201")
        self.assertIsNone(cve_pannello.dettaglio(self.record.cve_id)["defender"])


class RetiEWindowsTests(TestCase):
    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="NET-1", name="pc-net-01")

    def test_tabella_mac_e_porta_del_pc(self):
        from contatori.models import DispositivoSNMP
        from contatori.snmp_capture import Record
        from contatori.tabella_mac import FDB_PORT, IF_NAME, BASE_PORT_IFINDEX, Q_FDB_PORT, porte_di_asset, righe_da_record, salva

        sw = DispositivoSNMP.objects.create(nome="SW-01", categoria=DispositivoSNMP.Categoria.RETE, host="10.0.0.2")
        fdb_q = [Record(f"{Q_FDB_PORT}.10.170.187.204.0.0.1", "2", "5")]  # aa:bb:cc:00:00:01 su porta bridge 5, VLAN 10
        fdb_q += [Record(f"{Q_FDB_PORT}.10.170.187.204.0.1.{i}", "2", "24") for i in range(6)]  # uplink con 6 MAC
        righe = righe_da_record(fdb_q, [Record(f"{FDB_PORT}.1.2.3.4.5.6", "2", "1")],
                                [Record(f"{BASE_PORT_IFINDEX}.5", "2", "1005"), Record(f"{BASE_PORT_IFINDEX}.24", "2", "1024")],
                                [Record(f"{IF_NAME}.1005", "4", "Gi1/0/5"), Record(f"{IF_NAME}.1024", "4", "Gi1/0/24")])
        self.assertEqual(len(righe), 7)
        self.assertEqual((righe[0]["mac"], righe[0]["porta"], righe[0]["vlan"]), ("aa:bb:cc:00:00:01", "Gi1/0/5", 10))
        salva(sw, righe)
        DispositivoIntune.objects.create(intune_id="i-net-1", nome="pc-net-01", asset=self.pc, mac_ethernet="aa:bb:cc:00:00:01")
        porte = porte_di_asset(self.pc)
        self.assertEqual((porte[0].porta, porte[0].porta_accesso), ("Gi1/0/5", True))
        from assets.services.fonti_dispositivo import per_asset

        rete = [f for f in per_asset(self.pc, profilo="workstation") if f["nome"] == "Rete"]
        self.assertEqual(rete[0]["dettaglio"], "SW-01 · Gi1/0/5")
        admin = get_user_model().objects.create(username="net_admin", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        page = self.client.get(reverse("contatori:snmp_dispositivo", args=[sw.pk]))
        self.assertContains(page, "Chi è collegato alle porte")
        self.assertContains(page, "pc-net-01")

    def test_windows_indietro_rispetto_agli_altri_pc(self):
        from assets.services.intune import aggiornamento_windows, build_windows, per_asset

        self.assertEqual(build_windows("10.0.26100.2033"), (26100, 2033))
        self.assertIsNone(build_windows("17.1"))
        DispositivoIntune.objects.create(intune_id="i-w-1", nome="pc-net-01", asset=self.pc, sistema="Windows",
                                         versione_sistema="10.0.26100.2033", presente=True)
        DispositivoIntune.objects.create(intune_id="i-w-2", nome="pc-net-02", sistema="Windows",
                                         versione_sistema="10.0.26100.2314", presente=True)
        stato = per_asset(self.pc)[0].windows
        self.assertEqual((stato["indietro"], stato["riferimento"], stato["ramo"]), (True, "26100.2314", "Windows 11 24H2"))
        self.assertFalse(aggiornamento_windows(DispositivoIntune(sistema="Windows", versione_sistema="10.0.26100.2314"))["indietro"])

    def test_run_tabella_mac_spento(self):
        from contatori.tabella_mac import run

        soc_settings.save({"apparati.tabella_mac.attivo": False}, None)
        self.assertEqual(run(), {"attivo": False})


class TaskPatchTests(TestCase):
    def test_esito_dai_task_di_installazione(self):
        WatchGuardPatch.objects.create(device_id="d1", patch_id="p1", host="pc-wg-01", nome="Acme Viewer 2.0")
        recente = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        def finto_get(percorso, params=None, **kw):
            if percorso == "/tasks":
                return {"data": [{"id": "t1", "type": 6, "status": {"last_job_date": recente}}], "total_items": 1}
            if percorso.endswith("/jobs"):
                return [{"id": "j1", "date": recente}]
            return {"data": [{"host_name": "PC-WG-01", "patch_info": {"patch_name": "Acme Viewer 2.0", "result": 4}}],
                    "total_items": None}

        with mock.patch.object(watchguard_api, "get", side_effect=finto_get):
            self.assertEqual(watchguard_api.sincronizza_task(), {"task": 1, "patch_aggiornate": 1})
        self.assertEqual(WatchGuardPatch.objects.get().esito_label, "Errore di installazione")
