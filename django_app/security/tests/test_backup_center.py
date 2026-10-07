"""Sezione Backup: statistiche per PC (Veeam per macchina, Synology per job), per job, log e pagine."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import BackupJobRecord, SecuritySource, SourceType
from security.services import backup_center as svc


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="soc_bk_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="NAS sintetico", vendor="Demo", source_type=SourceType.EMAIL)
        self.n = 0

    def job(self, name, status, days_ago, payload):
        self.n += 1
        return BackupJobRecord.objects.create(
            source=self.source, job_name=name, status=status, completed_at=timezone.now() - timedelta(days=days_ago),
            payload=payload, dedup_hash=f"bk-{self.n}",
        )


class BackupCenterServiceTests(_Base):
    def test_veeam_objects_give_per_machine_status(self):
        self.job("VM notturno", "warning", 1, {"vendor": "veeam", "transferred_size_gb": 12.0, "duration_seconds": 1800, "objects": [
            {"name": "SRV-DEMO-01", "status": "completed", "transferred": "8,5 GB", "duration": "0:20:00"},
            {"name": "SRV-DEMO-02", "status": "failed", "transferred": "0 B", "duration": "0:01:00", "details": "Snapshot non riuscito"},
        ]})
        data = svc.overview(30)
        rows = {r["name"]: r for r in data["devices"]}
        self.assertEqual(rows["SRV-DEMO-01"]["last_status"], "completed")
        self.assertEqual(rows["SRV-DEMO-02"]["last_status"], "failed")
        self.assertAlmostEqual(rows["SRV-DEMO-01"]["gb"], 8.5)
        self.assertFalse(rows["SRV-DEMO-01"]["job_level"])
        # Il PC con l'ultimo backup fallito sta in cima.
        self.assertEqual(data["devices"][0]["name"], "SRV-DEMO-02")
        self.assertEqual(data["kpi"]["devices_failing"], 1)

    def test_synology_devices_inherit_job_status_and_staleness(self):
        self.job("PC uffici", "completed", 6, {"vendor": "synology", "devices": ["PC-DEMO-01", "PC-DEMO-02"]})
        self.job("PC uffici", "failed", 1, {"vendor": "synology", "devices": ["PC-DEMO-01", "PC-DEMO-02"]})
        self.job("PC singolo", "completed", 0, {"vendor": "synology", "device_name": "PC-DEMO-03", "transferred_size_gb": 2.0})
        data = svc.overview(30)
        rows = {r["name"]: r for r in data["devices"]}
        self.assertTrue(rows["PC-DEMO-01"]["job_level"])
        self.assertTrue(rows["PC-DEMO-01"]["stale"])  # ultimo riuscito 6 giorni fa
        self.assertEqual(rows["PC-DEMO-01"]["rate"], 50.0)
        self.assertFalse(rows["PC-DEMO-03"]["stale"])
        self.assertEqual(rows["PC-DEMO-03"]["gb"], 2.0)
        jobs = {j["name"]: j for j in data["jobs"]}
        self.assertEqual((jobs["PC uffici"]["runs"], jobs["PC uffici"]["fail"], jobs["PC uffici"]["devices"]), (2, 1, 2))
        self.assertEqual(data["kpi"]["runs"], 3)

    def test_period_excludes_old_runs(self):
        self.job("Vecchio", "completed", 40, {"device_name": "PC-OLD"})
        self.assertEqual(svc.overview(30)["kpi"]["runs"], 0)
        self.assertEqual(svc.overview(90)["kpi"]["runs"], 1)

    def test_size_parsing(self):
        self.assertAlmostEqual(svc._size_gb("830 MB"), 830 / 1024)
        self.assertAlmostEqual(svc._size_gb("1.234,5 GB"), 1234.5)
        self.assertIsNone(svc._size_gb("n/d"))


class BackupViewTests(_Base):
    def test_pages_render(self):
        self.job("PC uffici", "failed", 1, {"vendor": "synology", "devices": ["PC DEMO/01"]})
        page = self.client.get(reverse("security:backup"))
        self.assertContains(page, "PC DEMO/01")
        self.assertContains(page, "Per job")
        self.assertNotContains(page, "{#")
        device = self.client.get(reverse("security:backup_device") + "?nome=PC%20DEMO%2F01")
        self.assertContains(device, "Storico")
        self.assertEqual(self.client.get(reverse("security:backup_device") + "?nome=inesistente").status_code, 404)
        log = self.client.get(reverse("security:backup_log") + "?esito=failed&q=demo")
        self.assertContains(log, "PC uffici")
        empty = self.client.get(reverse("security:backup_log") + "?esito=completed")
        self.assertContains(empty, "Nessuna esecuzione")
