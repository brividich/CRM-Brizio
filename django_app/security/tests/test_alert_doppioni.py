"""Un alert per PC o job, non uno per mail; CVE della mail Defender e dell'inventario non doppie. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityEventRecord,
    SecurityMailboxSource,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.services import alert_doppioni
from security.services.cve_impact import impact_source
from security.services.dedup import make_hash
from security.services.rule_engine import evaluate_event

APERTI = ("new", "open", "acknowledged", "in_progress")


class _Base(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Casella report sintetica", source_type=SourceType.EMAIL, vendor="mailbox")
        self.n = 0

    def _evento(self, event_type, payload, source=None, quando=None):
        self.n += 1
        dedup = make_hash("evento-sintetico", self.n)
        return SecurityEventRecord.objects.create(
            source=source or self.source, event_type=event_type, severity=Severity.WARNING,
            occurred_at=quando or timezone.now() + timedelta(minutes=self.n), fingerprint=dedup, dedup_hash=dedup,
            payload=payload)

    def _usb(self, n, pc="PC-SINTETICO-1"):
        return self._evento("watchguard_alert_candidate", {
            "vendor": "watchguard", "alert_candidate": True, "type": "watchguard_epdr_threat_detected",
            "severity": "warning", "title": f"Endpoint Security: {n} devices blocked su {pc or 'computer non indicato'}",
            "computer": pc, "period_start": f"2026-11-{self.n:02d} 08:00:00"})


class AlertPerSoggettoTests(_Base):
    def test_mail_endpoint_security_stesso_pc_aggiornano_lo_stesso_alert(self):
        evaluate_event(self._usb(1))
        evaluate_event(self._usb(3))
        alerts = SecurityAlert.objects.filter(status__in=APERTI)
        self.assertEqual(alerts.count(), 1)
        alert = alerts.get()
        self.assertEqual(alert.title, "Endpoint Security: 3 devices blocked su PC-SINTETICO-1")
        self.assertEqual(alert_doppioni.occorrenze(alert).count(), 2)
        evaluate_event(self._usb(1, pc="PC-SINTETICO-2"))
        self.assertEqual(SecurityAlert.objects.filter(status__in=APERTI).count(), 2)

    def test_senza_pc_conta_il_titolo_senza_numeri(self):
        evaluate_event(self._usb(20, pc=""))
        evaluate_event(self._usb(30, pc=""))
        self.assertEqual(SecurityAlert.objects.filter(status__in=APERTI).count(), 1)

    def test_alert_chiuso_poi_nuova_mail_apre_un_alert_nuovo(self):
        evaluate_event(self._usb(1))
        SecurityAlert.objects.update(status=Status.CLOSED, closed_at=timezone.now())
        evaluate_event(self._usb(1))
        self.assertEqual(SecurityAlert.objects.filter(status__in=APERTI).count(), 1)
        self.assertEqual(SecurityAlert.objects.count(), 2)

    def test_backup_fallito_ogni_notte_un_alert_e_chiuso_dal_completato(self):
        for _ in range(3):
            evaluate_event(self._evento("backup_job", {"job_name": "BCK-SINTETICO", "device_name": "nas", "status": "failed"}))
        self.assertEqual(SecurityAlert.objects.filter(status__in=APERTI).count(), 1)
        evaluate_event(self._evento("backup_job", {"job_name": "BCK-SINTETICO", "device_name": "nas", "status": "completed"}))
        self.assertEqual(SecurityAlert.objects.filter(status__in=APERTI).count(), 0)
        self.assertEqual(SecurityAlert.objects.get().status, Status.RESOLVED)


class CveDoppieTests(_Base):
    CVE = "CVE-2099-12345"

    def _mail_defender(self):
        return self._evento("vulnerability_finding", {
            "cve": self.CVE, "cvss": 9.8, "severity": "critical", "exposed_devices": 3, "affected_product": "openssl"})

    def _inventario(self):
        evento = self._evento("cve_sla_scaduta", {"cve": self.CVE, "host": "pc-sintetico", "alert_candidate": True},
                              source=impact_source())
        return SecurityAlert.objects.create(source=evento.source, event=evento, severity=Severity.HIGH, dedup_hash=evento.dedup_hash,
                                            title=f"Oltre il termine di correzione: {self.CVE} su pc-sintetico (openssl)")

    def test_mail_senza_inventario_apre_l_alert(self):
        evaluate_event(self._mail_defender())
        self.assertTrue(SecurityAlert.objects.filter(title=f"Vulnerabilità critica esposta {self.CVE}").exists())

    def test_cve_gia_seguita_dall_inventario_niente_alert_dalla_mail(self):
        self._inventario()
        evento = self._mail_defender()
        evaluate_event(evento)
        self.assertFalse(SecurityAlert.objects.filter(title__startswith="Vulnerabilità critica esposta").exists())
        evento.refresh_from_db()
        self.assertEqual(evento.decision_trace["decision"], "kpi_only")

    def test_alert_della_mail_gia_aperto_si_chiude_come_doppione(self):
        evaluate_event(self._mail_defender())
        inventario = self._inventario()
        self.assertEqual(len(alert_doppioni.chiudi_cve_doppie(apply=False)), 1)
        self.assertTrue(SecurityAlert.objects.filter(title__startswith="Vulnerabilità", status__in=APERTI).exists())
        alert_doppioni.chiudi_cve_doppie()
        mail = SecurityAlert.objects.get(title__startswith="Vulnerabilità")
        self.assertEqual(mail.status, Status.CLOSED)
        self.assertIn(f"#{inventario.pk}", mail.status_reason)
        inventario.refresh_from_db()
        self.assertIn(inventario.status, APERTI)
        self.assertTrue(SecurityAlertActionLog.objects.filter(alert=inventario, action="cve_doppione_unito").exists())


class UnisciDoppioniTests(_Base):
    def _alert_vecchio(self, n, pc="PC-SINTETICO-1"):
        """Come prima della regola: chiave = impronta della mail."""
        evento = self._usb(n, pc)
        return SecurityAlert.objects.create(source=self.source, event=evento, title=evento.payload["title"],
                                            severity=Severity.WARNING, dedup_hash=evento.dedup_hash)

    def test_prova_poi_unione_e_mail_dopo_aggiorna_il_tenuto(self):
        vecchi = [self._alert_vecchio(i) for i in (1, 2, 5)]
        out = StringIO()
        call_command("security_unisci_doppioni", stdout=out)
        self.assertIn("[PROVA]", out.getvalue())
        self.assertEqual(SecurityAlert.objects.filter(status__in=APERTI).count(), 3)
        call_command("security_unisci_doppioni", "--apply", stdout=StringIO())
        aperti = SecurityAlert.objects.filter(status__in=APERTI)
        self.assertEqual(list(aperti.values_list("pk", flat=True)), [vecchi[-1].pk])
        tenuto = aperti.get()
        self.assertEqual(alert_doppioni.occorrenze(tenuto).count(), 3)
        for alert in vecchi[:-1]:
            alert.refresh_from_db()
            self.assertEqual(alert.status, Status.CLOSED)
            self.assertIn(f"#{tenuto.pk}", alert.status_reason)
        evaluate_event(self._usb(7))
        self.assertEqual(SecurityAlert.objects.filter(status__in=APERTI).count(), 1)
        tenuto.refresh_from_db()
        self.assertEqual(tenuto.title, "Endpoint Security: 7 devices blocked su PC-SINTETICO-1")

    def test_rinomina_fonte(self):
        SecurityMailboxSource.objects.create(name=self.source.name, code="report-sintetico")
        call_command("security_unisci_doppioni", "--apply", "--rinomina-fonte", self.source.name, "Casella report SOC",
                     stdout=StringIO())
        self.source.refresh_from_db()
        self.assertEqual(self.source.name, "Casella report SOC")
        self.assertTrue(SecurityMailboxSource.objects.filter(name="Casella report SOC").exists())
