"""Parser sui formati REALI dei report (WatchGuard, Synology, Veeam).

Le fixture sono sintetiche (nomi, IP e cifre inventati) ma ricalcano la struttura di quello
che arriva davvero: PDF con una cella per riga, mail Synology in italiano con apostrofo
tipografico, mail Veeam con tabelle a tabulazioni, CSV Authentication con colonna `method`.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from security.parsers.load import *  # noqa: F401,F403
from security.parsers import parser_registry
from security.parsers.synology_active_backup_email_parser import SynologyActiveBackupEmailParser
from security.parsers.veeam_backup_email_parser import VeeamBackupEmailParser
from security.parsers.watchguard import routing
from security.parsers.watchguard_report_parser import WatchGuardReportParser


def _item(subject="", body="", content="", original_name="", pk=1):
    return SimpleNamespace(subject=subject, body=body, content=content, original_name=original_name, sender="", received_at=None, source=None, pk=pk)


def _wg(name, content="", subject="", body=""):
    return WatchGuardReportParser().parse(_item(subject=subject, body=body, content=content, original_name=name))


AUTH_ALLOWED = (
    "user,ip,login,logout,duration,quota,method\n"
    + "".join(f"svc.fw,192.0.2.10,2026-09-29 00:{m:02d}:05,2026-09-29 00:{m:02d}:40,0:35,,Firewall\n" for m in range(30))
    + "mario.rossi,203.0.113.44,2026-09-29 08:00:00,2026-09-29 09:30:00,1:30:00,,SSLVPN\n"
)
AUTH_DENIED = "user,ip,login,reason\nghost,198.51.100.9,2026-09-29 16:30:55,\"Authentication of SSLVPN user [ghost@corp.local] from 198.51.100.9 was rejected, user doesn't exist\"\n"

EXEC_SUMMARY = """Executive Summary Report
From
2026-09-29 00:00 (Europe/Berlin)
To
2026-09-29 23:59 (Europe/Berlin)
Device(s)
TestFW
(192.0.2.1,192.0.2.2) SERIAL1, SERIAL2
License
Expires on 2027-12-31
Malware Attacks
Frequency   Daily 12.6K   Hourly 523   Every Minute 9
Total Scanned  12.5K
Gateway AntiVirus
12.1K
Scanned
2
Detected and Blocked
IntelligentAV
179
Scanned
0
Detected and Blocked
Advanced Malware
268
Scanned
0
Detected and Blocked
Zero-Day Malware
268
Scanned
0
Detected and Blocked
Network Attacks
Frequency   Daily 38M   Hourly 1.58M   Every Minute 26.4K
Total Scanned  37.9M
Intrusion Prevention Service
18.7M
Scanned
3
Detected
3
Prevented
Reputation Enabled Defense
0
Scanned
0
Detected and Blocked
Botnet Detection
7.56M
Scanned
2.84K
Detected and Blocked
"""

EPDR_REPORT = """Limitless Visibility, Absolute Control
EXECUTIVE REPORT
All computers
Created on:
Tuesday, September 29, 2026 | 10:00 AM - Wednesday, September 30, 2026 | 10:00 AM
CONTENTS
LICENSE STATUS ...................................................
NETWORK SECURITY STATUS ...........................................
LICENSE STATUS
Contracted licenses:
90 (WatchGuard Endpoint Security 360)
Used licenses:
86 (96 %)
Expiration date:
5/27/2027
NETWORK SECURITY STATUS
Enabled
85 (92.4 %)
No license
6 (6.5 %)
Protection with errors
1 (1.1 %)
ONLINE COMPUTERS:
Last 30 days 88 (96 %)
More than 30 days ago 4 (4 %)
UP-TO-DATE PROTECTION:
Updated 69 (75 %)
Outdated 23 (25 %)
UP-TO-DATE KNOWLEDGE:
Updated 89 (97 %)
Outdated 3 (3 %)
5 computers have been discovered that are not being managed by WatchGuard Endpoint Security 360.
DETECTIONS
PUPs
0 (0.0 %)
Exploits
0 (0.0 %)
Malware
2 (0.1 %)
Trusted programs
3,817 (100.0 %)
TOP 10 COMPUTERS WITH MOST DETECTIONS:
Computer
Group
Detections
First detection
Last detection
PC-TEST-01
All
4
9/29/2026 12:35 PM
9/29/2026 12:35 PM
Executive Report | 3
MALWARE ACTIVITY:
Phishing: 0
Blocked devices: 52
Malware URLs: 4
Critical
7 (7.6 %)
High
29 (31.5 %)
Medium
11 (12.0 %)
No risk
45 (48.9 %)
RISKS
DETECTED RISKS:
Risk
Computers
Risk level
Out-of-date protection
28
High
No protection
7
Critical
TOP 10 COMPUTERS AT RISK:
Computer
Risk level
"""

THREAT_MAIL = """Hello,
The following threats have been detected between 9/30/2026 9:59 AM and 9/30/2026 9:59 AM (UTC)
1 DEVICES BLOCKED ON 1 COMPUTER
AFFECTED COMPUTER INFORMATION:
Name: PC-TEST-02
IP address: 192.0.2.77
Group: All
Sincerely,
The WatchGuard Team.
"""

SYNOLOGY_OK = """L'attività di backup JOB-DEMO su NAS-DEMO è stata completata.
Ora d’inizio: 17/06/2026 10:00
Ora di fine: 17/06/2026 10:01
Dimensioni trasferite: 522.6 MB
Elenco dispositivi: PC-DEMO
Da NAS-DEMO
"""
SYNOLOGY_SUBJECT_OK = "NAS Active Backup for Business - attività di backup JOB-DEMO su NAS-DEMO completata"

VEEAM = (
    "Backup job: Backup DEMO - SQL - APP\n"
    "Created by SRV-VEEAM\\demo at 30/07/2024 16:24.\n"
    "Success\n"
    "2 of 2 VMs processed\n"
    "martedì 29 settembre 2026 23:30:12\n"
    "Success\t2\tStart time\t23:30:12\tTotal size\t770 GB\tBackup size\t12,2 GB\n"
    "Warning\t0\tEnd time\t00:21:13\tData read\t32 GB\tDedupe\t1,1x\n"
    "Error\t0\tDuration\t0:51:01 \tTransferred\t12,1 GB\tCompression\t2,4x\n"
    "Details\n"
    "Name\tStatus\tStart time\tEnd time\tSize\tRead\tTransferred\tDuration\tDetails\n"
    "SRV-SQL\tSuccess\t23:32:00\t23:50:25\t90 GB\t9,8 GB\t3,1 GB\t0:18:24\n"
    "SRV-APP\tSuccess\t23:40:30\t00:20:23\t180 GB\t6,6 GB\t2,1 GB\t0:39:52\n"
    "Veeam Backup & Replication 13.0.1.2067\n"
)


class WatchGuardAuthenticationTests(SimpleTestCase):
    def test_firewall_logins_are_not_counted_as_vpn(self):
        report = _wg("TestFW_Authentication_Allowed_2026-09-29T00_00_to_2026-09-29T23_59.csv", AUTH_ALLOWED)
        self.assertEqual(report.metrics["watchguard_auth_allowed_total"], 31)
        self.assertEqual(report.metrics["watchguard_firewall_auth_count"], 30)
        self.assertEqual(report.metrics["watchguard_sslvpn_allowed_count"], 1)
        self.assertEqual(report.metrics["watchguard_sslvpn_short_reconnect_count"], 0)
        self.assertFalse([r for r in report.records if r.record_type == "watchguard_alert_candidate"])
        kinds = [r.payload["kind"] for r in report.records if r.record_type == "vpn_access"]
        self.assertEqual(kinds.count("firewall"), 30)
        self.assertEqual(kinds.count("vpn"), 1)

    def test_denied_reason_is_kept_and_classified_vpn(self):
        report = _wg("TestFW_Authentication_Denied_2026-09-29T00_00_to_2026-09-29T23_59.csv", AUTH_DENIED)
        row = next(r.payload for r in report.records if r.record_type == "vpn_access")
        self.assertEqual(row["kind"], "vpn")
        self.assertIn("user doesn't exist", row["reason"])
        self.assertEqual(report.metrics["watchguard_sslvpn_denied_count"], 1)

    def test_report_without_login_column_value_is_still_listed(self):
        report = _wg("x_Authentication_Allowed.csv", "user,ip,login,logout,duration,quota,method\nsvc,192.0.2.1,,2026-09-29 00:00:03,,,Firewall\n")
        row = next(r.payload for r in report.records if r.record_type == "vpn_access")
        self.assertEqual(row["logout_time"], "2026-09-29 00:00:03")


class WatchGuardPdfTests(SimpleTestCase):
    def test_executive_summary_layout(self):
        report = _wg("TestFW_Executive_Summary_2026-09-28T22_00_to_2026-09-29T21_59.pdf", EXEC_SUMMARY)
        self.assertEqual(report.report_type, "watchguard_dimension_executive_summary")
        m = report.metrics
        self.assertEqual(m["watchguard_malware_scanned_count"], 12500)
        self.assertEqual(m["watchguard_malware_detected_count"], 2)
        self.assertEqual(m["watchguard_ips_detected_count"], 3)
        self.assertEqual(m["watchguard_ips_prevented_count"], 3)
        self.assertEqual(m["watchguard_botnet_blocked_count"], 2840)
        self.assertEqual(report.payload["report_date"], "2026-09-29")  # giorno locale, non quello UTC del nome file
        self.assertEqual(report.payload["firebox_name"], "TestFW")
        types = [r.payload.get("type") for r in report.records if r.record_type == "watchguard_alert_candidate"]
        self.assertIn("watchguard_malware_blocked", types)
        self.assertNotIn("watchguard_botnet_blocked_aggregate", types)  # 2,8K/giorno e' normale

    def test_epdr_report_layout(self):
        report = _wg("Report.pdf", EPDR_REPORT)
        self.assertEqual(report.report_type, "watchguard_epdr_executive_report")
        m = report.metrics
        self.assertEqual((m["watchguard_epdr_licenses_contracted"], m["watchguard_epdr_licenses_used"]), (90, 86))
        self.assertEqual(m["watchguard_epdr_protected_endpoints"], 85)
        self.assertEqual(m["watchguard_epdr_unprotected_endpoints"], 7)
        self.assertEqual(m["watchguard_epdr_outdated_agents"], 23)
        self.assertEqual(m["watchguard_epdr_unmanaged_computers"], 5)
        self.assertEqual(m["watchguard_malware_detected_count"], 2)
        self.assertEqual(m["watchguard_epdr_blocked_devices"], 52)
        self.assertEqual(m["watchguard_epdr_risk_critical"], 7)
        self.assertEqual(report.payload["report_date"], "2026-09-30")
        alerts = {r.payload["type"] for r in report.records if r.record_type == "watchguard_alert_candidate"}
        self.assertTrue({"watchguard_epdr_unprotected_endpoints", "watchguard_epdr_unmanaged_computers", "watchguard_epdr_malware_detected"} <= alerts)

    def test_threat_mail(self):
        report = _wg("", subject="[WatchGuard Endpoint Security 360] [Acme] Threats detected between 9/30/2026 9:59 AM and 9/30/2026 9:59 AM (UTC)", body=THREAT_MAIL)
        self.assertEqual(report.report_type, "watchguard_epdr_threat_alert")
        alert = next(r.payload for r in report.records if r.record_type == "watchguard_alert_candidate")
        self.assertEqual(alert["computer"], "PC-TEST-02")
        self.assertEqual(alert["categories"], [(1, "devices blocked")])

    def test_dashboard_is_not_mistaken_for_zero_day(self):
        text = "Executive Dashboard Report\nAvailable Reports\nTop Zero-Day Malware (APT)\nTop Clients\n"
        self.assertEqual(routing.detect_report("x_Executive_Dashboard.pdf", text), routing.EXECUTIVE_DASHBOARD)

    def test_zero_day_chart_axis_is_not_read_as_hits(self):
        text = "Zero-Day Malware (APT)\nThreat ID\nHits\n0\n1\n2\n3\n4\n5\nAcme | Page 1\n"
        report = _wg("x_Zero_day_APT_Summary.pdf", text)
        self.assertEqual(report.metrics["watchguard_zero_day_apt_hits"], 0)

    def test_chart_only_pdfs_warn_instead_of_inventing_zeros(self):
        report = _wg("x_SD-WAN.pdf", "SD-WAN Status\nLINK A (eth0): Loss Rate (%)\n0 %\n1 %\nLINK B (eth3): Latency (ms)\n0 ms\n")
        self.assertEqual(report.metrics["watchguard_sdwan_links_reported"], 2)
        self.assertTrue(any("solo grafici" in w for w in report.payload["parse_warnings"]))
        self.assertNotIn("watchguard_sdwan_loss_avg", report.metrics)


class WatchGuardRoutingTests(SimpleTestCase):
    def test_synology_body_is_not_claimed_by_watchguard(self):
        item = _item(subject=SYNOLOGY_SUBJECT_OK, body=SYNOLOGY_OK)
        self.assertFalse(WatchGuardReportParser().can_parse(item))  # «Dimensioni» non e' «Dimension»
        self.assertTrue(SynologyActiveBackupEmailParser().can_parse(item))

    def test_every_sample_kind_has_exactly_one_parser(self):
        veeam = _item(subject="[Success] Backup DEMO (2 objects)", body=VEEAM)
        matches = [p.name for p in parser_registry.all() if p.can_parse(veeam)]
        self.assertEqual(matches, ["veeam_backup_email_parser"])


class SynologyRealFormatTests(SimpleTestCase):
    def test_italian_mail_with_typographic_apostrophe(self):
        report = SynologyActiveBackupEmailParser().parse(_item(subject=SYNOLOGY_SUBJECT_OK, body=SYNOLOGY_OK))
        job = report.records[0].payload
        self.assertEqual((job["job_name"], job["nas_name"], job["device_name"]), ("JOB-DEMO", "NAS-DEMO", "PC-DEMO"))
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["duration_seconds"], 60)
        self.assertAlmostEqual(job["transferred_size_gb"], 522.6 / 1024, places=4)
        self.assertTrue(job["start_time"].startswith("2026-06-17T10:00"))

    def test_not_completed_is_failed_not_completed(self):
        body = SYNOLOGY_OK.replace("è stata completata", "non è stata completata")
        report = SynologyActiveBackupEmailParser().parse(_item(subject="NAS Active Backup for Business - attività di backup JOB-DEMO su NAS-DEMO non riuscita", body=body))
        self.assertEqual(report.records[0].payload["status"], "failed")

    def test_partial_is_warning(self):
        body = SYNOLOGY_OK.replace("è stata completata", "è stata parzialmente completata")
        report = SynologyActiveBackupEmailParser().parse(_item(subject="NAS Active Backup for Business - attività di backup JOB-DEMO su NAS-DEMO", body=body))
        self.assertEqual(report.records[0].payload["status"], "warning")


class VeeamTests(SimpleTestCase):
    def test_job_summary_and_objects(self):
        report = VeeamBackupEmailParser().parse(_item(subject="[Success] Backup DEMO - SQL - APP (2 objects)", body=VEEAM))
        job = report.records[0].payload
        self.assertEqual(job["job_name"], "Backup DEMO - SQL - APP")
        self.assertEqual(job["status"], "completed")
        self.assertEqual((job["objects_processed"], job["objects_total"]), (2, 2))
        self.assertAlmostEqual(job["transferred_size_gb"], 12.1)
        self.assertAlmostEqual(job["total_size_gb"], 770.0)
        self.assertEqual(job["duration_seconds"], 51 * 60 + 1)
        self.assertEqual(len(job["objects"]), 2)
        self.assertEqual(report.metrics["backup_completed_count"], 1)

    def test_job_running_past_midnight_ends_next_day(self):
        job = VeeamBackupEmailParser().parse(_item(subject="[Success] Backup DEMO", body=VEEAM)).records[0].payload
        self.assertTrue(job["start_time"].startswith("2026-09-29T23:30"))
        self.assertTrue(job["end_time"].startswith("2026-09-30T00:21"))

    def test_warning_subject(self):
        job = VeeamBackupEmailParser().parse(_item(subject="[Warning] Backup DEMO (2 objects)", body=VEEAM)).records[0].payload
        self.assertEqual(job["status"], "warning")
