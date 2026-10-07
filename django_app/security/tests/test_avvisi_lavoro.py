"""Impostazioni avvisi, avvisi programmati (una volta sola), report automatico, Il mio lavoro, ricerca, scheda PC."""
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    SecurityAlert,
    SecurityAsset,
    SecurityNotificationChannel,
    SecurityNotificationLog,
    SecurityRemediationTicket,
    SecuritySource,
    SecurityVulnerabilityFinding,
    Severity,
    SourceType,
    Status,
)
from security.services import incidents as inc_svc
from security.services import proactive_alerts, soc_settings
from security.services.configuration import set_setting


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="soc@example.test")
class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_av_user", is_staff=True, is_superuser=True, email="me@example.test")
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Fonte sintetica", vendor="Demo", source_type=SourceType.EMAIL)
        self.channel = SecurityNotificationChannel.objects.create(name="SOC mail", channel_type="email", recipients="soc@example.test")
        self.n = 0

    def enable(self, section):
        prefix = {"incidenti": "avvisi.incidenti", "backup": "avvisi.backup", "report": "report.auto"}[section]
        set_setting(f"{prefix}.attivo", True)
        set_setting(f"{prefix}.canali", [self.channel.pk])

    def backup(self, device, status, days_ago):
        self.n += 1
        return BackupJobRecord.objects.create(source=self.source, job_name="Job sintetico", status=status,
                                              completed_at=timezone.now() - timedelta(days=days_ago),
                                              payload={"device_name": device}, dedup_hash=f"b{self.n}")


class SettingsTests(_Base):
    def test_defaults_are_off(self):
        self.assertFalse(soc_settings.value("avvisi.incidenti.attivo"))
        self.assertEqual(soc_settings.value("avvisi.backup.giorni"), 3)

    def test_page_saves_and_requires_a_channel(self):
        url = reverse("security:soc_settings")
        self.assertContains(self.client.get(url), "Scadenze incidenti NIS2 e GDPR")
        bad = self.client.post(url, {"avvisi__incidenti__attivo": "on", "avvisi__incidenti__anticipo_ore": "6",
                                     "avvisi__backup__giorni": "3", "report__auto__frequenza": "weekly"})
        self.assertContains(bad, "scegli almeno un canale")
        self.assertFalse(soc_settings.value("avvisi.incidenti.attivo"))
        ok = self.client.post(url, {"avvisi__incidenti__attivo": "on", "avvisi__incidenti__anticipo_ore": "12",
                                    "avvisi__incidenti__canali": [str(self.channel.pk)],
                                    "avvisi__backup__giorni": "5", "report__auto__frequenza": "monthly"})
        self.assertRedirects(ok, url)
        self.assertTrue(soc_settings.value("avvisi.incidenti.attivo"))
        self.assertEqual(soc_settings.value("avvisi.incidenti.anticipo_ore"), 12)
        self.assertEqual(soc_settings.value("avvisi.incidenti.canali"), [self.channel.pk])
        self.assertEqual(soc_settings.value("avvisi.backup.giorni"), 5)
        self.assertEqual(soc_settings.value("report.auto.frequenza"), "monthly")

    def test_viewer_cannot_save(self):
        viewer = get_user_model().objects.create(username="soc_viewer")
        self.client.force_login(viewer)
        with patch("security.views_work.can_view_security_center", return_value=True), \
                patch("security.views_work.can_manage_security_config", return_value=False), \
                patch("core.middleware.ACLMiddleware.__call__", lambda self, request: self.get_response(request), create=True):
            self.assertContains(self.client.get(reverse("security:soc_settings")), "non modificarle")
            response = self.client.post(reverse("security:soc_settings"), {"avvisi__backup__giorni": "9"})
        self.assertIn(response.status_code, (302, 403))
        self.assertEqual(soc_settings.value("avvisi.backup.giorni"), 3)


class ScheduledAlertTests(_Base):
    def test_off_sends_nothing(self):
        inc_svc.create_incident(self.user, title="Sintetico", detected_at=timezone.now() - timedelta(hours=30), is_significant=True)
        self.assertEqual(proactive_alerts.check_incidents(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_incident_deadline_sent_once_per_state(self):
        self.enable("incidenti")
        incident = inc_svc.create_incident(self.user, title="Ransomware sintetico", detected_at=timezone.now() - timedelta(hours=30), is_significant=True)
        self.assertEqual(proactive_alerts.check_incidents(), 1)  # pre-notifica scaduta; notifica 72 h ancora lontana
        self.assertIn("SCADUTA", mail.outbox[0].subject)
        self.assertIn(f"/soc/incidenti/{incident.pk}/", mail.outbox[0].body)
        self.assertEqual(proactive_alerts.check_incidents(), 0)  # nessun doppione
        self.assertEqual(len(mail.outbox), 1)

    def test_backup_stale_and_rearm_after_success(self):
        self.enable("backup")
        self.backup("PC-SINT-01", "completed", 6)
        self.assertEqual(proactive_alerts.check_backups(), 1)
        self.assertIn("Backup fermo: PC-SINT-01", mail.outbox[0].subject)
        self.assertEqual(proactive_alerts.check_backups(), 0)
        self.backup("PC-SINT-01", "completed", 0)  # rientrato: niente avviso
        self.assertEqual(proactive_alerts.check_backups(), 0)
        self.backup("PC-SINT-01", "failed", 0)
        self.assertEqual(proactive_alerts.check_backups(), 1)
        self.assertIn("Backup fallito", mail.outbox[-1].subject)

    def test_weekly_report_on_monday_with_pdf(self):
        self.enable("report")
        tz = timezone.get_current_timezone()
        monday = timezone.make_aware(datetime(2026, 10, 5, 8, 0), tz)
        sunday = timezone.make_aware(datetime(2026, 10, 4, 8, 0), tz)
        early = timezone.make_aware(datetime(2026, 10, 5, 6, 0), tz)
        self.assertEqual(proactive_alerts.check_report(sunday), 0)
        self.assertEqual(proactive_alerts.check_report(early), 0)
        self.assertEqual(proactive_alerts.check_report(monday), 1)
        message = mail.outbox[0]
        name, content, mime = message.attachments[0]
        self.assertEqual(mime, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertEqual(proactive_alerts.check_report(monday + timedelta(hours=2)), 0)

    def test_broken_channel_is_logged_not_raised(self):
        self.enable("incidenti")
        inc_svc.create_incident(self.user, title="Sintetico", detected_at=timezone.now() - timedelta(hours=30), is_significant=True)
        with patch("security.services.notifications._send_email", side_effect=RuntimeError("smtp giù")):
            self.assertEqual(proactive_alerts.check_incidents(), 0)
        log = SecurityNotificationLog.objects.get()
        self.assertEqual(log.outcome, "failed")
        # Un invio fallito non conta come inviato: al giro dopo riprova.
        self.assertEqual(proactive_alerts.check_incidents(), 1)


class WorkPagesTests(_Base):
    def test_my_work(self):
        SecurityRemediationTicket.objects.create(source=self.source, title="Ticket mio", assignee=self.user, dedup_hash="t1")
        SecurityRemediationTicket.objects.create(source=self.source, title="Ticket di nessuno", dedup_hash="t2")
        inc_svc.create_incident(self.user, title="Incidente mio", owner=self.user, is_significant=True)
        page = self.client.get(reverse("security:my_work"))
        self.assertContains(page, "Ticket mio")
        self.assertNotContains(page, "Ticket di nessuno")
        self.assertContains(page, "Incidente mio")
        self.assertContains(page, "1 ticket senza responsabile")

    def test_search_groups(self):
        SecurityAlert.objects.create(source=self.source, title="Malware su PC-CERCA-01", severity=Severity.HIGH, status=Status.OPEN, dedup_hash="s1")
        self.backup("PC-CERCA-01", "completed", 1)
        SecurityVulnerabilityFinding.objects.create(source=self.source, cve="CVE-2026-12345", affected_product="Browser", cvss=8.1,
                                                    severity=Severity.HIGH, dedup_hash="v1")
        page = self.client.get(reverse("security:search") + "?q=cerca-01")
        self.assertContains(page, "Malware su PC-CERCA-01")
        self.assertContains(page, "/soc/pc/?nome=PC-CERCA-01")
        self.assertContains(self.client.get(reverse("security:search") + "?q=CVE-2026-12345"), "Browser")
        self.assertContains(self.client.get(reverse("security:search") + "?q=x"), "almeno due caratteri")

    def test_pc_page_merges_sources(self):
        asset = SecurityAsset.objects.create(source=self.source, hostname="PC-UNICO-01")
        SecurityVulnerabilityFinding.objects.create(source=self.source, asset=asset, cve="CVE-2026-9999", affected_product="Office",
                                                    cvss=9.1, severity=Severity.CRITICAL, dedup_hash="v2")
        self.backup("pc-unico-01", "failed", 0)
        page = self.client.get(reverse("security:pc_detail") + "?nome=PC-UNICO-01")
        self.assertContains(page, "CVE-2026-9999")
        self.assertContains(page, "Da gestire subito")
        self.assertContains(page, "Fallito")
        self.assertNotContains(page, "{#")
