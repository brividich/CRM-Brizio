"""Tessere KPI del SOC cliccabili: la pagina di destinazione conta lo stesso insieme. Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord,
    SecurityAlert,
    SecurityEventRecord,
    SecurityMailboxMessage,
    SecuritySource,
    Severity,
    SourceType,
)
from security.services import backup_center
from security.services.cve_impact import IMPACT_EVENT_TYPE


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create(username="soc_kpi_user", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Sorgente sintetica", vendor="Demo", source_type=SourceType.EMAIL)
        self.n = 0

    def alert(self, created_days_ago=0, closed_days_ago=None, status="new", event_type="demo"):
        self.n += 1
        event = SecurityEventRecord.objects.create(source=self.source, event_type=event_type, severity=Severity.HIGH,
                                                   fingerprint=f"f{self.n}", dedup_hash=f"e{self.n}", payload={})
        a = SecurityAlert.objects.create(source=self.source, event=event, title=f"Alert {self.n}", severity=Severity.HIGH,
                                         dedup_hash=f"a{self.n}", status=status)
        campi = {"created_at": timezone.now() - timedelta(days=created_days_ago)}
        if closed_days_ago is not None:
            campi["closed_at"] = timezone.now() - timedelta(days=closed_days_ago)
        SecurityAlert.objects.filter(pk=a.pk).update(**campi)
        return a

    def job(self, status, days_ago, started_only=False):
        self.n += 1
        quando = timezone.now() - timedelta(days=days_ago)
        return BackupJobRecord.objects.create(
            source=self.source, job_name="Job sintetico", status=status, dedup_hash=f"bk-{self.n}", payload={},
            completed_at=None if started_only else quando, started_at=quando,
        )


class ReportKpiLinkTests(_Base):
    def test_tessere_del_report_portano_agli_elenchi_con_lo_stesso_numero(self):
        self.alert(created_days_ago=1)
        self.alert(created_days_ago=2, closed_days_ago=1, status="closed")
        self.alert(created_days_ago=60)
        self.job("completed", 1)
        self.job("failed", 2)
        self.job("completed", 3, started_only=True)  # senza completed_at: conta per data di avvio
        self.job("completed", 90)
        r = self.client.get(reverse("security:report"), {"period": "last_30"})
        rep = r.context["report"]
        dal, al = rep["start"].isoformat(), rep["end"].isoformat()
        html = r.content.decode()

        alerts = reverse("security:alerts_list")
        self.assertIn(f'href="{alerts}?status=all&amp;dal={dal}&amp;al={al}"', html)
        creati = self.client.get(alerts, {"status": "all", "dal": dal, "al": al})
        self.assertEqual(creati.context["total"], rep["alerts"]["created"])
        self.assertEqual(rep["alerts"]["created"], 2)
        chiusi = self.client.get(alerts, {"status": "all", "chiusi_dal": dal, "chiusi_al": al})
        self.assertEqual(chiusi.context["total"], rep["alerts"]["closed"])

        log = reverse("security:backup_log")
        self.assertIn(f'href="{log}?dal={dal}&amp;al={al}"', html)
        righe = self.client.get(log, {"dal": dal, "al": al}).context["rows"]
        self.assertEqual(len(righe), rep["backup"]["total"])
        self.assertEqual(rep["backup"]["total"], 3)

        self.assertIn(f'href="{reverse("security:incidents")}?status=all&amp;dal={dal}&amp;al={al}"', html)


class BackupKpiLinkTests(_Base):
    def test_panoramica_e_log_usano_lo_stesso_periodo(self):
        self.job("completed", 1)
        self.job("failed", 2, started_only=True)
        self.job("completed", 45)
        data = backup_center.overview(30)
        r = self.client.get(reverse("security:backup"), {"giorni": 30})
        self.assertContains(r, f'href="{reverse("security:backup_log")}?giorni=30"')
        righe = self.client.get(reverse("security:backup_log"), {"giorni": "30"}).context["rows"]
        self.assertEqual(len(righe), data["kpi"]["runs"])
        self.assertEqual(data["kpi"]["runs"], 2)


class AlertCveKpiLinkTests(_Base):
    def test_alert_cve_aperti_e_chiusi(self):
        from security.services.cve_chiusura import metriche

        self.alert(event_type=IMPACT_EVENT_TYPE)
        self.alert(event_type=IMPACT_EVENT_TYPE, created_days_ago=5, closed_days_ago=2, status="closed")
        self.alert(event_type="altro")
        m = metriche()
        alerts = reverse("security:alerts_list")
        aperti = self.client.get(alerts, {"tipo": "cve", "status": "active"})
        self.assertEqual(aperti.context["total"], m["aperti"])
        chiusi = self.client.get(alerts, {"tipo": "cve", "status": "inactive",
                                          "chiusi_dal": m["dal"].isoformat(), "chiusi_al": m["al"].isoformat()})
        self.assertEqual(chiusi.context["total"], m["chiusi"])
        self.assertEqual((m["aperti"], m["chiusi"]), (1, 1))


class ParserCodaKpiLinkTests(_Base):
    def test_tessere_della_coda_aprono_inbox_filtrata(self):
        SecurityMailboxMessage.objects.create(source=self.source, sender="a@example.test", subject="S1", body="x",
                                              parse_status="failed")
        SecurityMailboxMessage.objects.create(source=self.source, sender="a@example.test", subject="S2", body="x",
                                              parse_status="skipped")
        from security.services.parser_catalog import _queue_summary

        coda = _queue_summary()
        for stato in ("pending", "failed", "skipped"):
            r = self.client.get(reverse("security:inbox"), {"stato": stato})
            self.assertEqual(r.context["inbox_n_messaggi"] + r.context["inbox_n_file"], coda[stato], stato)


class AccettazioniKpiLinkTests(_Base):
    def test_contatori_e_filtri_coincidono(self):
        from security.models import SecurityAccettazioneRischio, SecurityCveRecord

        cve = SecurityCveRecord.objects.create(cve_id="CVE-2099-7001", cvss=7.0, severity="high")
        oggi = timezone.localdate()
        for giorni in (10, 100, -3):
            SecurityAccettazioneRischio.objects.create(cve=cve, motivo="Sintetico", scadenza=oggi + timedelta(days=giorni))
        url = reverse("security:accettazioni_rischio")
        r = self.client.get(url)
        counts = r.context["counts"]
        for stato in ("attive", "in_scadenza", "scadute"):
            self.assertContains(r, f'href="{url}?stato={stato}"')
            self.assertEqual(len(self.client.get(url, {"stato": stato}).context["righe"]), counts[stato], stato)
        self.assertEqual((counts["attive"], counts["in_scadenza"], counts["scadute"]), (2, 1, 1))
