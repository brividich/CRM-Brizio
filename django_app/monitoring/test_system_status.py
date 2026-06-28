"""Smoke test della pagina 'Stato sistema' (centrale di comando monitoring)."""
from __future__ import annotations

import unittest.mock as mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from monitoring.models import Issue


class SystemStatusViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="admin_ss", email="admin_ss@example.test", password="x"
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_renders_for_admin(self):
        resp = self.client.get(reverse("monitoring_admin:system_status"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Stato sistema")
        self.assertContains(resp, "Assistente AI")
        self.assertContains(resp, "Servizi")
        # senza Issue AI aperte l'assistente risulta operativo
        self.assertContains(resp, "OPERATIVO")

    def test_open_ai_issue_shows_degraded(self):
        Issue.objects.create(
            code="INC-TEST-0001", title="AI · ollama_chat: FAIL", category=Issue.Category.INTEGRATION,
            severity=Issue.Severity.HIGH, source=Issue.Source.SYSTEM_WATCHDOG,
            status=Issue.Status.NEW, fingerprint="x" * 10, current_url="check:ai_ollama_chat",
        )
        resp = self.client.get(reverse("monitoring_admin:system_status"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "DEGRADATO")
        self.assertContains(resp, "ollama_chat")


class SystemActionViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="admin_sa", email="admin_sa@example.test", password="x"
        )
        self.client = Client()
        self.client.force_login(self.admin)
        self.url = reverse("monitoring_admin:system_action")

    def test_ai_verify_enqueues_task(self):
        with mock.patch("django_q.tasks.async_task") as async_task:
            resp = self.client.post(self.url, {"action": "ai_verify"})
        self.assertEqual(resp.status_code, 302)
        async_task.assert_called_once()
        self.assertEqual(async_task.call_args.args[0], "monitoring.tasks.run_ai_readiness_alert")

    def test_reindex_enqueues_task(self):
        with mock.patch("django_q.tasks.async_task") as async_task:
            resp = self.client.post(self.url, {"action": "ai_reindex"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(async_task.call_args.args[0], "ai_assistant.tasks.run_index_sgi_documents")

    def test_register_schedules_runs_command(self):
        with mock.patch("django.core.management.call_command") as call_command:
            resp = self.client.post(self.url, {"action": "register_schedules"})
        self.assertEqual(resp.status_code, 302)
        call_command.assert_called_once_with("setup_q_schedules")

    def test_unknown_action_redirects(self):
        resp = self.client.post(self.url, {"action": "nope"})
        self.assertEqual(resp.status_code, 302)

    def test_get_not_allowed(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)
