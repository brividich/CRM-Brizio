"""Pagine SOC rifatte: KPI per area con dettaglio, Stato elaborazione, Accessi VPN, Casella (cartelle e filtri)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord, ParseStatus, SecurityKpiSnapshot, SecurityMailboxMessage, SecurityMailboxSource, SecurityReport, SecurityReportMetric,
    SecuritySource, SecurityVpnAccess,
)
from security.services.kpi_dashboard import domain_for, is_last_value, kpi_detail, kpi_overview
from security.services.mailbox_setup import build_subject_filters, recommended_subject_filters, subject_filter_state


class _Admin(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create(username="ux_admin", is_staff=True, is_superuser=True))
        self.source = SecuritySource.objects.create(name="Casella", source_type="email", vendor="mailbox")
        self.today = timezone.localdate()


class KpiDashboardTests(_Admin):
    def _report(self, day, **metrics):
        report = SecurityReport.objects.create(source=self.source, report_type="watchguard_epdr_executive_report", title="EPDR", report_date=day, parser_name="p")
        for name, value in metrics.items():
            SecurityReportMetric.objects.create(report=report, name=name, value=value)
        return report

    def test_domains_and_kinds(self):
        self.assertEqual(domain_for("backup_failed_count"), "backup")
        self.assertEqual(domain_for("vpn_access_denied"), "vpn")
        self.assertEqual(domain_for("watchguard_epdr_protected_endpoints"), "endpoint")
        self.assertEqual(domain_for("watchguard_botnet_blocked_count"), "firewall")
        self.assertEqual(domain_for("defender_unique_cves"), "vulns")
        self.assertEqual(domain_for("possible_sender_spoofing"), "events")
        self.assertTrue(is_last_value("watchguard_epdr_protected_endpoints"))
        self.assertFalse(is_last_value("backup_failed_count"))

    def test_counts_are_summed_states_take_the_last_value_and_delta_compares_periods(self):
        self._report(self.today, backup_failed_count=2, watchguard_epdr_protected_endpoints=85)
        self._report(self.today - timedelta(days=1), backup_failed_count=1, watchguard_epdr_protected_endpoints=80)
        self._report(self.today - timedelta(days=8), backup_failed_count=5)
        tiles = {t["name"]: t for domain in kpi_overview(self.today, 7) for t in domain["tiles"]}
        self.assertEqual(tiles["backup_failed_count"]["value"], 3)
        self.assertEqual(tiles["backup_failed_count"]["delta"], -2)
        self.assertEqual(tiles["watchguard_epdr_protected_endpoints"]["value"], 85)
        self.assertTrue(tiles["backup_failed_count"]["spark"])

    def test_snapshot_wins_over_report_metric_for_the_same_day(self):
        self._report(self.today, vpn_access_allowed=3)
        SecurityKpiSnapshot.objects.create(source=self.source, snapshot_date=self.today, name="vpn_access_allowed", value=10)
        tiles = {t["name"]: t for domain in kpi_overview(self.today, 7) for t in domain["tiles"]}
        self.assertEqual(tiles["vpn_access_allowed"]["value"], 10)

    def test_page_and_detail_with_origin_reports(self):
        report = self._report(self.today, backup_failed_count=2)
        page = self.client.get(reverse("security:kpis"), {"giorni": 30})
        self.assertContains(page, reverse("security:kpi_detail", args=["backup_failed_count"]))
        self.assertContains(page, "Backup")
        detail = self.client.get(reverse("security:kpi_detail", args=["backup_failed_count"]), {"giorni": 7})
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Da dove arriva il numero")
        self.assertContains(detail, report.title)
        self.assertEqual(len(detail.context["d"]["rows"]), 7)

    def test_backup_detail_lists_jobs(self):
        BackupJobRecord.objects.create(source=self.source, job_name="JOB-X", status="failed", started_at=timezone.now(), dedup_hash="x")
        SecurityKpiSnapshot.objects.create(source=self.source, snapshot_date=self.today, name="backup_failed_count", value=1)
        data = kpi_detail("backup_failed_count", self.today, 7)
        self.assertEqual([j.job_name for j in data["backups"]], ["JOB-X"])

    def test_bad_period_falls_back(self):
        self.assertEqual(self.client.get(reverse("security:kpis"), {"giorni": "abc", "al": "x"}).status_code, 200)


class ProcessingPageTests(_Admin):
    def test_explains_steps_and_lists_failures(self):
        SecurityMailboxMessage.objects.create(source=self.source, subject="Report rotto", body="x", parse_status=ParseStatus.FAILED,
                                              raw_payload={"parser_error": "boom", "parser_name": "watchguard_report_parser"})
        response = self.client.get(reverse("security:pipeline"))
        self.assertContains(response, "Lettura delle caselle")
        self.assertContains(response, "Riconoscimento dei report")
        self.assertContains(response, "Report rotto")
        self.assertContains(response, "boom")
        self.assertContains(response, "Esegui a mano")


class VpnDashboardTests(_Admin):
    def _access(self, days_ago, action="allowed", user="mario"):
        when = timezone.now() - timedelta(days=days_ago)
        SecurityVpnAccess.objects.create(source=self.source, action=action, username=user, source_ip="203.0.113.5", login_at=when, kind="vpn",
                                         duration_seconds=60, dedup_hash=f"{days_ago}{action}{user}{when.timestamp()}")

    def test_default_period_tiles_with_delta_and_ranking(self):
        self._access(1)
        self._access(2, "denied")
        self._access(40)
        response = self.client.get(reverse("security:vpn_history"))
        tiles = {t["key"]: t for t in response.context["tiles"]}
        self.assertEqual(tiles["total"]["value"], 2)
        self.assertEqual(tiles["total"]["delta"], 1)  # 30 giorni precedenti: 1 accesso
        self.assertEqual(response.context["top_users"][0]["share"], 100)
        self.assertEqual(response.context["days"], 30)

    def test_period_chip_and_custom_dates(self):
        self._access(10)
        self.assertEqual(self.client.get(reverse("security:vpn_history"), {"giorni": 7}).context["summary"]["total"], 0)
        start = (self.today - timedelta(days=12)).isoformat()
        response = self.client.get(reverse("security:vpn_history"), {"from": start})
        self.assertTrue(response.context["custom"])
        self.assertEqual(response.context["summary"]["total"], 1)


class MailboxSettingsTests(_Admin):
    def setUp(self):
        super().setUp()
        self.mailbox = SecurityMailboxSource.objects.create(name="Personale", code="personale", source_type="graph", mailbox_address="x@example.test")
        self.url = reverse("security:admin_mailbox_source_detail", args=["personale"])

    def test_presets_round_trip(self):
        text = build_subject_filters(["synology", "veeam"], "Report notturno")
        self.mailbox.subject_include_text = text
        active, extra = subject_filter_state(self.mailbox)
        self.assertEqual(active, ["synology", "veeam"])
        self.assertEqual(extra, ["Report notturno"])
        self.assertEqual(build_subject_filters(["watchguard", "synology", "veeam", "defender"], ""), "\n".join(recommended_subject_filters()))

    def test_save_filters_from_page(self):
        self.client.post(self.url, {"action": "save_filters", "presets": ["watchguard"], "extra_subjects": "Scheduled", "subject_exclude_text": "RE:", "sender_allowlist_text": ""})
        self.mailbox.refresh_from_db()
        self.assertIn("Firebox", self.mailbox.subject_include_text)
        self.assertIn("Scheduled", self.mailbox.subject_include_text)
        self.assertEqual(self.mailbox.subject_exclude_text, "RE:")

    def test_load_and_save_folders(self):
        tree = [{"id": "AAA", "name": "Posta in arrivo", "path": "Posta in arrivo", "depth": 0, "total": 10, "outgoing": False},
                {"id": "BBB", "name": "Report", "path": "Posta in arrivo/Report", "depth": 1, "total": 3, "outgoing": False}]
        with mock.patch("security.services.mailbox_providers.GraphMailboxProvider.folder_tree", return_value=tree):
            response = self.client.post(self.url, {"action": "load_folders"})
        self.assertContains(response, "Posta in arrivo/Report")
        self.client.post(self.url, {"action": "save_folders", "mode": "selected", "folder": ["BBB|Posta in arrivo/Report"]})
        self.mailbox.refresh_from_db()
        self.assertEqual(self.mailbox.folders, [{"id": "BBB", "path": "Posta in arrivo/Report"}])
        self.client.post(self.url, {"action": "save_folders", "mode": "all"})
        self.mailbox.refresh_from_db()
        self.assertEqual(self.mailbox.folders, [])

    def test_folder_load_error_is_shown(self):
        with mock.patch("security.services.mailbox_providers.GraphMailboxProvider.folder_tree", side_effect=RuntimeError("Missing GRAPH_TENANT_ID")):
            response = self.client.post(self.url, {"action": "load_folders"})
        self.assertContains(response, "Cartelle non leggibili")

    def test_general_and_content_sections_save(self):
        self.client.post(self.url, {"action": "save", "name": "Personale", "enabled": "on", "source_type": "graph", "mailbox_address": "y@example.test",
                                    "description": "", "expected_every_hours": 12, "max_messages_per_run": 200})
        self.client.post(self.url, {"action": "save_content", "process_attachments": "on", "attachment_extensions": "csv,pdf,zip"})
        self.mailbox.refresh_from_db()
        self.assertEqual((self.mailbox.mailbox_address, self.mailbox.max_messages_per_run), ("y@example.test", 200))
        self.assertEqual(self.mailbox.attachment_extensions, "csv,pdf,zip")
        self.assertFalse(self.mailbox.process_email_body)

    def test_provider_reads_only_chosen_folders(self):
        from security.services.mailbox_providers import GraphMailboxProvider

        self.mailbox.folders = [{"id": "BBB", "path": "Report"}]
        provider = GraphMailboxProvider()
        page = {"value": [{"id": "1", "parentFolderId": "BBB"}, {"id": "2", "parentFolderId": "CCC"}]}
        with mock.patch.object(provider, "_folder_scope", return_value=(None, set())), \
                mock.patch.object(provider, "_folder_subtree", return_value={"BBB"}), \
                mock.patch("security.services.mailbox_providers._request_json", return_value=page):
            items = provider._get_messages("token", self.mailbox, 50)
        self.assertEqual([item["id"] for item in items], ["1"])
