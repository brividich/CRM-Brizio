"""Spiegazione alert e sintesi del giorno con l'AI locale (simulata) + Panoramica IT."""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord, SecurityAiInteractionLog, SecurityAlert, SecurityEventRecord, SecurityReport, SecurityReportMetric, SecuritySource, Severity,
)
from security.services.ai_explain import alert_context, explain_alert
from security.services.overview import area_cards, attention_items, overall
from security.templatetags.security_i18n import ai_markdown

AI_TEXT = "**Cosa è successo**\nIl firewall ha bloccato molti accessi.\n**Cosa fare adesso**\n- Controlla l'IP\n- Cambia la password"
CHAT = "ai_assistant.services.chat_with_ollama"


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="ai_admin", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Casella", source_type="email", vendor="mailbox")

    def _alert(self, **payload):
        event = SecurityEventRecord.objects.create(source=self.source, event_type="watchguard_alert_candidate", severity=Severity.HIGH,
                                                   fingerprint="f", dedup_hash="h1", payload=payload, decision_trace={"decision": "alert", "rule": "vpn_denied"})
        return SecurityAlert.objects.create(source=self.source, event=event, title="Accessi negati ripetuti", severity=Severity.HIGH, dedup_hash="h1")


class ExplainAlertTests(_Base):
    def test_context_is_minimal_and_never_contains_the_mail_body(self):
        alert = self._alert(source_ip="198.51.100.7", count=40, body="TESTO DELLA MAIL SEGRETO", raw="x" * 50)
        context = alert_context(alert)
        self.assertIn("198.51.100.7", context)
        self.assertIn("vpn_denied", context)
        self.assertNotIn("SEGRETO", context)
        self.assertNotIn("xxxxxxxxxx", context)

    def test_answer_is_logged_and_cached(self):
        alert = self._alert(count=3)
        with mock.patch(CHAT, return_value=SimpleNamespace(content=AI_TEXT)) as chat:
            first = explain_alert(alert, user=self.user)
            second = explain_alert(alert, user=self.user)
        self.assertTrue(first["ok"])
        self.assertTrue(second["cached"])
        self.assertEqual(chat.call_count, 1)
        log = SecurityAiInteractionLog.objects.get()
        self.assertEqual((log.action, log.status, log.object_id), ("alert_explain", "ok", str(alert.pk)))

    def test_ai_down_is_explained_not_raised_and_not_cached(self):
        alert = self._alert()
        with mock.patch(CHAT, side_effect=RuntimeError("OLLAMA_BASE_URL non configurato.")):
            result = explain_alert(alert)
        self.assertFalse(result["ok"])
        self.assertIn("OLLAMA_BASE_URL", result["error"])
        with mock.patch(CHAT, return_value=SimpleNamespace(content=AI_TEXT)) as chat:
            explain_alert(alert)
        self.assertEqual(chat.call_count, 1)

    def test_page_button_and_htmx_answer(self):
        alert = self._alert()
        self.assertContains(self.client.get(reverse("security:alert_detail", args=[alert.pk])), "Spiega con l'AI")
        with mock.patch(CHAT, return_value=SimpleNamespace(content=AI_TEXT)):
            response = self.client.post(reverse("security:alert_explain", args=[alert.pk]), HTTP_HX_REQUEST="true")
        self.assertContains(response, "<strong>Cosa è successo</strong>")
        self.assertContains(response, "<li>Controlla l&#x27;IP</li>")
        alert.refresh_from_db()
        self.assertEqual(alert.status, "new")  # spiegare non cambia l'alert

    def test_markdown_is_escaped_before_formatting(self):
        html = ai_markdown("**ok** <script>alert(1)</script>\n- uno")
        self.assertIn("<strong>ok</strong>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<li>uno</li>", html)


class OverviewTests(_Base):
    def _epdr(self, **metrics):
        report = SecurityReport.objects.create(source=self.source, report_type="watchguard_epdr_executive_report", title="EPDR", report_date=timezone.localdate(), parser_name="p")
        for name, value in metrics.items():
            SecurityReportMetric.objects.create(report=report, name=name, value=value)

    def test_items_from_every_area_sorted_by_severity(self):
        self._alert()
        BackupJobRecord.objects.create(source=self.source, job_name="JOB-X", status="failed", started_at=timezone.now(), dedup_hash="b")
        self._epdr(watchguard_epdr_unprotected_endpoints=7, watchguard_epdr_unmanaged_computers=5, watchguard_epdr_license_days_left=30)
        items = attention_items()
        titles = [item["title"] for item in items]
        self.assertIn("Accessi negati ripetuti", titles)
        self.assertIn("Backup fallito: JOB-X", titles)
        self.assertIn("7 computer senza protezione attiva", titles)
        self.assertIn("Licenza Endpoint Security in scadenza tra 30 giorni", titles)
        levels = [item["level"] for item in items]
        self.assertEqual(levels, sorted(levels, key=lambda lvl: {"critical": 0, "high": 1, "warning": 2, "info": 3}[lvl]))
        self.assertEqual(overall(items)[0], "high")
        cards = {card["code"]: card for card in area_cards(items)}
        self.assertEqual(cards["backup"]["state"], "high")
        self.assertEqual(cards["vulns"]["state"], "nodata")

    def test_old_imported_failures_are_not_news_and_license_goes_to_its_area(self):
        old = timezone.now() - timezone.timedelta(days=20)
        BackupJobRecord.objects.create(source=self.source, job_name="JOB-VECCHIO", status="failed", started_at=old, dedup_hash="old")
        for i in range(3):
            BackupJobRecord.objects.create(source=self.source, job_name="JOB-X", status="failed", started_at=timezone.now(), dedup_hash=f"n{i}")
        self._epdr(watchguard_epdr_license_days_left=30)
        items = attention_items()
        titles = [item["title"] for item in items]
        self.assertNotIn("Backup fallito: JOB-VECCHIO", titles)
        self.assertEqual(titles.count("Backup fallito: JOB-X"), 1)
        cards = {card["code"]: card for card in area_cards(items)}
        self.assertEqual(cards["endpoint"]["state"], "warning")
        self.assertEqual(cards["firewall"]["state"], "nodata")

    def test_nothing_open_is_reassuring(self):
        self.assertEqual(overall([])[0], "ok")
        response = self.client.get(reverse("security:dashboard"))
        self.assertContains(response, "Nessun problema aperto")
        self.assertContains(response, "Niente da gestire")

    def test_dashboard_and_brief(self):
        self._alert()
        response = self.client.get(reverse("security:dashboard"))
        self.assertContains(response, "Da guardare adesso")
        self.assertContains(response, "Accessi negati ripetuti")
        with mock.patch(CHAT, return_value=SimpleNamespace(content="Oggi: un alert sugli accessi.")) as chat:
            brief = self.client.post(reverse("security:overview_brief"), HTTP_HX_REQUEST="true")
        self.assertContains(brief, "Oggi: un alert sugli accessi.")
        cache.clear()
        with mock.patch(CHAT, return_value=SimpleNamespace(content="Backup fallito (*tool: Backup*) da controllare.")):
            brief = self.client.post(reverse("security:overview_brief"), HTTP_HX_REQUEST="true")
        self.assertContains(brief, "Backup fallito da controllare.")
        self.assertIn("Accessi negati ripetuti", chat.call_args.kwargs["runtime_context"])
