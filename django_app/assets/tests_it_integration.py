"""Integrazione asset IT <-> SNMP <-> SOC: abbinamento unico e copertura monitoraggio."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, AssetEndpoint
from assets.services.identity_match import (
    REASON_HOSTNAME,
    REASON_IP,
    REASON_IP_AMBIGUOUS,
    REASON_IP_LINKED,
    REASON_NONE,
    REASON_SERIAL,
    match_hub_asset,
)
from contatori.models import DispositivoSNMP
from contatori.services import trova_asset_snmp
from security.models import SecurityAsset
from security.services.asset_signals import suggest_hub_asset


class IdentityMatchTests(TestCase):
    def setUp(self):
        self.pc = Asset.objects.create(asset_tag="DEMO-PC1", name="PC-DEMO-01", asset_type="PC", serial_number="SN-DEMO-1")
        self.printer = Asset.objects.create(asset_tag="DEMO-PRN", name="Stampante demo", asset_type="STAMPANTE")

    def test_serial_wins_and_retired_assets_are_ignored(self):
        Asset.objects.create(asset_tag="DEMO-OLD", name="Vecchio", serial_number="SN-DEMO-1", status=Asset.STATUS_RETIRED)
        self.assertEqual(match_hub_asset(serial="sn-demo-1"), (self.pc, REASON_SERIAL))

    def test_ip_on_endpoint(self):
        AssetEndpoint.objects.create(asset=self.printer, ip="192.0.2.10")
        self.assertEqual(match_hub_asset(ip="192.0.2.10"), (self.printer, REASON_IP))

    def test_ip_linked_in_snmp_helps_soc(self):
        DispositivoSNMP.objects.create(nome="Stampante", host="192.0.2.20", asset=self.printer)
        soc_device = SecurityAsset.objects.create(hostname="prn-uff", ip_address="192.0.2.20")
        self.assertEqual(suggest_hub_asset(soc_device), (self.printer, REASON_IP_LINKED))

    def test_ip_linked_in_soc_helps_snmp(self):
        SecurityAsset.objects.create(hostname="pc-demo-01", ip_address="192.0.2.30", hub_asset=self.pc)
        self.assertEqual(trova_asset_snmp(host="192.0.2.30"), (self.pc, REASON_IP_LINKED))

    def test_ambiguous_ip_never_picks(self):
        AssetEndpoint.objects.create(asset=self.pc, ip="192.0.2.40")
        AssetEndpoint.objects.create(asset=self.printer, ip="192.0.2.40")
        self.assertEqual(match_hub_asset(ip="192.0.2.40"), (None, REASON_IP_AMBIGUOUS))

    def test_fqdn_matches_short_hostname(self):
        soc_device = SecurityAsset.objects.create(hostname="pc-demo-01.dominio.local")
        self.assertEqual(suggest_hub_asset(soc_device), (self.pc, REASON_HOSTNAME))

    def test_nothing_found(self):
        self.assertEqual(match_hub_asset(serial="X", ip="not-an-ip", hostname="sconosciuto"), (None, REASON_NONE))


class DeviceListCoverageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("cov-demo", "cov@example.test", "synthetic-only")
        self.client.force_login(self.user)
        self.ok = Asset.objects.create(asset_tag="DEMO-OK", name="Server regolare", asset_type="SERVER")
        self.silent = Asset.objects.create(asset_tag="DEMO-MUTO", name="Switch muto", asset_type="HW")
        self.bare = Asset.objects.create(asset_tag="DEMO-NUDO", name="PC scoperto", asset_type="PC")
        DispositivoSNMP.objects.create(nome="srv", host="192.0.2.50", asset=self.ok, snmp_stato="OK",
                                       snmp_ultimo_controllo=timezone.now())
        DispositivoSNMP.objects.create(nome="sw", host="192.0.2.51", asset=self.silent, snmp_stato="OK",
                                       snmp_ultimo_controllo=timezone.now() - timedelta(days=10))

    def page(self, **params):
        return self.client.get(reverse("assets:device_list"), params)

    def test_column_shows_state_per_asset(self):
        response = self.page(rows=96)
        self.assertContains(response, "SNMP regolare")
        self.assertContains(response, "SNMP muto da 10 gg")
        self.assertContains(response, "Non monitorato")

    def test_filters(self):
        scoperti = self.page(copertura="scoperti", rows=96)
        self.assertContains(scoperti, "PC scoperto")
        self.assertNotContains(scoperti, "Server regolare")
        problemi = self.page(copertura="problemi", rows=96)
        self.assertContains(problemi, "Switch muto")
        self.assertNotContains(problemi, "Server regolare")
        self.assertNotContains(problemi, "PC scoperto")


class AssetPageIntegrationTests(TestCase):
    """Fasi 2, 3 e 5: SOC e SNMP nella scheda asset."""

    def setUp(self):
        from security.models import (
            SecurityAlert, SecurityEventRecord, SecuritySource, SecurityVulnerabilityFinding,
        )

        self.user = get_user_model().objects.create_superuser("page-demo", "page@example.test", "synthetic-only")
        self.client.force_login(self.user)
        self.asset = Asset.objects.create(asset_tag="DEMO-SRV", name="SRV-DEMO", asset_type="SERVER",
                                          serial_number="SN-VECCHIO", manufacturer="")
        source = SecuritySource.objects.create(name="Fonte demo", source_type="manual")
        device = SecurityAsset.objects.create(source=source, hostname="srv-demo", hub_asset=self.asset)
        event = SecurityEventRecord.objects.create(source=source, asset=device, event_type="login_failed",
                                                   severity="high", fingerprint="f", dedup_hash="e1")
        SecurityAlert.objects.create(source=source, event=event, title="Accessi falliti ripetuti",
                                     severity="critical", status="open", dedup_hash="a1")
        SecurityVulnerabilityFinding.objects.create(source=source, asset=device, cve="CVE-2099-0001",
                                                    affected_product="Prodotto demo", cvss=9.8,
                                                    severity="critical", status="open", dedup_hash="v1")
        DispositivoSNMP.objects.create(nome="srv snmp", host="192.0.2.60", asset=self.asset, snmp_stato="ERROR",
                                       snmp_ultimo_controllo=timezone.now(), matricola="SN-LETTO",
                                       produttore="Produttore demo")

    def page(self):
        return self.client.get(reverse("assets:asset_view", args=[self.asset.pk]))

    def test_soc_vulnerabilities_and_events_on_asset(self):
        response = self.page()
        self.assertContains(response, "CVE-2099-0001")
        self.assertContains(response, "Vulnerabilità aperte")
        self.assertContains(response, "Ultimi eventi di sicurezza")

    def test_timeline_has_monitoring_and_soc_facts(self):
        response = self.page()
        self.assertContains(response, "non risponde al monitoraggio")
        self.assertContains(response, "Alert SOC: Accessi falliti ripetuti")
        self.assertContains(response, "Vulnerabilità critica CVE-2099-0001")

    def test_snmp_identity_diff_and_apply(self):
        response = self.page()
        self.assertContains(response, "Il monitoraggio legge dati diversi dall")
        self.assertContains(response, "SN-LETTO")
        url = reverse("assets:asset_view", args=[self.asset.pk])
        # Un valore non letto via SNMP viene rifiutato.
        self.client.post(url, {"action": "apply_snmp_identity", "field": "serial_number", "value": "INVENTATO"})
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.serial_number, "SN-VECCHIO")
        self.client.post(url, {"action": "apply_snmp_identity", "field": "serial_number", "value": "SN-LETTO"})
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.serial_number, "SN-LETTO")

    def test_unlinked_asset_shows_soc_candidate(self):
        other = Asset.objects.create(asset_tag="DEMO-PC9", name="PC-NONCOLLEGATO", asset_type="PC")
        SecurityAsset.objects.create(hostname="pc-noncollegato.dominio.local")
        response = self.client.get(reverse("assets:asset_view", args=[other.pk]))
        self.assertContains(response, "Possibili dispositivi SOC per questo asset")
        self.assertContains(response, "pc-noncollegato.dominio.local")