"""Integrazione Contatori IT ↔ Asset ↔ SOC. Dati sintetici (IP di documentazione 192.0.2.x)."""
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from .integrazione import allineamento_asset, crea_asset_da_apparato, postura_snmp, quadro_integrazione
from .models import DispositivoSNMP, ImpostazioniSNMP, Macchina, RilevazioneSNMP, StatoSNMP
from .tests import _AuthedClientMixin


def _asset(**kw):
    from assets.models import Asset

    kw.setdefault("name", "Asset demo")
    return Asset.objects.create(**kw)


class AllineamentoAssetTests(TestCase):
    def test_seriale_ip_e_stato_diversi(self):
        from assets.models import Asset, AssetEndpoint

        asset = _asset(asset_tag="INT-1", serial_number="SN-AAA", status=Asset.STATUS_RETIRED)
        AssetEndpoint.objects.create(asset=asset, ip="192.0.2.20")
        d = DispositivoSNMP.objects.create(nome="Switch", host="192.0.2.21", matricola="SN-BBB", asset=asset)
        righe = allineamento_asset(d)
        dati = [r["dato"] for r in righe]
        self.assertEqual(righe[0]["livello"], "danger")  # asset dismesso ma apparato interrogato: prima
        self.assertIn("Numero di serie", dati)
        self.assertIn("Indirizzo IP", dati)

    def test_tutto_allineato(self):
        from assets.models import AssetEndpoint

        asset = _asset(asset_tag="INT-2", serial_number="sn 123", model="X1")
        AssetEndpoint.objects.create(asset=asset, ip="192.0.2.22")
        d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.22", matricola="SN123", modello="X1", asset=asset)
        self.assertEqual(allineamento_asset(d), [])


class CreaAssetTests(_AuthedClientMixin, TestCase):
    def test_crea_asset_da_dispositivo(self):
        from assets.models import Asset

        d = DispositivoSNMP.objects.create(nome="FW sede", host="192.0.2.30", categoria="FIREWALL",
                                           produttore="Vendor", modello="FW-100", matricola="FW-SN-1")
        r = self.client.post(reverse("contatori:apparato_crea_asset", args=["snmp", d.pk]))
        self.assertRedirects(r, reverse("contatori:snmp_dispositivo", args=[d.pk]), fetch_redirect_response=False)
        d.refresh_from_db()
        self.assertIsNotNone(d.asset)
        self.assertEqual((d.asset.asset_type, d.asset.serial_number, d.asset.model), ("FIREWALL", "FW-SN-1", "FW-100"))
        self.assertEqual(list(d.asset.endpoints.values_list("ip", flat=True)), ["192.0.2.30"])
        # Seconda volta: nessun doppione.
        self.client.post(reverse("contatori:apparato_crea_asset", args=["snmp", d.pk]))
        self.assertEqual(Asset.objects.filter(serial_number="FW-SN-1").count(), 1)

    def test_crea_asset_da_mfc(self):
        m = Macchina.objects.create(reparto="Ufficio", matricola="MFC-SN-9", modello="M1", host="192.0.2.31")
        asset = crea_asset_da_apparato(m)
        self.assertEqual((asset.asset_type, asset.reparto), ("STAMPANTE", "Ufficio"))
        m.refresh_from_db()
        self.assertEqual(m.asset_id, asset.pk)

    def test_senza_gestione_nessun_asset(self):
        from assets.models import Asset

        d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.32")
        with mock.patch("contatori.permessi.puo_gestire", return_value=False):
            self.client.post(reverse("contatori:apparato_crea_asset", args=["snmp", d.pk]))
        self.assertFalse(Asset.objects.exists())

    def test_scheda_senza_asset_propone_crea(self):
        d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.33")
        r = self.client.get(reverse("contatori:snmp_dispositivo", args=[d.pk]))
        self.assertContains(r, reverse("contatori:apparato_crea_asset", args=["snmp", d.pk]))


class PosturaSnmpTests(TestCase):
    def test_community_predefinita_e_in_chiaro(self):
        d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.40", versione="v2c", community="public")
        titoli = [p["titolo"] for p in postura_snmp(d)]
        self.assertEqual(titoli[0], "Community predefinita")
        self.assertIn("SNMPv2c senza cifratura", titoli)

    def test_v3_nessun_rilievo(self):
        d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.41", versione="v3")
        self.assertEqual(postura_snmp(d), [])

    def test_globale_v1_senza_community_propria(self):
        cfg = ImpostazioniSNMP.get_solo()
        cfg.community, cfg.version = "segreta-sintetica", "v1"
        cfg.save()
        d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.42")
        self.assertEqual([p["livello"] for p in postura_snmp(d)], ["warn"])


class EventiSocTests(TestCase):
    def setUp(self):
        self.d = DispositivoSNMP.objects.create(nome="FW", host="192.0.2.50", categoria="FIREWALL")

    def _ril(self, errore=""):
        RilevazioneSNMP.objects.create(dispositivo=self.d, stato=StatoSNMP.ERROR if errore else StatoSNMP.OK,
                                       errore=errore)

    def test_caduta_e_ripristino_aprono_e_chiudono_l_alert(self):
        from security.models import SecurityAlert, SecurityEventRecord
        from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
        from security.services.rule_engine import evaluate_security_rules

        from .soc import valuta

        self._ril()
        self._ril("SNMP-003 timeout")
        self.assertIsNone(valuta(self.d))  # un solo controllo fallito: non e' ancora una caduta
        self._ril("SNMP-003 timeout")
        evento = valuta(self.d)
        self.assertEqual(evento.event_type, "apparato_irraggiungibile")
        self._ril("SNMP-003 timeout")
        self.assertIsNone(valuta(self.d))  # gia' giu': nessun doppione
        evaluate_security_rules()
        alert = SecurityAlert.objects.get(dedup_hash=evento.dedup_hash)
        self.assertIn(alert.status, ACTIVE_ALERT_STATUSES)
        self._ril()
        self.assertEqual(valuta(self.d).event_type, "apparato_raggiungibile")
        evaluate_security_rules()
        alert.refresh_from_db()
        self.assertNotIn(alert.status, ACTIVE_ALERT_STATUSES)
        self.assertEqual(SecurityEventRecord.objects.count(), 2)

    def test_stampanti_e_bozze_non_vanno_al_soc(self):
        from .soc import valuta

        stampante = DispositivoSNMP.objects.create(nome="Prt", host="192.0.2.51", categoria="STAMPANTE")
        bozza = DispositivoSNMP.objects.create(nome="Nuovo", host="192.0.2.52", categoria="RETE", verificato=False)
        for d in (stampante, bozza):
            for _ in range(3):
                RilevazioneSNMP.objects.create(dispositivo=d, stato=StatoSNMP.ERROR, errore="timeout")
            self.assertIsNone(valuta(d))

    def test_interrogazione_fallita_passa_dal_soc(self):
        from security.models import SecurityEventRecord

        from .services import interroga_dispositivo
        from .snmp import SNMPError

        RilevazioneSNMP.objects.create(dispositivo=self.d, stato=StatoSNMP.OK)
        with mock.patch("contatori.snmp.leggi_specifiche", side_effect=SNMPError("timeout sintetico")):
            interroga_dispositivo(self.d)
            interroga_dispositivo(self.d)
        self.assertTrue(SecurityEventRecord.objects.filter(event_type="apparato_irraggiungibile").exists())


class FirmwareSocAllineatoTests(TestCase):
    def _riga(self, d):
        from security.models import SoftwareInstallation

        return SoftwareInstallation.objects.get(source_kind="snmp_firmware", host=d.host)

    def setUp(self):
        from security.services.firmware_inventory import sincronizza_dispositivo

        self.d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.60", produttore="Vendor", modello="SW-1",
                                                firmware="1.2.3")
        sincronizza_dispositivo(self.d)

    def test_disattivato_non_piu_rilevato(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.d.attivo = False
            self.d.save()
        self.assertFalse(self._riga(self.d).still_detected)

    def test_ip_cambiato_dismette_il_vecchio_host(self):
        vecchio = self._riga(self.d)
        with self.captureOnCommitCallbacks(execute=True):
            self.d.host = "192.0.2.61"
            self.d.save()
        vecchio.refresh_from_db()
        self.assertFalse(vecchio.still_detected)

    def test_asset_collegato_segue_il_firmware(self):
        asset = _asset(asset_tag="INT-FW")
        with self.captureOnCommitCallbacks(execute=True):
            self.d.asset = asset
            self.d.save(update_fields=["asset", "aggiornato_il"])
        self.assertEqual(self._riga(self.d).hub_asset_id, asset.pk)


class SchedaSicurezzaTests(_AuthedClientMixin, TestCase):
    def test_cve_del_firmware_nella_scheda(self):
        from security.models import SecurityCveImpact, SecurityCveRecord
        from security.services.firmware_inventory import sincronizza_dispositivo

        d = DispositivoSNMP.objects.create(nome="Sw", host="192.0.2.70", produttore="Vendor", modello="SW-2",
                                           firmware="2.0", versione="v2c", community="public")
        riga = sincronizza_dispositivo(d)
        cve = SecurityCveRecord.objects.create(cve_id="CVE-2099-0001", cvss=9.8, kev=True)
        SecurityCveImpact.objects.create(cve=cve, host=d.host, installation=riga, outcome=SecurityCveImpact.IMPACTS,
                                         explanation="Versione sintetica nel range vulnerabile")
        r = self.client.get(reverse("contatori:snmp_dispositivo", args=[d.pk]))
        self.assertContains(r, "CVE-2099-0001")
        self.assertContains(r, "Community predefinita")
        self.assertNotContains(r, ">public<")  # mai il valore della community
        dash = self.client.get(reverse("contatori:dashboard"))
        self.assertContains(dash, "con firmware vulnerabile")

    def test_link_host_esposti_del_soc_apre_la_scheda_apparato(self):
        from security.models import SecurityCveImpact, SecurityCveRecord

        d = DispositivoSNMP.objects.create(nome="Switch piano 1", host="192.0.2.71")
        cve = SecurityCveRecord.objects.create(cve_id="CVE-2099-0002", cvss=7.0)
        SecurityCveImpact.objects.create(cve=cve, host=d.host, outcome=SecurityCveImpact.IMPACTS, explanation="x")
        r = self.client.get(reverse("security:vulnerabilities"))
        self.assertContains(r, reverse("contatori:snmp_dispositivo", args=[d.pk]))


class CentraleIntegrazioneTests(_AuthedClientMixin, TestCase):
    def test_apparati_senza_asset_e_su_asset_dismesso(self):
        from assets.models import Asset

        DispositivoSNMP.objects.create(nome="Sw libero", host="192.0.2.80")
        DispositivoSNMP.objects.create(nome="Cam", host="192.0.2.81", categoria="TVCC_CAMERA")
        dismesso = _asset(asset_tag="INT-D", status=Asset.STATUS_RETIRED)
        Macchina.objects.create(reparto="Vecchia", matricola="OLD-1", asset=dismesso)
        q = quadro_integrazione()
        self.assertEqual(q["n_senza_asset"], 1)  # telecamere escluse
        self.assertEqual(q["n_dismessi"], 1)
        r = self.client.get(reverse("contatori:dashboard"))
        self.assertContains(r, "senza asset")
        self.assertContains(r, "su asset dismess")


class ImpostazioniTests(_AuthedClientMixin, TestCase):
    def test_pagina_dedicata_salva_e_registra_senza_community(self):
        from core.models import AuditLog

        r = self.client.post(reverse("contatori:impostazioni"), {
            "community": "sintetica", "port": "161", "timeout": "4", "version": "v2c",
            "tvcc_intervallo_nvr": "5", "tvcc_intervallo_telecamere": "30", "tvcc_retention_giorni": "14",
        })
        self.assertRedirects(r, reverse("contatori:impostazioni"))
        self.assertEqual(ImpostazioniSNMP.get_solo().timeout, 4)
        voce = AuditLog.objects.filter(azione="impostazioni_snmp_salvate").latest("pk")
        self.assertNotIn("sintetica", str(voce.dettaglio))
        self.assertNotContains(self.client.get(reverse("contatori:macchine")), "Salva impostazioni")


class AssetSchedaMonitoraggioTests(_AuthedClientMixin, TestCase):
    def test_asset_videosorveglianza_usa_il_riquadro_con_permessi(self):
        asset = _asset(asset_tag="CCTV-T1", asset_type="CCTV")
        DispositivoSNMP.objects.create(nome="NVR demo", host="192.0.2.90", categoria="TVCC_NVR", asset=asset)
        r = self.client.get(reverse("assets:asset_view", args=[asset.pk]))
        self.assertContains(r, "Apri in Contatori IT")
        with mock.patch("assets.services.it_monitoring.acl_allows_path", return_value=False):
            r = self.client.get(reverse("assets:asset_view", args=[asset.pk]))
        self.assertNotContains(r, "192.0.2.90")

    def test_ip_dal_monitoraggio_diventa_punto_rete(self):
        from assets.services.it_identity_diff import snmp_identity_diffs

        asset = _asset(asset_tag="IT-IP1", asset_type="FIREWALL")
        DispositivoSNMP.objects.create(nome="FW", host="192.0.2.91", asset=asset)
        diff = next(d for d in snmp_identity_diffs(asset) if d["field"] == "ip")
        self.client.post(reverse("assets:asset_view", args=[asset.pk]),
                         {"action": "apply_snmp_identity", "field": "ip", "value": diff["snmp_value"]})
        self.assertEqual(list(asset.endpoints.values_list("ip", flat=True)), ["192.0.2.91"])
        self.assertFalse([d for d in snmp_identity_diffs(asset) if d["field"] == "ip"])
