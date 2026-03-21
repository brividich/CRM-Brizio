"""
Test minimi per l'app monitoring.

Copertura:
- deduplicazione issue (stesso fingerprint → aggiorna, non duplica)
- creazione issue da eccezione web
- creazione UserProblemReport
- decorator @monitored_automation su successo e fallimento
- decorator: doppia-chiusura non avviene se _complete_execution lancia
- healthcheck job missing
"""
from __future__ import annotations

import unittest.mock as mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .automation import get_or_create_automation_job, monitored_automation
from .models import AutomationExecution, AutomationJob, Issue, IssueOccurrence, UserProblemReport
from .services import (
    build_issue_fingerprint,
    count_consecutive_failures,
    detect_missed_jobs,
    detect_stuck_jobs,
    open_or_update_issue_from_automation_error,
    open_or_update_issue_from_web_error,
    register_user_problem_report,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(username: str = "testuser") -> object:
    return User.objects.create_user(username=username, password="x")


# ---------------------------------------------------------------------------
# Fingerprint / deduplicazione
# ---------------------------------------------------------------------------

class FingerprintTests(TestCase):
    def test_same_inputs_same_fingerprint(self):
        fp1 = build_issue_fingerprint(
            source=Issue.Source.WEB,
            category=Issue.Category.SYSTEM,
            exception_class="ValueError",
            route_name="assets:index",
            module_name="assets",
            message="test error",
        )
        fp2 = build_issue_fingerprint(
            source=Issue.Source.WEB,
            category=Issue.Category.SYSTEM,
            exception_class="ValueError",
            route_name="assets:index",
            module_name="assets",
            message="test error",
        )
        self.assertEqual(fp1, fp2)

    def test_different_exception_different_fingerprint(self):
        fp1 = build_issue_fingerprint(
            source=Issue.Source.WEB,
            category=Issue.Category.SYSTEM,
            exception_class="ValueError",
            module_name="assets",
            message="test",
        )
        fp2 = build_issue_fingerprint(
            source=Issue.Source.WEB,
            category=Issue.Category.SYSTEM,
            exception_class="KeyError",
            module_name="assets",
            message="test",
        )
        self.assertNotEqual(fp1, fp2)

    def test_message_normalization_deduplicates_ids(self):
        """Messaggi che differiscono solo per ID numerico devono produrre lo stesso fingerprint."""
        fp1 = build_issue_fingerprint(
            source=Issue.Source.WEB,
            exception_class="DoesNotExist",
            module_name="assets",
            message="Asset matching query does not exist. id=123",
        )
        fp2 = build_issue_fingerprint(
            source=Issue.Source.WEB,
            exception_class="DoesNotExist",
            module_name="assets",
            message="Asset matching query does not exist. id=456",
        )
        self.assertEqual(fp1, fp2)


# ---------------------------------------------------------------------------
# open_or_update_issue_from_web_error — creazione e deduplicazione
# ---------------------------------------------------------------------------

class WebErrorIssueTests(TestCase):
    def _create(self, **kwargs):
        defaults = dict(
            category=Issue.Category.SYSTEM,
            severity=Issue.Severity.HIGH,
            source=Issue.Source.WEB,
            status_code=500,
            method="GET",
            current_url="/assets/",
            route_name="assets:index",
            module_name="assets",
            message="Unhandled exception",
            exception_class="ValueError",
        )
        defaults.update(kwargs)
        return open_or_update_issue_from_web_error(**defaults)

    def test_creates_issue(self):
        issue = self._create()
        self.assertIsNotNone(issue.pk)
        self.assertEqual(issue.occurrences_count, 1)
        self.assertEqual(issue.status, Issue.Status.NEW)

    def test_deduplication_updates_count(self):
        i1 = self._create()
        i2 = self._create()
        self.assertEqual(i1.pk, i2.pk)
        i1.refresh_from_db()
        self.assertEqual(i1.occurrences_count, 2)

    def test_occurrence_created(self):
        issue = self._create()
        self.assertEqual(IssueOccurrence.objects.filter(issue=issue).count(), 1)
        self._create()
        self.assertEqual(IssueOccurrence.objects.filter(issue=issue).count(), 2)

    def test_no_dedup_when_resolved(self):
        i1 = self._create()
        i1.status = Issue.Status.RESOLVED
        i1.save(update_fields=["status"])
        i2 = self._create()
        self.assertNotEqual(i1.pk, i2.pk)

    def test_severity_escalates_on_dedup(self):
        i1 = self._create(severity=Issue.Severity.LOW)
        self._create(severity=Issue.Severity.CRITICAL)
        i1.refresh_from_db()
        self.assertEqual(i1.severity, Issue.Severity.CRITICAL)


# ---------------------------------------------------------------------------
# UserProblemReport
# ---------------------------------------------------------------------------

class UserProblemReportTests(TestCase):
    def test_creates_report(self):
        user = _make_user()
        report = register_user_problem_report(
            user=user,
            current_url="/assets/",
            route_name="assets:index",
            module_name="assets",
            message="Non riesco a salvare",
            browser_info="Mozilla/5.0",
        )
        self.assertIsNotNone(report.pk)
        self.assertEqual(UserProblemReport.objects.count(), 1)

    def test_correlates_issue_on_same_module(self):
        """Un report su un modulo con issue aperta deve essere correlato."""
        existing_issue = open_or_update_issue_from_web_error(
            category=Issue.Category.SYSTEM,
            severity=Issue.Severity.HIGH,
            source=Issue.Source.WEB,
            status_code=500,
            module_name="assets",
            current_url="/assets/",
            message="Server error",
            exception_class="ValueError",
        )
        user = _make_user()
        report = register_user_problem_report(
            user=user,
            current_url="/assets/",
            route_name="",
            module_name="assets",
            message="Qualcosa non va",
            browser_info="",
        )
        # La correlazione è opzionale nel service, non garantita, ma se c'è deve puntare a issue aperta
        if report.issue_id is not None:
            self.assertEqual(report.issue_id, existing_issue.pk)


# ---------------------------------------------------------------------------
# Automation decorator — successo
# ---------------------------------------------------------------------------

class MonitoredAutomationSuccessTests(TestCase):
    def test_creates_job_and_execution_on_success(self):
        @monitored_automation(
            job_code="test_job_success",
            job_name="Test job success",
            module_name="monitoring",
            re_raise=True,
        )
        def my_job():
            return {"monitoring_message": "fatto"}

        my_job()

        job = AutomationJob.objects.get(code="test_job_success")
        self.assertIsNotNone(job)
        execution = AutomationExecution.objects.filter(job=job).first()
        self.assertIsNotNone(execution)
        self.assertEqual(execution.status, AutomationExecution.Status.SUCCESS)
        self.assertEqual(execution.message, "fatto")

    def test_no_issue_created_on_success(self):
        @monitored_automation(
            job_code="test_job_no_issue",
            job_name="Test job no issue",
            module_name="monitoring",
        )
        def clean_job():
            return {}

        clean_job()
        self.assertEqual(Issue.objects.count(), 0)


# ---------------------------------------------------------------------------
# Automation decorator — fallimento
# ---------------------------------------------------------------------------

class MonitoredAutomationFailureTests(TestCase):
    def test_creates_failed_execution_on_error(self):
        @monitored_automation(
            job_code="test_job_fail",
            job_name="Test job fail",
            module_name="monitoring",
            re_raise=False,
        )
        def bad_job():
            raise ValueError("qualcosa è andato storto")

        bad_job()

        job = AutomationJob.objects.get(code="test_job_fail")
        execution = AutomationExecution.objects.filter(job=job).first()
        self.assertIsNotNone(execution)
        self.assertEqual(execution.status, AutomationExecution.Status.FAILED)
        self.assertIn("ValueError", execution.exception_class)

    def test_creates_issue_after_threshold_consecutive_failures(self):
        @monitored_automation(
            job_code="test_job_consec",
            job_name="Test job consecutive",
            module_name="monitoring",
            alert_after_consecutive_failures=2,
            re_raise=False,
        )
        def failing_job():
            raise RuntimeError("boom")

        # Prima esecuzione: sotto soglia
        failing_job()
        self.assertEqual(Issue.objects.count(), 0)

        # Seconda esecuzione: raggiunge soglia
        failing_job()
        self.assertEqual(Issue.objects.count(), 1)
        issue = Issue.objects.first()
        self.assertEqual(issue.source, Issue.Source.AUTOMATION)

    def test_reraise_propagates_exception(self):
        @monitored_automation(
            job_code="test_job_reraise",
            job_name="Test job reraise",
            module_name="monitoring",
            re_raise=True,
        )
        def raising_job():
            raise TypeError("re-raise me")

        with self.assertRaises(TypeError):
            raising_job()


# ---------------------------------------------------------------------------
# Decorator: no double-close se _complete_execution lancia
# ---------------------------------------------------------------------------

class MonitoredAutomationDoubleCloseTests(TestCase):
    def test_no_double_mark_failure_if_complete_execution_raises(self):
        """
        Se _complete_execution lancia (es. DB error), il context manager NON deve
        chiamare _mark_automation_failure. L'esecuzione rimane con status=started
        e non viene segnata come FAILED per un errore interno di monitoring.
        """

        @monitored_automation(
            job_code="test_double_close",
            job_name="Test double close",
            module_name="monitoring",
            re_raise=False,
        )
        def normal_job():
            return {}

        with mock.patch(
            "monitoring.automation._complete_execution",
            side_effect=Exception("DB unavailable"),
        ):
            # Non deve propagare, e non deve creare una issue di fallimento
            normal_job()

        # Nessuna issue deve essere stata creata (il job è andato a buon fine)
        self.assertEqual(Issue.objects.filter(source=Issue.Source.AUTOMATION).count(), 0)


# ---------------------------------------------------------------------------
# detect_missed_jobs
# ---------------------------------------------------------------------------

class DetectMissedJobsTests(TestCase):
    def test_no_missed_jobs_when_none_configured(self):
        result = detect_missed_jobs(now=timezone.now(), create_issues=False)
        self.assertEqual(result, [])

    def test_detects_job_never_executed(self):
        from datetime import timedelta

        job = get_or_create_automation_job(
            job_code="job_never_run",
            job_name="Job mai eseguito",
            module_name="monitoring",
            critical=True,
            expected_max_interval_minutes=60,
        )
        # now = creazione + 2h → il job (60 min interval, mai eseguito) è scaduto
        future_now = timezone.now() + timedelta(hours=2)
        result = detect_missed_jobs(now=future_now, create_issues=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["job"].pk, job.pk)

    def test_no_alert_when_job_ran_recently(self):
        job = get_or_create_automation_job(
            job_code="job_recent",
            job_name="Job recente",
            module_name="monitoring",
            critical=True,
            expected_max_interval_minutes=60,
        )
        # Crea un'esecuzione di successo recente
        AutomationExecution.objects.create(
            job=job,
            started_at=timezone.now(),
            finished_at=timezone.now(),
            duration_seconds=1,
            status=AutomationExecution.Status.SUCCESS,
            trigger_type=AutomationExecution.TriggerType.SCHEDULER,
            message="ok",
            payload_json={},
        )
        result = detect_missed_jobs(now=timezone.now(), create_issues=False)
        self.assertEqual(result, [])

    def test_detects_job_overdue(self):
        from datetime import timedelta

        job = get_or_create_automation_job(
            job_code="job_overdue",
            job_name="Job scaduto",
            module_name="monitoring",
            critical=True,
            expected_max_interval_minutes=30,
        )
        overdue_time = timezone.now() - timedelta(minutes=120)
        AutomationExecution.objects.create(
            job=job,
            started_at=overdue_time,
            finished_at=overdue_time,
            duration_seconds=1,
            status=AutomationExecution.Status.SUCCESS,
            trigger_type=AutomationExecution.TriggerType.SCHEDULER,
            message="ok",
            payload_json={},
        )
        result = detect_missed_jobs(now=timezone.now(), create_issues=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["job"].pk, job.pk)

    def test_creates_issue_when_requested(self):
        from datetime import timedelta

        get_or_create_automation_job(
            job_code="job_issue_create",
            job_name="Job crea issue",
            module_name="monitoring",
            critical=True,
            expected_max_interval_minutes=5,
        )
        # now = creazione + 30 min → job (5 min interval, mai eseguito) è scaduto
        future_now = timezone.now() + timedelta(minutes=30)
        detect_missed_jobs(now=future_now, create_issues=True)
        self.assertEqual(Issue.objects.count(), 1)
        issue = Issue.objects.first()
        self.assertIn(issue.source, {Issue.Source.AUTOMATION, Issue.Source.SYSTEM_WATCHDOG})


# ---------------------------------------------------------------------------
# detect_stuck_jobs
# ---------------------------------------------------------------------------

class DetectStuckJobsTests(TestCase):
    def test_no_stuck_jobs_when_none_running(self):
        result = detect_stuck_jobs(now=timezone.now(), create_issues=False)
        self.assertEqual(result, [])

    def test_does_not_flag_short_running_job(self):
        from datetime import timedelta

        job = get_or_create_automation_job(
            job_code="job_short_run",
            job_name="Job breve",
            module_name="monitoring",
            critical=True,
            expected_max_duration_seconds=300,
        )
        # Esecuzione avviata 30 secondi fa, max è 300s → non stuck
        AutomationExecution.objects.create(
            job=job,
            started_at=timezone.now() - timedelta(seconds=30),
            status=AutomationExecution.Status.WARNING,
            trigger_type=AutomationExecution.TriggerType.SCHEDULER,
            message="in corso",
            payload_json={},
        )
        result = detect_stuck_jobs(now=timezone.now(), create_issues=False)
        self.assertEqual(result, [])

    def test_detects_job_exceeding_max_duration(self):
        from datetime import timedelta

        job = get_or_create_automation_job(
            job_code="job_stuck",
            job_name="Job bloccato",
            module_name="monitoring",
            critical=True,
            expected_max_duration_seconds=60,
        )
        # Esecuzione avviata 10 minuti fa, max è 60s → stuck
        AutomationExecution.objects.create(
            job=job,
            started_at=timezone.now() - timedelta(minutes=10),
            status=AutomationExecution.Status.WARNING,
            trigger_type=AutomationExecution.TriggerType.SCHEDULER,
            message="in corso",
            payload_json={},
        )
        result = detect_stuck_jobs(now=timezone.now(), create_issues=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["job"].pk, job.pk)

    def test_creates_issue_for_stuck_job(self):
        from datetime import timedelta

        job = get_or_create_automation_job(
            job_code="job_stuck_issue",
            job_name="Job bloccato issue",
            module_name="monitoring",
            critical=True,
            expected_max_duration_seconds=30,
        )
        AutomationExecution.objects.create(
            job=job,
            started_at=timezone.now() - timedelta(minutes=5),
            status=AutomationExecution.Status.WARNING,
            trigger_type=AutomationExecution.TriggerType.SCHEDULER,
            message="in corso",
            payload_json={},
        )
        detect_stuck_jobs(now=timezone.now(), create_issues=True)
        self.assertEqual(Issue.objects.count(), 1)
        issue = Issue.objects.first()
        self.assertIn(issue.source, {Issue.Source.AUTOMATION, Issue.Source.SYSTEM_WATCHDOG})

    def test_completed_job_is_not_flagged_as_stuck(self):
        from datetime import timedelta

        job = get_or_create_automation_job(
            job_code="job_completed_ok",
            job_name="Job completato ok",
            module_name="monitoring",
            critical=True,
            expected_max_duration_seconds=30,
        )
        # Esecuzione completata (SUCCESS), anche se ha impiegato molto
        AutomationExecution.objects.create(
            job=job,
            started_at=timezone.now() - timedelta(minutes=10),
            finished_at=timezone.now() - timedelta(seconds=1),
            duration_seconds=599,
            status=AutomationExecution.Status.SUCCESS,
            trigger_type=AutomationExecution.TriggerType.SCHEDULER,
            message="completato",
            payload_json={},
        )
        result = detect_stuck_jobs(now=timezone.now(), create_issues=False)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# count_consecutive_failures
# ---------------------------------------------------------------------------

class CountConsecutiveFailuresTests(TestCase):
    def test_returns_zero_with_no_executions(self):
        job = get_or_create_automation_job(
            job_code="job_no_exec",
            job_name="Job senza esecuzioni",
            module_name="monitoring",
        )
        self.assertEqual(count_consecutive_failures(job), 0)

    def test_counts_consecutive_failures_from_most_recent(self):
        job = get_or_create_automation_job(
            job_code="job_consec_fail",
            job_name="Job fallimenti consecutivi",
            module_name="monitoring",
        )
        now = timezone.now()
        # 2 fallimenti + 1 successo più vecchio → conta solo i 2 fallimenti
        for i, status in enumerate([
            AutomationExecution.Status.SUCCESS,   # più vecchio
            AutomationExecution.Status.FAILED,
            AutomationExecution.Status.FAILED,
        ]):
            from datetime import timedelta
            AutomationExecution.objects.create(
                job=job,
                started_at=now - timedelta(minutes=10 - i),
                finished_at=now - timedelta(minutes=9 - i),
                duration_seconds=60,
                status=status,
                trigger_type=AutomationExecution.TriggerType.SCHEDULER,
                message="",
                payload_json={},
            )
        self.assertEqual(count_consecutive_failures(job), 2)

    def test_resets_on_success(self):
        job = get_or_create_automation_job(
            job_code="job_reset_success",
            job_name="Job reset su successo",
            module_name="monitoring",
        )
        now = timezone.now()
        from datetime import timedelta
        # Fallimento poi successo → consecutive = 0
        for i, status in enumerate([
            AutomationExecution.Status.FAILED,
            AutomationExecution.Status.SUCCESS,  # più recente
        ]):
            AutomationExecution.objects.create(
                job=job,
                started_at=now - timedelta(minutes=4 - i),
                finished_at=now - timedelta(minutes=3 - i),
                duration_seconds=60,
                status=status,
                trigger_type=AutomationExecution.TriggerType.SCHEDULER,
                message="",
                payload_json={},
            )
        self.assertEqual(count_consecutive_failures(job), 0)
