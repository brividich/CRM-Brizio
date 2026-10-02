from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from assets.models import Asset
from security.models import SecurityAlert, SecurityAsset, SecurityAssetSignal, SecurityEventRecord, SecuritySource, Status
from security.services.asset_overview import overview_for_hub_asset
from security.templatetags.security_asset import security_asset_it_overview


class AssetOverviewTests(TestCase):
    def setUp(self):
        self.hub = Asset.objects.create(asset_tag="SOC-DEMO", name="Demo", asset_type="PC")
        self.source = SecuritySource.objects.create(name="Fonte demo", source_type="manual")
        self.device = SecurityAsset.objects.create(hostname="PC-DEMO", hub_asset=self.hub, source=self.source)
        self.now = timezone.now()

    def signal(self, job, status="completed", hours=0, device=None, source=None, key=None):
        return SecurityAssetSignal.objects.create(asset=device or self.device, source=source or self.source, kind="backup", status=status, title="Backup dimostrativo", detail={"job": job} if job else {}, occurred_at=self.now - timedelta(hours=hours), dedup_hash=key or f"{job}-{status}-{hours}")

    def test_failed_job_not_masked_by_success_of_other_job(self):
        previous = self.signal("A", hours=24)
        failure = self.signal("A", "failed", hours=2)
        self.signal("B", hours=1)
        rows = {r["job"]: r for r in overview_for_hub_asset(self.hub)["backup_rows"]}
        self.assertEqual(rows["A"]["latest"], failure)
        self.assertEqual(rows["A"]["success"], previous)
        self.assertEqual(rows["B"]["latest"].status, "completed")

    def test_old_report_arriving_late_does_not_replace_latest_fact(self):
        current = self.signal("A", "failed")
        self.signal("A", hours=72)
        data = overview_for_hub_asset(self.hub)
        self.assertEqual(data["last_signal"], current)
        self.assertEqual(data["backup_rows"][0]["latest"], current)

    def test_identity_and_source_are_not_merged_by_job_name(self):
        self.signal("same")
        source = SecuritySource.objects.create(name="Seconda fonte", source_type="manual")
        device = SecurityAsset.objects.create(hostname="ALIAS-DEMO", hub_asset=self.hub, source=source)
        self.signal("same", device=device, source=source)
        self.assertEqual(len(overview_for_hub_asset(self.hub)["backup_rows"]), 2)

    def test_unknown_job_not_merged_and_bounded_sample_is_explicit(self):
        self.signal(None, key="unknown-a")
        self.signal(None, key="unknown-b", hours=1)
        self.assertEqual(len(overview_for_hub_asset(self.hub)["backup_rows"]), 2)
        with patch("security.services.asset_overview.BACKUP_SAMPLE_LIMIT", 1):
            data = overview_for_hub_asset(self.hub)
        self.assertTrue(data["backup_sample_limited"])
        self.assertEqual(data["backup_sample_size"], 1)

    def test_alerts_require_explicit_asset_event_and_active_status(self):
        event = SecurityEventRecord.objects.create(source=self.source, asset=self.device, event_type="demo", fingerprint="demo", dedup_hash="demo")
        for key, status, severity, linked_event in (("high", Status.OPEN, "high", event), ("critical", Status.OPEN, "critical", event), ("closed", Status.CLOSED, "critical", event), ("unlinked", Status.OPEN, "critical", None)):
            SecurityAlert.objects.create(source=self.source, event=linked_event, title=key, severity=severity, status=status, dedup_hash=key, decision_trace={})
        data = overview_for_hub_asset(self.hub)
        self.assertEqual(data["open_alert_count"], 2)
        self.assertEqual([x.title for x in data["open_alerts"]], ["critical", "high"])

    def test_permission_denied_does_not_query_soc(self):
        user = get_user_model().objects.create(username="no-soc")
        with self.assertNumQueries(0), patch("security.templatetags.security_asset.can_view_security_center", return_value=False):
            data = security_asset_it_overview({"request": SimpleNamespace(user=user)}, self.hub)
        self.assertEqual(data, {"show": False})

    def test_projection_query_count_independent_of_rows(self):
        for i in range(15):
            self.signal(f"job-{i}")
        with self.assertNumQueries(4):
            data = overview_for_hub_asset(self.hub)
            for row in data["backup_rows"]:
                str(row["latest"].source.name)
                str(row["latest"].asset.hostname)
        self.assertTrue(data["backup_jobs_limited"])
        self.assertEqual(len(data["backup_rows"]), 12)
