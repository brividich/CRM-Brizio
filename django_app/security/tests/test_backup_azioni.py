"""Pagina Backup: selezione multipla e pannello laterale anche per i job, azioni sugli alert (prendi, chiudi, ticket)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import BackupJobRecord, SecurityAlert, SecurityEventRecord, SecurityRemediationTicket, SecuritySource, SourceType, Status


class BackupAzioniTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="soc_backup_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Fonte backup", vendor="Demo", source_type=SourceType.EMAIL)
        now = timezone.now()
        for i, (job, device) in enumerate((("BCK-PC-1", "PC-1"), ("BCK-PC-2", "PC-2"), ("Backup Server", "SRV-1"))):
            BackupJobRecord.objects.create(source=self.source, job_name=job, status="failed", completed_at=now - timedelta(hours=i + 1),
                                           payload={"device_name": device}, dedup_hash=f"r{i}")
        self.a1 = self._alert("BCK-PC-1")
        self.a2 = self._alert("BCK-PC-2")
        self.altro = self._alert("Backup Server")

    def _alert(self, job):
        event = SecurityEventRecord.objects.create(source=self.source, event_type="backup_job", fingerprint=f"f-{job}", dedup_hash=f"e-{job}",
                                                   payload={"job_name": job, "status": "failed"})
        return SecurityAlert.objects.create(source=self.source, event=event, title=f"Backup job requires attention: {job}",
                                            status=Status.OPEN, dedup_hash=f"a-{job}")

    def test_page_has_job_selection_and_preview(self):
        page = self.client.get(reverse("security:backup"))
        self.assertContains(page, 'name="jobs" value="BCK-PC-1"')
        self.assertContains(page, reverse("security:preview_backup_job") + "?nome=BCK-PC-1")
        self.assertContains(page, "Chiudi gli alert")
        log = self.client.get(reverse("security:backup_log"))
        self.assertContains(log, 'name="jobs" value="BCK-PC-2"')

    def test_close_needs_reason_then_closes_only_selected_jobs(self):
        url = reverse("security:backup_bulk_case")
        self.client.post(url, {"jobs": ["BCK-PC-1", "BCK-PC-2"], "action": "close", "esito": "resolved"})
        self.assertEqual(SecurityAlert.objects.filter(status=Status.OPEN).count(), 3)
        self.client.post(url, {"jobs": ["BCK-PC-1", "BCK-PC-2"], "action": "close", "esito": "resolved", "motivo": "Job rifatti a mano"})
        self.assertEqual(set(SecurityAlert.objects.filter(status=Status.OPEN).values_list("pk", flat=True)), {self.altro.pk})

    def test_close_from_pc_selection_uses_the_pc_jobs(self):
        self.client.post(reverse("security:backup_bulk_case"), {"devices": ["PC-1"], "action": "close", "esito": "not_relevant", "motivo": "PC dismesso"})
        self.a1.refresh_from_db()
        self.a2.refresh_from_db()
        self.assertNotEqual(self.a1.status, Status.OPEN)
        self.assertEqual(self.a2.status, Status.OPEN)

    def test_acknowledge_selected_jobs(self):
        self.client.post(reverse("security:backup_bulk_case"), {"jobs": ["BCK-PC-2"], "action": "acknowledge"})
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.status, Status.ACKNOWLEDGED)

    def test_ticket_for_jobs_links_their_open_alerts(self):
        response = self.client.post(reverse("security:backup_bulk_case"), {"jobs": ["BCK-PC-1", "BCK-PC-1", "BCK-PC-2"], "action": "case"})
        case = SecurityRemediationTicket.objects.get()
        self.assertRedirects(response, reverse("security:case_detail", args=[case.pk]), fetch_redirect_response=False)
        self.assertEqual(case.tasks.count(), 2)
        self.assertEqual(set(case.linked_alerts.values_list("pk", flat=True)), {self.a1.pk, self.a2.pk})

    def test_job_preview_and_live_close_from_drawer(self):
        preview = self.client.get(reverse("security:preview_backup_job"), {"nome": "BCK-PC-1"})
        self.assertContains(preview, "Alert di backup aperti")
        self.assertContains(preview, "PC-1")
        response = self.client.post(reverse("security:backup_pannello_azione"), {
            "kind": "job", "nome": "BCK-PC-1", "jobs": "BCK-PC-1", "action": "close", "esito": "resolved", "motivo": "Rifatto",
        }, HTTP_HX_REQUEST="true")
        self.assertContains(response, "1 alert chiuso come «Risolto».")
        self.assertContains(response, "Nessun alert di backup aperto.")
        self.a1.refresh_from_db()
        self.assertNotEqual(self.a1.status, Status.OPEN)

    def test_pc_preview_shows_backup_alerts_once(self):
        response = self.client.get(reverse("security:preview_pc"), {"nome": "PC-2"})
        self.assertContains(response, "Alert di backup aperti")
        self.assertContains(response, "Backup job requires attention: BCK-PC-2", count=1)
        self.assertContains(response, "<dt>Alert aperti</dt><dd>1</dd>", html=False)

    def test_drawer_close_error_keeps_alerts_open(self):
        response = self.client.post(reverse("security:backup_pannello_azione"), {
            "kind": "pc", "nome": "PC-2", "devices": "PC-2", "action": "close", "esito": "resolved", "motivo": "",
        }, HTTP_HX_REQUEST="true")
        self.assertContains(response, "Scrivi il motivo")
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.status, Status.OPEN)
