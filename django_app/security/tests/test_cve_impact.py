"""Impatto CVE sugli asset: versioni, import inventario idempotente, matching, feed mockati.

Tutto sintetico: host PC-DEMO-*, prodotti e CVE inventati (CVE-2099-*). Mai rete.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityCenterSetting,
    SecurityEventRecord,
    SecurityRemediationTicket,
    SecuritySource,
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityExternalFeedCache,
    SoftwareAlias,
    SoftwareCpeMapping,
    SoftwareInstallation,
    SoftwareInventoryImport,
    SoftwareSourceKind,
)
from security.services import cve_feeds, cve_impact, software_inventory
from security.services.versioning import compare, in_range

CSV = (
    "Report software installato\n"
    "Computer;Editore;Software;Versione;Rilevato il\n"
    "PC-DEMO-01;Igor Pavlov;7-Zip 23.01 (x64);23.01;01/10/2026\n"
    "PC-DEMO-02;Igor Pavlov;7-Zip 24.08 (x64);24.08;01/10/2026\n"
    "PC-DEMO-03;Demo Corp Inc.;DemoViewer;21H2;01/10/2026\n"
    ";Igor Pavlov;7-Zip;23.01;01/10/2026\n"
    "PC-DEMO-04;Igor Pavlov;7-Zip;;01/10/2026\n"
    "PC-DEMO-01;Igor Pavlov;7-Zip 23.01 (x64);23.01;01/10/2026\n"
).encode("utf-8")
MAP = {"hostname": "Computer", "vendor": "Editore", "product": "Software", "version": "Versione", "detected_at": "Rilevato il"}


class VersionCompareTests(SimpleTestCase):
    CASES = [
        ("23.01", "24.07", -1),
        ("24.08", "24.07", 1),
        ("10.0.19045.4651", "10.0.19045.4529", 1),
        ("10.0.19045.4651", "10.0.19045.4651", 0),
        ("2.4.1-beta", "2.4.1", -1),
        ("2.4.1-beta", "2.4.0", 1),
        ("v1.2.0", "1.2", 0),
        ("1.10", "1.9", 1),
        ("21H2", "22H2", None),
        ("abc", "1.0", None),
        ("1.1.1b", "1.1.1", None),
        ("1.1.1w", "1.1.1w", 0),
        ("1.2.3rc1", "1.2.3", -1),
    ]

    def test_compare_table(self):
        for a, b, expected in self.CASES:
            with self.subTest(a=a, b=b):
                self.assertEqual(compare(a, b), expected)

    def test_in_range(self):
        self.assertTrue(in_range("23.01", end_excluding="24.07"))
        self.assertFalse(in_range("24.07", end_excluding="24.07"))
        self.assertTrue(in_range("24.07", end_including="24.07"))
        self.assertFalse(in_range("1.0", start_including="2.0", end_excluding="3.0"))
        self.assertIsNone(in_range("21H2", end_excluding="22.0"))
        self.assertTrue(in_range("5.0"))  # nessun limite = tutte le versioni
        self.assertTrue(in_range("5.0", exact="5.0"))
        self.assertFalse(in_range("5.1", exact="5.0"))


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_cve_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def _import(self, data=CSV, name="export.csv", inventory_date=None):
        table = software_inventory.read_table(data, name)
        item = SoftwareInventoryImport.objects.create(source_kind=SoftwareSourceKind.WATCHGUARD, original_name=name, file_sha256="x",
                                                      headers=table.headers, column_map=MAP,
                                                      inventory_date=inventory_date or timezone.localdate())
        preview = software_inventory.build_preview(table, MAP)
        return software_inventory.run_import(item, preview), preview

    def _cve(self, cve_id="CVE-2099-0001", criteria=None, **kwargs):
        criteria = criteria if criteria is not None else [{"part": "a", "vendor": "7-zip", "product": "7-zip", "version": "*",
                                                           "start_including": "", "start_excluding": "", "end_including": "",
                                                           "end_excluding": "24.07", "requires_platform": False}]
        return SecurityCveRecord.objects.create(cve_id=cve_id, configurations=criteria, cvss=kwargs.pop("cvss", 7.8),
                                                severity=kwargs.pop("severity", "high"), nvd_fetched_at=timezone.now(), **kwargs)

    def _map_7zip(self):
        SoftwareCpeMapping.objects.create(vendor="igor pavlov", product="7-zip", cpe_vendor="7-zip", cpe_product="7-zip", confirmed=True)


class InventoryImportTests(_Base):
    def test_header_detection_and_suggested_mapping(self):
        table = software_inventory.read_table(CSV, "export.csv")
        self.assertEqual(table.headers[0], "Computer")
        suggested = software_inventory.suggest_mapping(table.headers)
        self.assertEqual(suggested["hostname"], "Computer")
        self.assertEqual(suggested["version"], "Versione")

    def test_watchguard_utf16_tab_export(self):
        # Formato reale dell'export WatchGuard EPDR «per PC»: UTF-16 LE con BOM, separato da tab.
        text = ("Client\tComputer type\tComputer\tName\tPublisher\tInstallation date\tVersion\r\n"
                "Demo\tWorkstation\tPC-DEMO-01\t7-Zip 23.01 (x64)\tIgor Pavlov\t2025-08-29\t23.01\r\n")
        table = software_inventory.read_table(text.encode("utf-16"), "Software_demo.csv")
        self.assertEqual(table.headers[2], "Computer")
        self.assertEqual(table.rows[0][2], "PC-DEMO-01")
        suggested = software_inventory.suggest_mapping(table.headers)
        self.assertEqual(suggested["hostname"], "Computer")  # non «Computer type»
        self.assertEqual(suggested["product"], "Name")
        self.assertEqual(suggested["vendor"], "Publisher")

    def test_preview_reports_skipped_rows_with_reason(self):
        _item, preview = self._import()
        self.assertEqual(len(preview.valid), 3)
        reasons = [reason for _n, reason in preview.skipped]
        self.assertIn("hostname vuoto", reasons)
        self.assertTrue(any("versione vuota" in r for r in reasons))
        self.assertIn("riga duplicata nel file", reasons)

    def test_normalization(self):
        self._import()
        install = SoftwareInstallation.objects.get(host="pc-demo-01")
        self.assertEqual(install.product, "7-zip")
        self.assertEqual(install.vendor, "igor pavlov")
        self.assertEqual(SoftwareInstallation.objects.get(host="pc-demo-03").vendor, "demo corp")

    def test_import_is_idempotent(self):
        self._import()
        first = SoftwareInstallation.objects.count()
        item, _ = self._import()
        self.assertEqual(SoftwareInstallation.objects.count(), first)
        self.assertEqual(item.rows_new, 0)

    def test_missing_software_marked_not_deleted(self):
        self._import()
        smaller = CSV.replace(b"PC-DEMO-02;Igor Pavlov;7-Zip 24.08 (x64);24.08;01/10/2026\n", b"PC-DEMO-02;Igor Pavlov;7-Zip 24.09;24.09;02/10/2026\n")
        item, _ = self._import(smaller)
        old = SoftwareInstallation.objects.get(host="pc-demo-02", version_raw="24.08")
        self.assertFalse(old.still_detected)
        self.assertEqual(item.rows_marked_missing, 1)
        self.assertTrue(SoftwareInstallation.objects.get(host="pc-demo-02", version_raw="24.09").still_detected)

    def test_product_names_with_numbers_are_kept(self):
        self.assertEqual(software_inventory.normalize_product("Windows 10", {}, "10.0.19045.4651"), "windows 10")
        self.assertEqual(software_inventory.normalize_product("Microsoft Office 365", {}, "16.0.1"), "microsoft office 365")
        self.assertEqual(software_inventory.normalize_product("7-Zip 23.01 (x64)", {}, "23.01"), "7-zip")
        self.assertEqual(software_inventory.normalize_product("DemoTool 5", {}, "5"), "demotool")

    def test_numeric_xlsx_version_is_skipped(self):
        table = software_inventory.ParsedTable(headers=["Computer", "Software", "Versione"], rows=[["PC-DEMO-05", "DemoApp", 2.1]])
        preview = software_inventory.build_preview(table, {"hostname": "Computer", "product": "Software", "version": "Versione"})
        self.assertEqual(preview.valid, [])
        self.assertIn("numero", preview.skipped[0][1])

    def test_malformed_csv_is_user_error(self):
        huge = b"Computer;Software;Versione\n\"" + b"x" * 200000 + b"\";a;1\n"
        with self.assertRaises(software_inventory.InventoryFileError):
            software_inventory.read_table(huge, "bad.csv")

    def test_stale_previews_are_cleaned(self):
        item = SoftwareInventoryImport.objects.create(original_name="a.csv", file_sha256="y", stored_name="")
        SoftwareInventoryImport.objects.filter(pk=item.pk).update(created_at=timezone.now() - timedelta(days=5))
        self.assertEqual(software_inventory.cleanup_stale_previews(days=2), 1)
        item.refresh_from_db()
        self.assertEqual(item.status, SoftwareInventoryImport.STATUS_FAILED)

    def test_alias_applies_on_import(self):
        SoftwareAlias.objects.create(kind=SoftwareAlias.KIND_VENDOR, raw="igor pavlov", canonical="7-zip")
        self._import()
        self.assertEqual(SoftwareInstallation.objects.get(host="pc-demo-01").vendor, "7-zip")

    def test_xlsx_reading(self):
        from io import BytesIO

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["Computer", "Software", "Versione"])
        ws.append(["PC-DEMO-09", "DemoApp", "1.2.3"])
        buffer = BytesIO()
        wb.save(buffer)
        table = software_inventory.read_table(buffer.getvalue(), "inv.xlsx")
        self.assertEqual(table.headers, ["Computer", "Software", "Versione"])
        self.assertEqual(table.rows[0][0], "PC-DEMO-09")


class MatchingTests(_Base):
    def setUp(self):
        super().setUp()
        self._import()

    def _outcomes(self, record):
        cve_impact.recompute(record)
        return {i.host: (i.outcome, i.explanation) for i in record.impacts.all()}

    def test_matching_case_table(self):
        self._map_7zip()
        outcomes = self._outcomes(self._cve())
        self.assertEqual(outcomes["pc-demo-01"][0], SecurityCveImpact.IMPACTS)
        self.assertIn("7-Zip 23.01 (x64) 23.01 installato su PC-DEMO-01; vulnerabile < 24.07; fonte: export", outcomes["pc-demo-01"][1])
        self.assertEqual(outcomes["pc-demo-02"][0], SecurityCveImpact.NOT_IMPACTED)
        self.assertNotIn("pc-demo-03", outcomes)

    def test_unmapped_product_is_to_verify(self):
        outcomes = self._outcomes(self._cve())
        self.assertEqual(outcomes["pc-demo-01"][0], SecurityCveImpact.TO_VERIFY)
        self.assertIn("mappatura CPE non è confermata", outcomes["pc-demo-01"][1])

    def test_not_comparable_version_is_to_verify(self):
        SoftwareCpeMapping.objects.create(vendor="demo corp", product="demoviewer", cpe_vendor="democorp", cpe_product="demoviewer", confirmed=True)
        record = self._cve("CVE-2099-0003", [{"part": "a", "vendor": "democorp", "product": "demoviewer", "version": "*", "start_including": "",
                                              "start_excluding": "", "end_including": "", "end_excluding": "22.0", "requires_platform": False}])
        outcomes = self._outcomes(record)
        self.assertEqual(outcomes["pc-demo-03"][0], SecurityCveImpact.TO_VERIFY)
        self.assertIn("non confrontabile", outcomes["pc-demo-03"][1])

    def test_stale_inventory_is_to_verify(self):
        self._map_7zip()
        SoftwareInstallation.objects.update(last_inventory_date=timezone.localdate() - timedelta(days=90))
        outcomes = self._outcomes(self._cve())
        self.assertEqual(outcomes["pc-demo-01"][0], SecurityCveImpact.TO_VERIFY)
        self.assertIn("Inventario vecchio", outcomes["pc-demo-01"][1])

    def test_platform_specific_configuration_is_to_verify(self):
        self._map_7zip()
        record = self._cve(criteria=[{"part": "a", "vendor": "7-zip", "product": "7-zip", "version": "*", "start_including": "",
                                      "start_excluding": "", "end_including": "", "end_excluding": "24.07", "requires_platform": True}])
        self.assertEqual(self._outcomes(record)["pc-demo-01"][0], SecurityCveImpact.TO_VERIFY)

    def test_summary_absent_hosts_and_closure_proposal(self):
        self._map_7zip()
        record = self._cve(criteria=[{"part": "a", "vendor": "7-zip", "product": "7-zip", "version": "*", "start_including": "",
                                      "start_excluding": "", "end_including": "", "end_excluding": "20.00", "requires_platform": False}])
        cve_impact.recompute(record)
        info = cve_impact.summary(record)
        self.assertEqual(info["impacts"], 0)
        self.assertEqual(info["not_impacted"], 2)
        self.assertEqual(info["absent_hosts"], 1)
        self.assertTrue(info["closure"][0])

    def test_kev_or_critical_never_proposed_for_closure(self):
        self._map_7zip()
        criteria = [{"part": "a", "vendor": "7-zip", "product": "7-zip", "version": "*", "start_including": "", "start_excluding": "",
                     "end_including": "", "end_excluding": "20.00", "requires_platform": False}]
        kev = self._cve("CVE-2099-0010", criteria, kev=True)
        critical = self._cve("CVE-2099-0011", criteria, cvss=9.8, severity="critical")
        for record in (kev, critical):
            cve_impact.recompute(record)
            self.assertFalse(cve_impact.summary(record)["closure"][0])

    def test_dashboard_lists(self):
        self._map_7zip()
        cve_impact.recompute(self._cve())
        self.assertEqual([c.cve_id for c in cve_impact.impacting_cves()], ["CVE-2099-0001"])
        self.assertEqual(cve_impact.most_exposed_hosts()[0]["host"], "pc-demo-01")
        self.assertIn("demoviewer", [row["product"] for row in cve_impact.unmapped_software()])


class ImpactAlertTests(_Base):
    """PC che diventano impattati da una CVE critica o in KEV: alert per CVE ed eventuale ticket."""

    def setUp(self):
        super().setUp()
        self._import()
        self._map_7zip()

    def _settings(self, **overrides):
        from security.services import soc_settings

        real = soc_settings.value
        values = {"cve.impatto.alert": True, "cve.impatto.ticket": True, **overrides}
        return patch.object(soc_settings, "value", side_effect=lambda key: values[key] if key in values else real(key))

    def _alerts(self):
        return SecurityAlert.objects.filter(event__event_type=cve_impact.IMPACT_EVENT_TYPE)

    def test_critical_cve_opens_one_alert_and_ticket(self):
        self._cve(cvss=9.8, severity="critical")
        with self._settings():
            cve_impact.recompute_all()
        alert = self._alerts().get()
        self.assertEqual(alert.severity, "critical")
        self.assertIn("CVE-2099-0001", alert.title)
        self.assertIn("1 PC", alert.title)
        ticket = SecurityRemediationTicket.objects.get(linked_alerts=alert)
        self.assertIn("CVE-2099-0001", ticket.cve_ids)

    def test_same_hosts_do_not_raise_again(self):
        self._cve(kev=True)
        with self._settings():
            cve_impact.recompute_all()
            cve_impact.recompute_all()
        self.assertEqual(SecurityEventRecord.objects.filter(event_type=cve_impact.IMPACT_EVENT_TYPE).count(), 1)
        self.assertEqual(self._alerts().count(), 1)

    def test_non_critical_cve_without_kev_has_no_alert(self):
        self._cve(cvss=7.8, severity="high")
        with self._settings():
            cve_impact.recompute_all()
        self.assertFalse(self._alerts().exists())

    def test_setting_off_means_no_alert(self):
        self._cve(kev=True)
        with self._settings(**{"cve.impatto.alert": False}):
            cve_impact.recompute_all()
        self.assertFalse(SecurityEventRecord.objects.filter(event_type=cve_impact.IMPACT_EVENT_TYPE).exists())

    def test_existing_ticket_for_the_cve_is_reused(self):
        self._cve(kev=True)
        other = SecuritySource.objects.create(name="Defender demo", source_type="email")
        existing = SecurityRemediationTicket.objects.create(source=other, cve="CVE-2099-0001", cve_ids=["CVE-2099-0001"], title="Remediate demo",
                                                            affected_product="7-zip", dedup_hash="demo-hash")
        with self._settings():
            cve_impact.recompute_all()
        self.assertEqual(SecurityRemediationTicket.objects.count(), 1)
        self.assertIn(self._alerts().get(), existing.linked_alerts.all())

    def test_ticket_off_keeps_only_the_alert(self):
        self._cve(kev=True)
        with self._settings(**{"cve.impatto.ticket": False}):
            cve_impact.recompute_all()
        self.assertTrue(self._alerts().exists())
        self.assertFalse(SecurityRemediationTicket.objects.exists())


class RecomputeAllConcurrencyTests(_Base):
    """Un solo ricalcolo completo alla volta, richieste accodate unite, letture una volta sola."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.delete_many([cve_impact.LOCK_KEY, cve_impact.QUEUED_KEY, cve_impact.RERUN_KEY])
        self.addCleanup(cache.delete_many, [cve_impact.LOCK_KEY, cve_impact.QUEUED_KEY, cve_impact.RERUN_KEY])
        self._import()
        self._map_7zip()

    def test_ricalcolo_gia_in_corso_viene_rimandato_e_rifatto_alla_fine(self):
        from django.core.cache import cache

        self._cve()
        cache.add(cve_impact.LOCK_KEY, "altro processo", 60)
        self.assertEqual(cve_impact.recompute_all(), 0)
        self.assertFalse(SecurityCveImpact.objects.exists())
        cache.delete(cve_impact.LOCK_KEY)
        with patch("security.services.cve_feeds.queue_recompute") as queue:
            self.assertGreater(cve_impact.recompute_all(), 0)
        queue.assert_called_once()
        self.assertIsNone(cache.get(cve_impact.LOCK_KEY))

    def test_richieste_accodate_insieme_diventano_un_solo_task(self):
        from security.services import cve_feeds

        with patch("django_q.tasks.async_task") as async_task:
            self.assertEqual(cve_feeds.queue_recompute(), "accodato")
            self.assertEqual(cve_feeds.queue_recompute(), "già accodato")
            async_task.assert_called_once()
            cve_impact.recompute_all()  # parte: la richiesta successiva si accoda di nuovo
            self.assertEqual(cve_feeds.queue_recompute(), "accodato")

    def test_letture_non_crescono_con_il_numero_di_cve(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._cve()
        with CaptureQueriesContext(connection) as una:
            cve_impact.recompute_all()
        for n in range(2, 6):
            self._cve(cve_id=f"CVE-2099-000{n}")
        with CaptureQueriesContext(connection) as cinque:
            cve_impact.recompute_all()
        letture = lambda ctx: sum(1 for q in ctx.captured_queries if "security_softwareinstallation" in q["sql"] and q["sql"].lstrip().upper().startswith("SELECT"))  # noqa: E731
        self.assertEqual(letture(una), letture(cinque))


class FeedTests(_Base):
    NVD = {"vulnerabilities": [{"cve": {
        "id": "CVE-2099-0001", "published": "2099-01-01T00:00:00.000", "lastModified": "2099-01-02T00:00:00.000",
        "descriptions": [{"lang": "en", "value": "Synthetic 7-Zip issue"}],
        "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 7.8, "baseSeverity": "HIGH"}}]},
        "configurations": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
            {"vulnerable": True, "criteria": "cpe:2.3:a:7-zip:7-zip:*:*:*:*:*:*:*:*", "versionEndExcluding": "24.07"}]}]}],
    }}]}
    KEV = {"vulnerabilities": [{"cveID": "CVE-2099-0001", "dateAdded": "2099-01-05", "dueDate": "2099-01-26"}]}
    EPSS = {"data": [{"cve": "CVE-2099-0001", "epss": "0.42", "percentile": "0.97"}]}

    def _fake(self, calls):
        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append((url, params, headers))
            if url == cve_feeds.NVD_CVE_URL:
                return 200, self.NVD
            if url == cve_feeds.KEV_URL:
                return 200, self.KEV
            if url == cve_feeds.EPSS_URL:
                return 200, self.EPSS
            return 404, None
        return fake_get

    def test_enrichment_parses_nvd_kev_epss_and_caches(self):
        calls = []
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0001")
        with patch.object(cve_feeds, "http_get", self._fake(calls)):
            result = cve_feeds.run_enrichment(sleep=lambda s: None, recompute=lambda: "test")
        record = SecurityCveRecord.objects.get(cve_id="CVE-2099-0001")
        self.assertEqual(result["nvd"], 1)
        self.assertEqual(record.cvss, 7.8)
        self.assertEqual(record.configurations[0]["end_excluding"], "24.07")
        self.assertTrue(record.kev)
        self.assertAlmostEqual(record.epss, 0.42)
        self.assertTrue(SecurityExternalFeedCache.objects.filter(feed="nvd_cve", key="CVE-2099-0001").exists())
        calls.clear()
        with patch.object(cve_feeds, "http_get", self._fake(calls)):
            cve_feeds.fetch_nvd_cve("CVE-2099-0001")
        self.assertEqual(calls, [])  # servito dalla cache dedicata

    def test_time_budget_stops_the_run(self):
        clock = [0.0]

        def slow(url, params=None, headers=None, timeout=None):
            clock[0] += 40  # ogni richiesta «costa» 40 s
            return 200, self.NVD if url == cve_feeds.NVD_CVE_URL else ({"vulnerabilities": []} if url == cve_feeds.KEV_URL else {"data": []})

        for n in range(1, 6):
            SecurityCveRecord.objects.create(cve_id=f"CVE-2099-02{n:02d}")
        with patch.object(cve_feeds, "http_get", slow):
            result = cve_feeds.run_enrichment(time_budget_seconds=90, clock=lambda: clock[0], sleep=lambda s: None, recompute=lambda: "test")
        self.assertLess(result["nvd"], 5)
        self.assertTrue(any("budget" in e for e in result["errors"]))
        self.assertLess(clock[0], 140)

    def test_retry_with_backoff_then_error(self):
        attempts, sleeps = [], []

        def failing(url, params=None, headers=None, timeout=None):
            attempts.append(url)
            return 503, None

        with patch.object(cve_feeds, "http_get", failing):
            record = cve_feeds.enrich_cve("CVE-2099-0002", sleep=sleeps.append)
        self.assertEqual(len(attempts), cve_feeds.RETRIES)
        self.assertEqual(sleeps, [2, 4, 8])
        self.assertIn("HTTP 503", record.nvd_error)

    def test_network_exception_is_handled(self):
        def boom(url, params=None, headers=None, timeout=None):
            raise OSError("rete giù")

        with patch.object(cve_feeds, "http_get", boom):
            record = cve_feeds.enrich_cve("CVE-2099-0004", sleep=lambda s: None)
        self.assertIn("OSError", record.nvd_error)

    def test_rate_limiter_waits_after_limit(self):
        clock = [0.0]
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            clock[0] += seconds

        limiter = cve_feeds.RateLimiter(5, 30.0, clock=lambda: clock[0], sleep=sleep)
        for _ in range(5):
            limiter.wait()
        self.assertEqual(slept, [])
        limiter.wait()
        self.assertEqual(len(slept), 1)
        self.assertGreaterEqual(slept[0], 30.0)

    def test_epss_cache_key_is_hashed(self):
        calls = []
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0001")
        with patch.object(cve_feeds, "http_get", self._fake(calls)):
            cve_feeds.refresh_epss(["CVE-2099-0001"], sleep=lambda s: None)
        self.assertEqual(len(SecurityExternalFeedCache.objects.get(feed="epss").key), 64)

    def test_api_key_encrypted_and_sent(self):
        cve_feeds.set_nvd_api_key("chiave-sintetica-123", actor=self.user)
        stored = SecurityCenterSetting.objects.get(key=cve_feeds.NVD_KEY_SETTING)
        self.assertNotIn("chiave-sintetica-123", str(stored.value))
        self.assertEqual(cve_feeds.nvd_api_key(), "chiave-sintetica-123")
        calls = []
        with patch.object(cve_feeds, "http_get", self._fake(calls)):
            cve_feeds.fetch_nvd_cve("CVE-2099-0001")
        self.assertEqual(calls[0][2], {"apiKey": "chiave-sintetica-123"})
        self.assertEqual(cve_feeds.nvd_limiter().limit, 50)

    def test_task_skipped_when_disabled(self):
        from security.tasks import enrich_cve_task

        with patch.object(cve_feeds, "http_get", side_effect=AssertionError("niente rete")):
            self.assertIn("skipped", enrich_cve_task())


class ViewTests(_Base):
    def test_upload_map_preview_import_flow(self):
        upload = SimpleUploadedFile("export.csv", CSV, content_type="text/csv")
        with patch("security.views_vuln.validate_extension_and_mime", return_value="text/csv"):
            response = self.client.post(reverse("security:inventory"), {"file": upload, "source_kind": "watchguard"})
        item = SoftwareInventoryImport.objects.get()
        self.assertRedirects(response, reverse("security:inventory_map", args=[item.pk]))
        self.assertEqual(item.column_map["hostname"], "Computer")
        response = self.client.get(reverse("security:inventory_map", args=[item.pk]))
        self.assertContains(response, "hostname vuoto")
        post = {f"col_{k}": v for k, v in MAP.items()}
        response = self.client.post(reverse("security:inventory_map", args=[item.pk]), {**post, "do": "import", "preset_name": "WatchGuard demo"})
        self.assertRedirects(response, reverse("security:inventory"))
        item.refresh_from_db()
        self.assertEqual(item.status, SoftwareInventoryImport.STATUS_IMPORTED)
        self.assertEqual(item.stored_name, "")
        self.assertEqual(SoftwareInstallation.objects.count(), 3)
        self.assertEqual(item.preset.name, "WatchGuard demo")

    def test_upload_rejects_bad_mime(self):
        upload = SimpleUploadedFile("export.csv", b"<html>", content_type="text/csv")
        response = self.client.post(reverse("security:inventory"), {"file": upload}, follow=True)
        self.assertFalse(SoftwareInventoryImport.objects.exists())
        self.assertEqual(response.status_code, 200)

    def test_cpe_confirm_and_pages_render(self):
        self._import()
        response = self.client.post(reverse("security:software_mapping"), {"action": "cpe_confirm", "vendor": "igor pavlov", "product": "7-zip", "cpe": "7-zip:7-zip"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SoftwareCpeMapping.objects.get(product="7-zip").confirmed)
        self._cve()
        cve_impact.recompute_all()
        for url in (reverse("security:vulnerabilities"), reverse("security:cve_detail", args=["CVE-2099-0001"]),
                    reverse("security:software_mapping"), reverse("security:inventory")):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(reverse("security:cve_detail", args=["CVE-2099-0001"])), "Impatta")

    def test_config_pages_require_config_permission(self):
        viewer = get_user_model().objects.create(username="soc_cve_viewer")
        self.client.force_login(viewer)
        with patch("security.views_vuln.can_view_security_center", return_value=True), \
                patch("core.middleware.ACLMiddleware.__call__", lambda self, r: self.get_response(r), create=True):
            response = self.client.post(reverse("security:software_mapping"), {"action": "nvd_key", "nvd_key": "x"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SecurityCenterSetting.objects.filter(key=cve_feeds.NVD_KEY_SETTING).exists())

    def test_invalid_cve_id_404(self):
        self.assertEqual(self.client.get(reverse("security:cve_detail", args=["not-a-cve"])).status_code, 404)

    def test_hub_asset_page_shows_vulnerabilities(self):
        from assets.models import Asset

        asset = Asset.objects.create(name="PC-DEMO-01")
        self._import()
        self._map_7zip()
        cve_impact.recompute(self._cve())
        self.assertEqual(SoftwareInstallation.objects.get(host="pc-demo-01").hub_asset_id, asset.pk)
        from django.template import Context, Template
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.user = self.user
        html = Template("{% load security_asset %}{% security_asset_vulns asset %}").render(Context({"asset": asset, "request": request}))
        self.assertIn("CVE-2099-0001", html)
        self.assertIn("Vulnerabilità", html)


class AutoLinkTests(_Base):
    """Collegamento automatico software ↔ CPE quando il nome non lascia dubbi."""

    def setUp(self):
        super().setUp()
        self._import()

    def test_match_rules(self):
        from security.services.cpe_auto import match

        pairs = {("google", "chrome"), ("7-zip", "7-zip"), ("acme", "viewer"), ("demo", "viewer"), ("x", "zip")}
        self.assertEqual(match("google", "google chrome", pairs), ("google", "chrome"))
        self.assertEqual(match("igor pavlov", "7-zip", pairs), ("7-zip", "7-zip"))
        self.assertIsNone(match("other", "viewer", pairs))  # stesso nome per due produttori: decide una persona
        self.assertIsNone(match("other", "zip", pairs))     # nome troppo corto per collegarlo da solo
        self.assertIsNone(match("google", "google earth", pairs))

    def test_auto_link_then_impact_explains_it(self):
        from security.services.cpe_auto import auto_link

        record = self._cve()
        self.assertEqual(auto_link(), 1)
        mapping = SoftwareCpeMapping.objects.get(product="7-zip")
        self.assertTrue(mapping.confirmed)
        self.assertEqual(mapping.origin, SoftwareCpeMapping.ORIGIN_AUTO)
        cve_impact.recompute(record)
        impact = record.impacts.get(host="pc-demo-01")
        self.assertEqual(impact.outcome, SecurityCveImpact.IMPACTS)
        self.assertIn("collegamento automatico a 7-zip:7-zip", impact.explanation)
        self.assertEqual(auto_link(), 0)  # già collegato: niente da rifare

    def test_reset_of_auto_link_is_not_redone(self):
        from security.services.cpe_auto import auto_link

        self._cve()
        auto_link()
        mapping = SoftwareCpeMapping.objects.get(product="7-zip")
        self.client.post(reverse("security:software_mapping"), {"action": "cpe_reset", "vendor": mapping.vendor, "product": mapping.product})
        mapping.refresh_from_db()
        self.assertFalse(mapping.confirmed)
        self.assertEqual(mapping.origin, SoftwareCpeMapping.ORIGIN_AUTO_REJECTED)
        self.assertEqual(auto_link(), 0)
        mapping.refresh_from_db()
        self.assertFalse(mapping.confirmed)

    def test_human_decisions_are_never_touched(self):
        from security.services.cpe_auto import auto_link

        self._cve()
        SoftwareCpeMapping.objects.create(vendor="igor pavlov", product="7-zip", not_applicable=True)
        self.assertEqual(auto_link(), 0)
        self.assertFalse(SoftwareCpeMapping.objects.get(product="7-zip").confirmed)

    def test_bulk_confirm_and_filters(self):
        self._cve(criteria=[{"part": "a", "vendor": "democorp", "product": "demoviewer_pro", "version": "*", "start_including": "",
                             "start_excluding": "", "end_including": "", "end_excluding": "22.0", "requires_platform": False}])
        page = self.client.get(reverse("security:software_mapping"), {"stato": "proposte"})
        self.assertContains(page, "Da decidere (1)")
        self.assertContains(page, "demo corp|||demoviewer|||democorp:demoviewer_pro")
        self.client.post(reverse("security:software_mapping"), {"action": "cpe_confirm_bulk", "bulk": ["demo corp|||demoviewer|||democorp:demoviewer_pro"]})
        mapping = SoftwareCpeMapping.objects.get(product="demoviewer")
        self.assertEqual((mapping.cpe_vendor, mapping.cpe_product, mapping.confirmed, mapping.origin), ("democorp", "demoviewer_pro", True, ""))


class MappingTriageTests(_Base):
    """«Da decidere» vs «Senza CVE note», azioni in blocco e regole «non applicabile»."""

    EXTRA = (
        "Computer;Editore;Software;Versione;Rilevato il\n"
        "PC-DEMO-01;Demo Corp;DemoViewer;21H2;01/10/2026\n"
        "PC-DEMO-01;Microsoft;Demo Redistributable 2015;14.0;01/10/2026\n"
        "PC-DEMO-02;Microsoft;Demo Redistributable 2019;14.2;01/10/2026\n"
        "PC-DEMO-02;Intel;Demo Graphics Driver;31.0;01/10/2026\n"
    ).encode("utf-8")
    URL = "security:software_mapping"

    def setUp(self):
        super().setUp()
        self._import(self.EXTRA)
        # CVE sintetica dal nome simile a DemoViewer: unica riga «da decidere».
        self._cve(criteria=[{"part": "a", "vendor": "democorp", "product": "demoviewer_pro", "version": "*", "start_including": "",
                             "start_excluding": "", "end_including": "", "end_excluding": "22.0", "requires_platform": False}])

    def _page(self, **params):
        return self.client.get(reverse(self.URL), params)

    def test_states_split_work_from_noise(self):
        page = self._page(stato="proposte")
        self.assertContains(page, "Da decidere (1)")
        self.assertContains(page, "Senza CVE note (3)")
        self.assertContains(page, "demoviewer")
        self.assertNotContains(page, "demo graphics driver")
        self.assertContains(self._page(stato="senza_cve"), "demo graphics driver")
        # Il vecchio filtro apre «Da decidere».
        self.assertEqual(self._page(stato="da_mappare").context["stato"], "proposte")

    def test_confirm_unique_across_pages(self):
        self.client.post(reverse(self.URL), {"action": "cpe_confirm_unique", "q": "", "stato": "proposte"})
        mapping = SoftwareCpeMapping.objects.get(product="demoviewer")
        self.assertEqual((mapping.cpe_vendor, mapping.cpe_product, mapping.confirmed), ("democorp", "demoviewer_pro", True))
        self.assertEqual(SoftwareCpeMapping.objects.filter(confirmed=True).count(), 1)

    def test_na_bulk_and_na_search(self):
        self.client.post(reverse(self.URL), {"action": "cpe_na_bulk", "bulk": ["intel|||demo graphics driver|||"]})
        self.assertTrue(SoftwareCpeMapping.objects.get(product="demo graphics driver").not_applicable)
        self.client.post(reverse(self.URL), {"action": "cpe_na_search", "q": "re"})  # troppo corta: niente
        self.assertFalse(SoftwareCpeMapping.objects.filter(product__contains="redistributable").exists())
        self.client.post(reverse(self.URL), {"action": "cpe_na_search", "q": "redistributable", "stato": ""})
        self.assertEqual(SoftwareCpeMapping.objects.filter(product__contains="redistributable", not_applicable=True).count(), 2)
        self.assertContains(self._page(stato="non_applicabili"), "Non applicabili (3)")

    def test_rule_applies_spares_proposals_and_reopens_on_delete(self):
        from security.models import SoftwareNaRule
        from security.services.cpe_rules import apply_rules

        SoftwareCpeMapping.objects.create(vendor="intel", product="demo graphics driver", cpe_vendor="intel", cpe_product="x", confirmed=True)
        self.client.post(reverse(self.URL), {"action": "na_rule", "pattern": " Demo ", "note": "sintetica"})
        rule = SoftwareNaRule.objects.get(pattern="demo")
        excluded = SoftwareCpeMapping.objects.filter(na_rule=rule, not_applicable=True, origin=SoftwareCpeMapping.ORIGIN_RULE)
        # Solo i due redistributable: DemoViewer ha una proposta, il driver è già confermato.
        self.assertEqual(sorted(excluded.values_list("product", flat=True)), ["demo redistributable 2015", "demo redistributable 2019"])
        self.assertFalse(SoftwareCpeMapping.objects.filter(product="demoviewer", not_applicable=True).exists())
        self.assertTrue(SoftwareCpeMapping.objects.get(product="demo graphics driver").confirmed)
        # Import successivo con un prodotto nuovo: la regola vale anche lì.
        self._import("Computer;Editore;Software;Versione;Rilevato il\nPC-DEMO-03;Microsoft;Demo Redistributable 2022;14.3;01/10/2026\n".encode("utf-8"))
        apply_rules()
        self.assertTrue(SoftwareCpeMapping.objects.get(product="demo redistributable 2022").not_applicable)
        # Una CVE dal nome simile arrivata dopo riporta il software in «Da decidere».
        self._cve("CVE-2099-0002", criteria=[{"part": "a", "vendor": "microsoft", "product": "demo_redistributable", "version": "*",
                                              "start_including": "", "start_excluding": "", "end_including": "", "end_excluding": "",
                                              "requires_platform": False}])
        page = self._page(stato="proposte")
        self.assertContains(page, "è arrivata una CVE dal nome simile")
        # Eliminare la regola riapre ciò che aveva escluso.
        self.client.post(reverse(self.URL), {"action": "na_rule_delete", "rule_id": rule.pk})
        self.assertFalse(SoftwareNaRule.objects.exists())
        self.assertFalse(SoftwareCpeMapping.objects.filter(product__contains="redistributable", not_applicable=True).exists())

    def test_rule_vendor_filter_and_min_length(self):
        from security.models import SoftwareNaRule

        self.client.post(reverse(self.URL), {"action": "na_rule", "pattern": "dr"})
        self.assertFalse(SoftwareNaRule.objects.exists())
        self.client.post(reverse(self.URL), {"action": "na_rule", "pattern": "demo", "vendor": "Intel"})
        self.assertEqual(list(SoftwareCpeMapping.objects.filter(not_applicable=True).values_list("product", flat=True)), ["demo graphics driver"])
        self.assertEqual(self._page().status_code, 200)
