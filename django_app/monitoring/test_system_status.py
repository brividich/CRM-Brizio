"""Smoke test della pagina 'Stato sistema' (centrale di comando monitoring)."""
from __future__ import annotations

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
