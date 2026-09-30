"""Storico accessi VPN: parser (CSV e testo da PDF) -> SecurityVpnAccess -> KPI -> pagina."""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import ParseStatus, SecurityKpiSnapshot, SecurityMailboxMessage, SecuritySource, SecurityVpnAccess
from security.parsers.watchguard_report_parser import WatchGuardReportParser
from security.services.kpi_service import build_daily_kpi_snapshots
from security.services.parser_engine import run_pending_parsers
from security.services.vpn_history import persist_vpn_accesses

ALLOWED_CSV = (
    "User,Source IP,Login Time,Logout Time,Duration,Method\n"
    "mario.rossi,203.0.113.10,2026-09-29 08:01:00,2026-09-29 09:31:00,01:30:00,SSLVPN\n"
    "anna.verdi,203.0.113.11,2026-09-29 08:05:00,2026-09-29 08:06:00,00:01:00,SSLVPN\n"
    "mario.rossi,203.0.113.10,2026-09-29 14:00:00,2026-09-29 15:00:00,01:00:00,SSLVPN\n"
)
DENIED_CSV = (
    "User,Source IP,Login Time,Reason\n"
    "admin,198.51.100.7,2026-09-29 03:00:00,Authentication of SSLVPN user [admin] was rejected\n"
    "admin,198.51.100.7,2026-09-29 03:01:00,Authentication of SSLVPN user [admin] was rejected\n"
)
PDF_TEXT = (
    "Firebox Authentication Allowed\n"
    "User Source IP Login Time Logout Time Duration\n"
    "mario.rossi 203.0.113.10 2026-09-29 08:01:00 2026-09-29 09:31:00 01:30:00\n"
    "anna.verdi 203.0.113.11 2026-09-29 08:05:00 2026-09-29 08:06:00 00:01:00\n"
)


def _item(name, content):
    return SimpleNamespace(original_name=name, subject=name, content=content, body="", received_at=None, source=None)


class VpnParserTests(TestCase):
    def test_csv_emits_one_vpn_record_per_row(self):
        report = WatchGuardReportParser().parse(_item("FB1_Authentication_Allowed.csv", ALLOWED_CSV))
        rows = [r for r in report.records if r.record_type == "vpn_access"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].payload["user"], "mario.rossi")
        self.assertEqual(rows[0].payload["duration_seconds"], 5400)

    def test_pdf_text_without_csv_header_is_still_read(self):
        report = WatchGuardReportParser().parse(_item("Firebox Authentication Allowed.pdf", PDF_TEXT))
        rows = [r.payload for r in report.records if r.record_type == "vpn_access"]
        self.assertEqual([r["user"] for r in rows], ["mario.rossi", "anna.verdi"])
        self.assertEqual(rows[0]["source_ip"], "203.0.113.10")
        self.assertEqual(rows[0]["duration_seconds"], 5400)
        self.assertTrue(any("testo del report" in w for w in report.payload["parse_warnings"]))

    def test_non_vpn_report_emits_no_vpn_records(self):
        report = WatchGuardReportParser().parse(_item("Dimension Executive Summary", "Botnet Detection 12"))
        self.assertFalse([r for r in report.records if r.record_type == "vpn_access"])


class VpnHistoryPersistenceTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Firewall", source_type="watchguard_epdr", vendor="WatchGuard")

    def _payloads(self, csv_text, action):
        name = "FB1_Authentication_%s.csv" % action.capitalize()
        report = WatchGuardReportParser().parse(_item(name, csv_text))
        return [r.payload for r in report.records if r.record_type == "vpn_access"]

    def test_persist_dedups_across_reruns(self):
        payloads = self._payloads(ALLOWED_CSV, "allowed")
        self.assertEqual(persist_vpn_accesses(self.source, None, payloads), 3)
        self.assertEqual(persist_vpn_accesses(self.source, None, payloads), 0)
        self.assertEqual(SecurityVpnAccess.objects.count(), 3)

    def test_persist_dedups_inside_one_batch(self):
        payloads = self._payloads(ALLOWED_CSV, "allowed")
        self.assertEqual(persist_vpn_accesses(self.source, None, payloads + payloads), 3)

    def test_engine_saves_history_from_mailbox_message(self):
        SecurityMailboxMessage.objects.create(
            source=self.source, external_id="m1", subject="FB1 Authentication Allowed", sender="noreply@watchguard.com",
            body=ALLOWED_CSV, received_at=timezone.now(), parse_status=ParseStatus.PENDING,
        )
        run_pending_parsers()
        self.assertEqual(SecurityVpnAccess.objects.filter(action="allowed").count(), 3)

    def test_daily_kpis_use_history(self):
        persist_vpn_accesses(self.source, None, self._payloads(ALLOWED_CSV, "allowed") + self._payloads(DENIED_CSV, "denied"))
        build_daily_kpi_snapshots(timezone.datetime(2026, 9, 29).date())
        values = {s.name: s.value for s in SecurityKpiSnapshot.objects.filter(source=self.source)}
        self.assertEqual(values["vpn_access_allowed"], 3)
        self.assertEqual(values["vpn_access_denied"], 2)
        self.assertEqual(values["vpn_unique_users"], 3)
        self.assertEqual(values["vpn_unique_source_ips"], 3)
        self.assertEqual(values["vpn_session_max_seconds"], 5400)


class SocDashboardAndKpiTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("soc_dash", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(user)

    def test_dashboard_shows_data_flows_and_vpn_panels(self):
        response = self.client.get(reverse("security:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Flussi dati")
        self.assertContains(response, "Accessi VPN")
        self.assertIn("source_rows", response.context)

    def test_metric_display_formats_by_unit(self):
        from security.templatetags.security_i18n import metric_display

        self.assertEqual(metric_display(SimpleNamespace(name="vpn_session_avg_seconds", value=5400.0)), "1:30:00")
        self.assertEqual(metric_display(SimpleNamespace(name="backup_transferred_total_gb", value=1234.5)), "1.234,50 GB")
        self.assertEqual(metric_display(SimpleNamespace(name="vpn_access_allowed", value=1200.0)), "1.200")


class VpnFindingsTests(TestCase):
    def test_burst_then_success_is_flagged_high(self):
        from security.services.vpn_history import vpn_findings

        source = SecuritySource.objects.create(name="Firewall", source_type="watchguard_epdr", vendor="WatchGuard")
        denied = "User,Source IP,Login Time\n" + "".join(f"admin,198.51.100.7,2026-09-29 03:{m:02d}:00\n" for m in range(12))
        allowed = "User,Source IP,Login Time,Logout Time,Duration\nadmin,198.51.100.7,2026-09-29 03:30:00,2026-09-29 04:00:00,00:30:00\n"
        rows = []
        for name, text in (("FB1_Authentication_Denied.csv", denied), ("FB1_Authentication_Allowed.csv", allowed)):
            rows += [r.payload for r in WatchGuardReportParser().parse(_item(name, text)).records if r.record_type == "vpn_access"]
        persist_vpn_accesses(source, None, rows)
        findings = vpn_findings(SecurityVpnAccess.objects.all())
        self.assertEqual(findings[0]["level"], "high")
        self.assertIn("dopo 12 rifiuti", findings[0]["title"])


class VpnHistoryPageTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("vpn_admin", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(user)
        source = SecuritySource.objects.create(name="Firewall", source_type="watchguard_epdr", vendor="WatchGuard")
        report = WatchGuardReportParser()
        rows = []
        for name, text in (("FB1_Authentication_Allowed.csv", ALLOWED_CSV), ("FB1_Authentication_Denied.csv", DENIED_CSV)):
            rows += [r.payload for r in report.parse(_item(name, text)).records if r.record_type == "vpn_access"]
        persist_vpn_accesses(source, None, rows)

    def test_page_lists_and_filters(self):
        response = self.client.get(reverse("security:vpn_history"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["summary"]["total"], 5)
        self.assertContains(response, "mario.rossi")
        filtered = self.client.get(reverse("security:vpn_history"), {"action": "denied", "user": "admin"})
        self.assertEqual(filtered.context["page"].paginator.count, 2)
        self.assertNotContains(filtered, "mario.rossi</td>")
        self.assertFalse(response.context["daily"]["empty"])
        self.assertEqual(len(response.context["hours"]), 24)
        by_day = self.client.get(reverse("security:vpn_history"), {"from": "2026-09-30"})
        self.assertEqual(by_day.context["page"].paginator.count, 0)
