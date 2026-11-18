"""KPI cliccabili del monitoring: ogni tessera porta alla lista filtrata che conta lo stesso numero."""
from __future__ import annotations

import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from monitoring.models import AutomationExecution, AutomationJob, Issue


def _href_for(html: str, needle: str) -> str:
    """href della prima <a class="... kpi-link"> che contiene ``needle``."""
    for m in re.finditer(r'<a class="[^"]*kpi-link[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        if needle in m.group(2):
            return m.group(1).replace("&amp;", "&")
    raise AssertionError(f"KPI cliccabile non trovato: {needle}")


class MonitoringKpiLinkTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="kpi_mon", email="kpi_mon@example.test", password="x"
        )
        self.client = Client()
        self.client.force_login(self.admin)
        now = timezone.now()
        base = dict(category=Issue.Category.BUG, source=Issue.Source.WEB)
        self.i1 = Issue.objects.create(code="K-1", title="a", severity=Issue.Severity.CRITICAL,
                                       status=Issue.Status.NEW, fingerprint="f1", **base)
        Issue.objects.create(code="K-2", title="b", severity=Issue.Severity.LOW,
                             status=Issue.Status.NEW, fingerprint="f2", assigned_to=self.admin, **base)
        old = Issue.objects.create(code="K-3", title="c", severity=Issue.Severity.CRITICAL,
                                   status=Issue.Status.RESOLVED,
                                   fingerprint="f3", **base)
        Issue.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=3))
        self.job_ko = AutomationJob.objects.create(code="job_ko", name="Job KO")
        self.job_ok = AutomationJob.objects.create(code="job_ok", name="Job OK")
        AutomationExecution.objects.create(job=self.job_ko, status=AutomationExecution.Status.FAILED, started_at=now)
        AutomationExecution.objects.create(job=self.job_ko, status=AutomationExecution.Status.FAILED, started_at=now)
        AutomationExecution.objects.create(job=self.job_ok, status=AutomationExecution.Status.SUCCESS,
                                           started_at=now)
        self.job_missing = AutomationJob.objects.create(code="job_miss", name="Job Missing",
                                                        expected_max_interval_minutes=5)
        AutomationJob.objects.filter(pk=self.job_missing.pk).update(created_at=now - timedelta(hours=2))

    def _count_issues(self, href: str) -> int:
        resp = self.client.get(href)
        self.assertEqual(resp.status_code, 200)
        return resp.context["page_obj"].paginator.count

    def test_dashboard_issue_kpis_match_filtered_list(self):
        resp = self.client.get(reverse("monitoring_admin:dashboard"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        ctx = resp.context
        for label, key in (("Issue aperte", "open_issues_count"), ("Issue critiche", "critical_issues_count"),
                           ("Nuove ultime 24h", "new_issues_24h_count"), ("Non assegnate", "unassigned_open_issues_count")):
            href = _href_for(html, label)
            self.assertTrue(href.startswith(reverse("monitoring_admin:issue_list")), href)
            self.assertEqual(self._count_issues(href), ctx[key], label)
        self.assertEqual(ctx["critical_issues_count"], 1)
        self.assertEqual(ctx["unassigned_open_issues_count"], 1)
        self.assertEqual(ctx["new_issues_24h_count"], 2)

    def test_dashboard_job_kpis_match_filtered_automation_list(self):
        resp = self.client.get(reverse("monitoring_admin:dashboard"))
        html = resp.content.decode()
        # Due esecuzioni fallite dello stesso job = 1 job fallito (la tessera conta job).
        self.assertEqual(resp.context["job_failed_today_count"], 1)
        for label, key in (("Job falliti oggi", "job_failed_today_count"), ("Job missing", "job_missing_count")):
            href = _href_for(html, label)
            lst = self.client.get(href)
            self.assertEqual(lst.status_code, 200)
            self.assertEqual(len(lst.context["job_rows"]), resp.context[key], label)
        lst = self.client.get(_href_for(html, "Job falliti oggi"))
        self.assertEqual([r["job"].pk for r in lst.context["job_rows"]], [self.job_ko.pk])

    def test_system_status_severity_rows_are_links(self):
        resp = self.client.get(reverse("monitoring_admin:system_status"))
        html = resp.content.decode()
        href = _href_for(html, "Critiche")
        self.assertEqual(self._count_issues(href), resp.context["severity_counts"].get("critical", 0))
        href = _href_for(html, "Totale aperte")
        self.assertEqual(self._count_issues(href), resp.context["open_issues_count"])

    def test_schedules_status_filter_matches_counts(self):
        rows = [
            {"name": "a", "status": "ok"}, {"name": "b", "status": "errore"}, {"name": "c", "status": "errore"},
        ]
        full = [dict(r, func="f", cadence="", last_run=None, last_success=False, failures_24h=0,
                     registered=True, next_run=None, status_label=r["status"], last_error="", enabled=True)
                for r in rows]
        with mock.patch("monitoring.schedule_health.schedule_rows", return_value=full), \
                mock.patch("monitoring.schedule_health.cluster_status", return_value={"alive": True, "last_task": None}):
            resp = self.client.get(reverse("monitoring_admin:schedule_list"))
            href = _href_for(resp.content.decode(), "Ultimo run fallito")
            self.assertIn("stato=errore", href)
            filtered = self.client.get(href)
        self.assertEqual(len(filtered.context["rows"]), resp.context["summary"]["counts"]["errore"])
        self.assertEqual(len(filtered.context["rows"]), 2)

    def test_issue_detail_kpis_anchor_sections(self):
        resp = self.client.get(reverse("monitoring_admin:issue_detail", args=[self.i1.pk]))
        html = resp.content.decode()
        self.assertEqual(_href_for(html, "Occorrenze"), "#occorrenze")
        self.assertIn('id="occorrenze"', html)
        self.assertIn('id="utenti"', html)
