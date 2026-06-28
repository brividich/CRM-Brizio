"""Test per ai_assistant.tasks.run_rag_quality_alert (alert qualità RAG SGI)."""
from __future__ import annotations

import json
import unittest.mock as mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from ai_assistant import tasks


def _fake_eval(summary):
    """side_effect per call_command: scrive il JSON di ai_eval su stdout passato."""
    def _inner(*args, **kwargs):
        kwargs["stdout"].write(json.dumps({"summary": summary}))
    return _inner


@override_settings(OLLAMA_RAG_SGI_MIN_RECALL=0.7)
class RagQualityAlertTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_alert_when_recall_below_threshold(self):
        with mock.patch("django.core.management.call_command",
                        side_effect=_fake_eval({"sgi_chunks": 50, "recall_hits": 1, "cases": 4})), \
             mock.patch("monitoring.health.emit_monitoring_alert", return_value=True) as emit:
            result = tasks.run_rag_quality_alert()
        self.assertTrue(result["degraded"])
        self.assertTrue(result["emailed"])
        self.assertAlmostEqual(result["recall_pct"], 0.25)
        emit.assert_called_once()

    def test_alert_when_index_empty(self):
        with mock.patch("django.core.management.call_command",
                        side_effect=_fake_eval({"sgi_chunks": 0, "recall_hits": 4, "cases": 4})), \
             mock.patch("monitoring.health.emit_monitoring_alert", return_value=True) as emit:
            result = tasks.run_rag_quality_alert()
        self.assertTrue(result["degraded"])
        emit.assert_called_once()

    def test_no_alert_when_healthy(self):
        with mock.patch("django.core.management.call_command",
                        side_effect=_fake_eval({"sgi_chunks": 50, "recall_hits": 4, "cases": 4})), \
             mock.patch("monitoring.health.emit_monitoring_alert", return_value=True) as emit:
            result = tasks.run_rag_quality_alert()
        self.assertFalse(result["degraded"])
        emit.assert_not_called()

    def test_failsafe_when_eval_raises(self):
        with mock.patch("django.core.management.call_command", side_effect=RuntimeError("boom")), \
             mock.patch("monitoring.health.emit_monitoring_alert", return_value=True) as emit:
            result = tasks.run_rag_quality_alert()
        # eval non eseguibile = problema -> alert (fail-safe: non solleva)
        self.assertTrue(result["degraded"])
        emit.assert_called_once()

    def test_creates_issue_on_degrade_and_resolves_on_recovery(self):
        from monitoring.models import Issue

        with mock.patch("django.core.management.call_command",
                        side_effect=_fake_eval({"sgi_chunks": 0, "recall_hits": 4, "cases": 4})), \
             mock.patch("monitoring.health.emit_monitoring_alert", return_value=False):
            tasks.run_rag_quality_alert()
        open_data = Issue.objects.exclude(status=Issue.Status.RESOLVED).filter(category=Issue.Category.DATA)
        self.assertEqual(open_data.count(), 1)
        self.assertEqual(open_data.first().severity, Issue.Severity.HIGH)  # sgi_chunks=0

        with mock.patch("django.core.management.call_command",
                        side_effect=_fake_eval({"sgi_chunks": 50, "recall_hits": 4, "cases": 4})), \
             mock.patch("monitoring.health.emit_monitoring_alert", return_value=False):
            tasks.run_rag_quality_alert()
        self.assertEqual(
            Issue.objects.exclude(status=Issue.Status.RESOLVED).filter(category=Issue.Category.DATA).count(),
            0,
        )
