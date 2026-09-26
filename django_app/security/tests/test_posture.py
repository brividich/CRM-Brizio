"""Postura, trend e stato pipeline della dashboard SOC calcolati dai dati reali.

Prima i punteggi (72/81/94/88), il trend e le card della pipeline erano scritti a mano
nei template: la console restava «verde» qualunque cosa accadesse. Questi test fissano
che i numeri mostrati cambiano con i dati e che senza dati si dichiara «n.d.».
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    ParseStatus,
    SecurityAlert,
    SecurityMailboxMessage,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.services.posture import build_pipeline_status, build_posture, build_trend


def _indicator(key):
    return next(ind for ind in build_posture() if ind["key"] == key)


class PostureTest(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Demo", vendor="Demo", source_type=SourceType.EMAIL)

    def _alert(self, severity, status=Status.NEW, n=1):
        for i in range(n):
            SecurityAlert.objects.create(
                source=self.source, title=f"A{severity}{i}", severity=severity, status=status, dedup_hash=f"{severity}{status}{i}"
            )

    def test_alert_score_drops_with_active_alerts(self):
        self.assertEqual(_indicator("alerts")["score"], 100)
        self._alert(Severity.CRITICAL)
        self._alert(Severity.WARNING)
        ind = _indicator("alerts")
        self.assertEqual(ind["score"], 100 - 30 - 8)
        self.assertIn("1 critici", ind["detail"])

    def test_snoozed_and_closed_alerts_do_not_penalize(self):
        self._alert(Severity.CRITICAL, status=Status.SNOOZED)
        self._alert(Severity.CRITICAL, status=Status.CLOSED)
        self.assertEqual(_indicator("alerts")["score"], 100)

    def test_alert_score_never_negative(self):
        self._alert(Severity.CRITICAL, n=5)
        ind = _indicator("alerts")
        self.assertEqual(ind["score"], 0)
        self.assertEqual(ind["tone"], "danger")

    def test_no_data_is_not_available(self):
        for key in ("vulnerabilities", "backup", "ingestion"):
            ind = _indicator(key)
            self.assertIsNone(ind["score"], key)
            self.assertEqual(ind["grade"], "n.d.")

    def test_backup_ratio(self):
        for i, status in enumerate(["completed", "completed", "warning", "failed"]):
            BackupJobRecord.objects.create(source=self.source, job_name=f"J{i}", status=status, dedup_hash=f"b{i}")
        # (2 + 0.5) / 4 = 62.5 -> 62 (arrotondamento bancario di round)
        self.assertEqual(_indicator("backup")["score"], 62)

    def test_ingestion_counts_failures(self):
        for i, status in enumerate([ParseStatus.PARSED, ParseStatus.PARSED, ParseStatus.PARSED, ParseStatus.FAILED]):
            SecurityMailboxMessage.objects.create(source=self.source, subject=f"S{i}", parse_status=status)
        self.assertEqual(_indicator("ingestion")["score"], 75)


class TrendAndPipelineTest(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Demo", vendor="Demo", source_type=SourceType.EMAIL)

    def test_trend_counts_today(self):
        SecurityAlert.objects.create(source=self.source, title="x", severity=Severity.CRITICAL, dedup_hash="t1")
        trend = build_trend(today=timezone.localdate())
        totals = {s["key"]: s["total"] for s in trend["series"]}
        self.assertEqual(totals["alerts"], 1)
        self.assertEqual(totals["critical"], 1)
        self.assertEqual(len(trend["days"]), 7)
        self.assertFalse(trend["is_empty"])

    def test_trend_empty(self):
        self.assertTrue(build_trend()["is_empty"])

    def test_pipeline_status_counts(self):
        SecurityMailboxMessage.objects.create(source=self.source, subject="p", parse_status=ParseStatus.PENDING)
        SecurityMailboxMessage.objects.create(source=self.source, subject="f", parse_status=ParseStatus.FAILED)
        status = build_pipeline_status()
        self.assertEqual(status["pending"], 1)
        self.assertEqual(status["failed"], 1)
        self.assertGreater(status["parsers_registered"], 0)


class NoHardcodedNumbersTest(TestCase):
    """I template non devono tornare ad avere punteggi/grafici finti."""

    TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "security"

    def test_no_fake_values_in_templates(self):
        for name in ("dashboard.html", "kpis.html", "pipeline.html"):
            text = (self.TEMPLATES / name).read_text(encoding="utf-8")
            self.assertNotIn("--score:72", text, name)
            self.assertNotIn("sec-chart-line", text, name)
            self.assertNotIn("sec-bar", text, name)

    def test_pages_render_with_real_values(self):
        U = get_user_model()
        user = U.objects.create(username="soc_posture_admin", is_staff=True, is_superuser=True)
        self.client.force_login(user)
        source = SecuritySource.objects.create(name="Demo", vendor="Demo", source_type=SourceType.EMAIL)
        SecurityAlert.objects.create(source=source, title="x", severity=Severity.CRITICAL, dedup_hash="r1")
        html = self.client.get(reverse("security:dashboard")).content.decode()
        self.assertIn("--score:70;", html)
        self.assertIn("<polyline", html)
        for name in ("security:kpis", "security:pipeline"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
