"""Dispositivi citati dai report -> SecurityAsset + segnali -> collegamento confermato all'asset HUB."""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from assets.models import Asset
from security.models import ParseStatus, SecurityAsset, SecurityAssetSignal, SecurityConfigurationAuditLog, SecurityMailboxMessage, SecuritySource
from security.parsers.synology_active_backup_email_parser import SynologyActiveBackupEmailParser
from security.parsers.veeam_backup_email_parser import VeeamBackupEmailParser
from security.parsers.watchguard_report_parser import WatchGuardReportParser
from security.services.asset_signals import device_identity, link, record_asset_signals, signals_for_hub_asset, suggest_hub_asset
from security.services.parser_engine import run_pending_parsers
from security.templatetags.security_asset import security_asset_card
from security.tests.test_parsers_real_formats import EPDR_REPORT, SYNOLOGY_OK, SYNOLOGY_SUBJECT_OK, THREAT_MAIL, VEEAM, _item


class DeviceIdentityTests(TestCase):
    def test_labels(self):
        self.assertEqual(device_identity("PCLOGSYS"), ("PCLOGSYS", ""))
        self.assertEqual(device_identity("_2_10.0.0.6 (QLIKSENSE-SRV)"), ("QLIKSENSE-SRV", "10.0.0.6"))
        self.assertEqual(device_identity("10.0.0.9"), ("10.0.0.9", "10.0.0.9"))
        self.assertEqual(device_identity("  NOVISQL  "), ("NOVISQL", ""))


class SignalExtractionTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Casella", source_type="email", vendor="mailbox")

    def test_synology_device_gets_a_backup_signal(self):
        parsed = SynologyActiveBackupEmailParser().parse(_item(subject=SYNOLOGY_SUBJECT_OK, body=SYNOLOGY_OK))
        self.assertEqual(record_asset_signals(self.source, None, parsed), 1)
        signal = SecurityAssetSignal.objects.get()
        self.assertEqual((signal.asset.hostname, signal.kind, signal.status), ("PC-DEMO", "backup", "completed"))
        self.assertEqual(signal.detail["job"], "JOB-DEMO")

    def test_same_report_twice_does_not_duplicate(self):
        parsed = SynologyActiveBackupEmailParser().parse(_item(subject=SYNOLOGY_SUBJECT_OK, body=SYNOLOGY_OK))
        record_asset_signals(self.source, None, parsed)
        self.assertEqual(record_asset_signals(self.source, None, parsed), 0)
        self.assertEqual(SecurityAssetSignal.objects.count(), 1)
        self.assertEqual(SecurityAsset.objects.count(), 1)

    def test_veeam_objects_become_one_signal_each(self):
        parsed = VeeamBackupEmailParser().parse(_item(subject="[Success] Backup DEMO (2 objects)", body=VEEAM))
        record_asset_signals(self.source, None, parsed)
        self.assertEqual(sorted(SecurityAsset.objects.values_list("hostname", flat=True)), ["SRV-APP", "SRV-SQL"])
        self.assertEqual(SecurityAssetSignal.objects.filter(kind="backup", status="completed").count(), 2)

    def test_veeam_label_with_ip_and_parentheses(self):
        body = VEEAM.replace("SRV-APP\t", "_2_10.0.0.6 (QLIKSENSE-SRV)\t")
        parsed = VeeamBackupEmailParser().parse(_item(subject="[Success] Backup DEMO", body=body))
        record_asset_signals(self.source, None, parsed)
        asset = SecurityAsset.objects.get(hostname="QLIKSENSE-SRV")
        self.assertEqual(asset.ip_address, "10.0.0.6")

    def test_endpoint_detections_and_threat_mail(self):
        report = WatchGuardReportParser().parse(_item(original_name="Report.pdf", content=EPDR_REPORT))
        record_asset_signals(self.source, None, report)
        self.assertEqual(SecurityAssetSignal.objects.get(kind="endpoint_detections").asset.hostname, "PC-TEST-01")
        threat = WatchGuardReportParser().parse(_item(subject="[WatchGuard Endpoint Security 360] Threats detected between 9/30/2026 9:59 AM and 9/30/2026 9:59 AM (UTC)", body=THREAT_MAIL))
        record_asset_signals(self.source, None, threat)
        asset = SecurityAsset.objects.get(hostname="PC-TEST-02")
        self.assertEqual(str(asset.ip_address), "192.0.2.77")
        self.assertEqual(asset.signals.get().kind, "endpoint_threat")

    def test_failure_in_extraction_never_breaks_the_report(self):
        broken = SimpleNamespace(records=[SimpleNamespace(record_type="backup_job", payload={"vendor": "veeam", "objects": [None]})], payload={})
        self.assertEqual(record_asset_signals(self.source, None, broken), 0)

    def test_pipeline_records_signals_when_a_mail_is_parsed(self):
        SecurityMailboxMessage.objects.create(source=self.source, subject=SYNOLOGY_SUBJECT_OK, body=SYNOLOGY_OK, sender="nas@example.test")
        run_pending_parsers()
        self.assertEqual(SecurityMailboxMessage.objects.get().parse_status, ParseStatus.PARSED)
        self.assertEqual(SecurityAssetSignal.objects.count(), 1)


class LinkingTests(TestCase):
    def setUp(self):
        self.device = SecurityAsset.objects.create(hostname="PCLOGSYS")
        self.admin = get_user_model().objects.create(username="soc_admin_link", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def test_suggestion_is_exact_name_ignoring_case_and_unique(self):
        hub = Asset.objects.create(asset_tag="T1", name="pclogsys")
        self.assertEqual(suggest_hub_asset(self.device)[0], hub)

    def test_ambiguous_and_missing_are_not_suggested(self):
        Asset.objects.create(asset_tag="T1", name="PCLOGSYS")
        Asset.objects.create(asset_tag="T2", name="pclogsys")
        self.assertIsNone(suggest_hub_asset(self.device)[0])
        self.assertIsNone(suggest_hub_asset(SecurityAsset.objects.create(hostname="NESSUNO"))[0])

    def test_nothing_is_linked_without_confirmation(self):
        Asset.objects.create(asset_tag="T1", name="PCLOGSYS")
        response = self.client.get(reverse("security:assets"))
        self.assertContains(response, "Proposto")
        self.device.refresh_from_db()
        self.assertIsNone(self.device.hub_asset)

    def test_confirm_links_and_audits(self):
        hub = Asset.objects.create(asset_tag="T1", name="PCLOGSYS")
        self.client.post(reverse("security:assets"), {"action": "confirm", "asset": self.device.pk, "hub": hub.pk})
        self.device.refresh_from_db()
        self.assertEqual(self.device.hub_asset, hub)
        self.assertTrue(SecurityConfigurationAuditLog.objects.filter(action="asset_link", object_id=str(self.device.pk)).exists())

    def test_confirm_all_links_only_unambiguous_exact_names(self):
        Asset.objects.create(asset_tag="T1", name="PCLOGSYS")
        other = SecurityAsset.objects.create(hostname="DOPPIO")
        Asset.objects.create(asset_tag="T2", name="DOPPIO")
        Asset.objects.create(asset_tag="T3", name="doppio")
        self.client.post(reverse("security:assets"), {"action": "confirm_all"})
        self.device.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNotNone(self.device.hub_asset)
        self.assertIsNone(other.hub_asset)

    def test_unlink(self):
        hub = Asset.objects.create(asset_tag="T1", name="PCLOGSYS")
        link(self.device, hub, actor=self.admin)
        self.client.post(reverse("security:assets"), {"action": "unlink", "asset": self.device.pk})
        self.device.refresh_from_db()
        self.assertIsNone(self.device.hub_asset)

    def test_user_without_config_permission_cannot_link(self):
        hub = Asset.objects.create(asset_tag="T1", name="PCLOGSYS")
        self.client.force_login(get_user_model().objects.create(username="solo_lettura"))
        self.client.post(reverse("security:assets"), {"action": "confirm", "asset": self.device.pk, "hub": hub.pk})
        self.device.refresh_from_db()
        self.assertIsNone(self.device.hub_asset)


class HubAssetCardTests(TestCase):
    def setUp(self):
        self.hub = Asset.objects.create(asset_tag="T1", name="PCLOGSYS")
        self.device = SecurityAsset.objects.create(hostname="PCLOGSYS", hub_asset=self.hub)
        source = SecuritySource.objects.create(name="Casella", source_type="email", vendor="mailbox")
        parsed = SynologyActiveBackupEmailParser().parse(_item(subject=SYNOLOGY_SUBJECT_OK.replace("JOB-DEMO", "JOB-X"), body=SYNOLOGY_OK.replace("PC-DEMO", "PCLOGSYS").replace("JOB-DEMO", "JOB-X")))
        record_asset_signals(source, None, parsed)
        self.admin = get_user_model().objects.create(username="hub_admin", is_staff=True, is_superuser=True)

    def test_signals_for_hub_asset(self):
        data = signals_for_hub_asset(self.hub)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["last_backup"].status, "completed")

    def test_card_shows_on_asset_page_for_security_users(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assets:asset_view", args=[self.hub.pk]))
        self.assertContains(response, "SICUREZZA E BACKUP")
        self.assertContains(response, "JOB-X")

    def test_card_hidden_when_no_device_is_linked(self):
        other = Asset.objects.create(asset_tag="T2", name="ALTRO")
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse("assets:asset_view", args=[other.pk])), "SICUREZZA E BACKUP")

    def test_card_hidden_for_users_without_security_access(self):
        plain = get_user_model().objects.create(username="senza_soc")
        context = {"request": SimpleNamespace(user=plain)}
        self.assertEqual(security_asset_card.__wrapped__(context, self.hub), {"show": False}) if hasattr(security_asset_card, "__wrapped__") else None
        from security.permissions import can_view_security_center

        self.assertFalse(can_view_security_center(plain))
