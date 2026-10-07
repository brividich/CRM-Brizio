"""Barra di stato live, anteprime a pannello, azioni massive, filtri multipli e controlli AI del SOC."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    SecurityAlert,
    SecurityAsset,
    SecurityEventRecord,
    SecurityIncident,
    SecurityRemediationTicket,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.services import incidents as inc_svc


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="soc_live_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Fonte live", vendor="Demo", source_type=SourceType.EMAIL)
        self.n = 0

    def alert(self, severity=Severity.HIGH, title=None):
        self.n += 1
        return SecurityAlert.objects.create(source=self.source, title=title or f"Alert {self.n}", severity=severity, status=Status.OPEN, dedup_hash=f"a{self.n}")

    def ticket(self, **kw):
        self.n += 1
        return SecurityRemediationTicket.objects.create(source=self.source, title=kw.pop("title", f"Ticket {self.n}"), dedup_hash=f"t{self.n}", **kw)


class LiveStripTests(_Base):
    def test_strip_on_every_page_and_endpoint(self):
        self.alert(Severity.CRITICAL)
        page = self.client.get(reverse("security:tickets_list"))
        self.assertContains(page, 'data-live-url="/soc/stato/"')
        self.assertContains(page, "critici e alti")
        strip = self.client.get(reverse("security:live_strip"))
        self.assertContains(strip, "tone-critical")
        self.assertContains(strip, "/soc/alerts/?status=active&amp;severity=critical&amp;severity=high")


class PreviewTests(_Base):
    def test_all_previews_render(self):
        alert = self.alert()
        case = self.ticket(assignee=None)
        incident = inc_svc.create_incident(self.user, title="Incidente anteprima", is_significant=True)
        asset = SecurityAsset.objects.create(source=self.source, hostname="PC-ANTE-01")
        event = SecurityEventRecord.objects.create(source=self.source, asset=asset, event_type="endpoint_threat", fingerprint="f1", dedup_hash="d1", payload={"computer": "PC-ANTE-01"})
        BackupJobRecord.objects.create(source=self.source, job_name="Job", status="completed", completed_at=timezone.now(), payload={"device_name": "PC-ANTE-01"}, dedup_hash="b1")
        checks = [
            (reverse("security:preview", args=["alert", alert.pk]), "Spiega con l'AI"),
            (reverse("security:preview", args=["ticket", case.pk]), "Prendo io"),
            (reverse("security:preview", args=["incident", incident.pk]), "Pre-notifica CSIRT"),
            (reverse("security:preview", args=["event", event.pk]), "Minaccia endpoint"),
            (reverse("security:preview_pc") + "?nome=PC-ANTE-01", "Controlla con l'AI"),
        ]
        for url, text in checks:
            response = self.client.get(url)
            self.assertContains(response, text, msg_prefix=url)
            self.assertNotContains(response, "<html", msg_prefix=url)  # frammento, non pagina intera
        self.assertEqual(self.client.get(reverse("security:preview", args=["boh", 1])).status_code, 404)

    def test_lists_mark_rows_for_preview(self):
        alert = self.alert()
        self.assertContains(self.client.get(reverse("security:alerts_list")), f'data-preview="/soc/anteprima/alert/{alert.pk}/"')
        case = self.ticket()
        self.assertContains(self.client.get(reverse("security:tickets_list")), f'data-preview="/soc/anteprima/ticket/{case.pk}/"')


class MultiFilterTests(_Base):
    def test_severity_chips_combine(self):
        self.alert(Severity.CRITICAL, "Critico uno")
        self.alert(Severity.HIGH, "Alto uno")
        self.alert(Severity.LOW, "Basso uno")
        page = self.client.get(reverse("security:alerts_list") + "?severity=critical&severity=high")
        self.assertContains(page, "Critico uno")
        self.assertContains(page, "Alto uno")
        self.assertNotContains(page, "Basso uno")
        # Il chip «critico» attivo, cliccato, lascia solo «alto».
        self.assertContains(page, 'href="?severity=high"')


class BulkTests(_Base):
    def test_tickets_bulk_assign_and_close(self):
        t1, t2 = self.ticket(), self.ticket()
        self.client.post(reverse("security:tickets_bulk"), {"ticket_ids": [t1.pk, t2.pk], "action": "assign_me"})
        self.assertEqual(SecurityRemediationTicket.objects.filter(assignee=self.user).count(), 2)
        self.client.post(reverse("security:tickets_bulk"), {"ticket_ids": [t1.pk], "action": "status", "status": "closed"})
        t1.refresh_from_db()
        self.assertNotEqual(t1.status, "closed")  # senza esito non si chiude
        self.client.post(reverse("security:tickets_bulk"), {"ticket_ids": [t1.pk, t2.pk], "action": "status", "status": "closed", "reason": "Sistemato"})
        self.assertEqual(SecurityRemediationTicket.objects.filter(status="closed").count(), 2)

    def test_incidents_bulk(self):
        a = inc_svc.create_incident(self.user, title="A")
        b = inc_svc.create_incident(self.user, title="B")
        self.client.post(reverse("security:incidents_bulk"), {"incident_ids": [a.pk, b.pk], "action": "owner_me"})
        self.client.post(reverse("security:incidents_bulk"), {"incident_ids": [a.pk, b.pk], "action": "status", "status": "contained"})
        self.assertEqual(SecurityIncident.objects.filter(owner=self.user, status="contained").count(), 2)
        self.assertTrue(a.logs.filter(action="updated").exists())

    def test_events_bulk_ok_and_promote(self):
        events = [SecurityEventRecord.objects.create(source=self.source, event_type="vpn_auth_denied", fingerprint=f"f{i}", dedup_hash=f"e{i}", payload={"user": f"u{i}"}) for i in range(2)]
        self.client.post(reverse("security:events_bulk"), {"event_ids": [e.pk for e in events], "action": "promote"})
        self.assertFalse(SecurityAlert.objects.exists())  # serve il motivo
        self.client.post(reverse("security:events_bulk"), {"event_ids": [e.pk for e in events], "action": "promote", "reason": "Tentativi sospetti", "severity": "high"})
        self.assertGreaterEqual(SecurityAlert.objects.count(), 1)

    def test_backup_bulk_case(self):
        BackupJobRecord.objects.create(source=self.source, job_name="Job", status="failed", completed_at=timezone.now() - timedelta(days=1), payload={"device_name": "PC-1"}, dedup_hash="b1")
        response = self.client.post(reverse("security:backup_bulk_case"), {"devices": ["PC-1", "PC-2"]})
        case = SecurityRemediationTicket.objects.get()
        self.assertRedirects(response, reverse("security:case_detail", args=[case.pk]), fetch_redirect_response=False)
        self.assertEqual(case.assignee, self.user)
        self.assertEqual(case.tasks.count(), 2)
        self.assertIn("PC-2", case.description)


class AiCheckTests(_Base):
    def _fake(self, *args, **kwargs):
        return SimpleNamespace(content="**Cosa manca**\n- Causa non indicata")

    def test_incident_and_pc_checks_call_local_ai(self):
        incident = inc_svc.create_incident(self.user, title="Da controllare", is_significant=True)
        BackupJobRecord.objects.create(source=self.source, job_name="Job", status="failed", completed_at=timezone.now(), payload={"device_name": "PC-AI-01"}, dedup_hash="b9")
        with patch("ai_assistant.services.chat_with_ollama", side_effect=self._fake) as fake:
            r1 = self.client.post(reverse("security:incident_ai_check", args=[incident.pk]), HTTP_HX_REQUEST="true")
            r2 = self.client.post(reverse("security:pc_ai_check"), {"nome": "PC-AI-01"}, HTTP_HX_REQUEST="true")
        self.assertContains(r1, "Causa non indicata")
        self.assertContains(r2, "Causa non indicata")
        contexts = [call.kwargs["runtime_context"] for call in fake.call_args_list]
        self.assertIn("Causa: VUOTO", contexts[0])
        self.assertIn("Pre-notifica CSIRT (24 h)", contexts[0])
        self.assertIn("ultimo esito Fallito", contexts[1])

    def test_ai_down_is_a_message_not_an_error(self):
        incident = inc_svc.create_incident(self.user, title="AI spenta")
        with patch("ai_assistant.services.chat_with_ollama", side_effect=RuntimeError("connessione rifiutata")):
            response = self.client.post(reverse("security:incident_ai_check", args=[incident.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "L'AI locale non ha risposto")
