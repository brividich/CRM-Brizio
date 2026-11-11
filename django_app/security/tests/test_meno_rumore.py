"""Meno rumore: blocchi USB, CVE oltre il termine per CVE, backup ritentati, malware nei backup, Entra, alert fermi.

Dati sintetici.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityAlertProposta,
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityEventRecord,
    SecuritySource,
    Severity,
    SourceType,
    Status,
)
from security.parsers.veeam_backup_email_parser import VeeamBackupEmailParser, parse_veeam_email
from security.services import alert_doppioni, alert_fermi, cve_sla
from security.services.configuration import set_setting
from security.services.cve_impact import impact_source
from security.services.dedup import make_hash
from security.services.rule_engine import evaluate_event

APERTI = ("new", "open", "acknowledged", "in_progress")
CVE = "CVE-2099-40001"


class _Base(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Casella report sintetica", source_type=SourceType.EMAIL, vendor="mailbox")
        self.n = 0

    def _evento(self, event_type, payload, source=None, quando=None):
        self.n += 1
        dedup = make_hash("evento-rumore", self.n)
        return SecurityEventRecord.objects.create(
            source=source or self.source, event_type=event_type, severity=Severity.WARNING,
            occurred_at=quando or timezone.now() - timedelta(hours=1) + timedelta(seconds=self.n),
            fingerprint=dedup, dedup_hash=dedup, payload=payload)

    def _usb(self, n, pc="PC-SINTETICO-1", categoria="devices blocked"):
        return self._evento("watchguard_alert_candidate", {
            "vendor": "watchguard", "alert_candidate": True, "type": "watchguard_epdr_threat_detected",
            "severity": "warning", "title": f"Endpoint Security: {n} {categoria} su {pc or 'computer non indicato'}",
            "computer": pc, "categories": [[n, categoria]]})

    def aperti(self):
        return SecurityAlert.objects.filter(status__in=APERTI)


class DispositiviBloccatiTests(_Base):
    def test_blocchi_usb_niente_alert_ma_contati(self):
        evento = self._usb(3)
        evaluate_event(evento)
        evaluate_event(self._usb(2, pc=""))
        self.assertFalse(self.aperti().exists())
        evento.refresh_from_db()
        self.assertEqual(evento.decision_trace["decision"], "kpi_only")
        righe = {r["pc"]: r for r in alert_doppioni.dispositivi_bloccati_per_pc(30)}
        self.assertEqual(righe["PC-SINTETICO-1"]["blocchi"], 3)
        self.assertEqual(righe["Computer non indicato nella mail"]["blocchi"], 2)

    def test_sopra_la_soglia_in_24_ore_apre_l_alert(self):
        set_setting("rumore.dispositivi_bloccati.soglia", 5)
        evaluate_event(self._usb(3))
        self.assertFalse(self.aperti().exists())
        evaluate_event(self._usb(4))
        self.assertEqual(self.aperti().count(), 1)

    def test_minaccia_vera_apre_sempre_l_alert(self):
        evaluate_event(self._usb(1, categoria="malware"))
        self.assertEqual(self.aperti().count(), 1)

    def test_rumore_spento_come_prima(self):
        set_setting("rumore.attivo", False)
        evaluate_event(self._usb(3))
        self.assertEqual(self.aperti().count(), 1)

    def test_pagina_dispositivi_mostra_il_conteggio(self):
        evaluate_event(self._usb(3))
        admin = get_user_model().objects.create(username="soc_rumore", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse("security:pc_copertura") + "?vista=bloccati")
        self.assertContains(resp, "Dispositivi bloccati dalla policy")
        self.assertContains(resp, "PC-SINTETICO-1")


class CveOltreTermineTests(_Base):
    def setUp(self):
        super().setUp()
        self.impact = impact_source()
        self.record = SecurityCveRecord.objects.create(cve_id=CVE, cvss=7.5, severity="high")

    def _sla(self, host):
        return self._evento(cve_sla.EVENT_SLA, {
            "cve": CVE, "host": host, "classe": "alta", "etichetta": "Alta", "scadenza": "2026-10-01", "giorni_ritardo": 10,
            "affected_product": "programma-sintetico", "alert_candidate": True}, source=self.impact)

    def _esposto(self, host):
        SecurityCveImpact.objects.create(cve=self.record, host=host, outcome=SecurityCveImpact.IMPACTS, explanation="sintetico",
                                         aperta_dal=timezone.now() - timedelta(days=60))

    def test_un_alert_per_cve_e_i_pc_in_timeline(self):
        evaluate_event(self._sla("pc-a"))
        evaluate_event(self._sla("pc-b"))
        alert = self.aperti().get()
        self.assertIn(CVE, alert.title)
        self.assertEqual(alert.dedup_hash, cve_sla.chiave_cve(self.impact, CVE))
        self.assertTrue(SecurityAlertActionLog.objects.filter(alert=alert, action="cve_termine_scaduto",
                                                              details__host="pc-b").exists())

    def test_pc_corretto_lascia_traccia_e_l_ultimo_chiude(self):
        self._esposto("pc-a")
        self._esposto("pc-b")
        evaluate_event(self._sla("pc-a"))
        evaluate_event(self._sla("pc-b"))
        alert = self.aperti().get()
        SecurityCveImpact.objects.filter(host="pc-a").delete()   # pc-a aggiornato: non più esposto
        cve_sla.chiudi_rientrate()
        alert.refresh_from_db()
        self.assertIn(alert.status, APERTI)
        self.assertTrue(alert.title.endswith(", 1 PC"))
        self.assertTrue(SecurityAlertActionLog.objects.filter(alert=alert, action="cve_pc_rientrato", details__host="pc-a").exists())
        SecurityCveImpact.objects.all().delete()
        cve_sla.chiudi_rientrate()
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.RESOLVED)
        self.assertEqual(SecurityAlertActionLog.objects.filter(alert=alert, action="cve_pc_rientrato").count(), 2)

    def test_cve_con_alert_impatto_va_nella_sua_timeline(self):
        ev = self._evento("cve_impact_confirmed", {"cve": CVE, "alert_candidate": True}, source=self.impact)
        impatto = SecurityAlert.objects.create(source=self.impact, event=ev, severity=Severity.CRITICAL, dedup_hash=ev.dedup_hash,
                                               title=f"{CVE}: 2 PC con versione vulnerabile")
        evento = self._sla("pc-a")
        evaluate_event(evento)
        self.assertEqual(list(self.aperti().values_list("pk", flat=True)), [impatto.pk])
        self.assertTrue(SecurityAlertActionLog.objects.filter(alert=impatto, action="cve_termine_scaduto", details__host="pc-a").exists())
        evento.refresh_from_db()
        self.assertEqual(evento.decision_trace["decision"], "merged")

    def test_comando_unisce_gli_alert_vecchi_per_pc(self):
        vecchi = []
        for host in ("pc-a", "pc-b", "pc-c"):
            ev = self._sla(host)
            vecchi.append(SecurityAlert.objects.create(source=self.impact, event=ev, severity=Severity.MEDIUM, dedup_hash=ev.dedup_hash,
                                                       title=cve_sla.titolo_evento(ev.payload)))
        call_command("security_unisci_doppioni", "--apply", stdout=StringIO())
        tenuto = self.aperti().get()
        self.assertEqual(tenuto.dedup_hash, cve_sla.chiave_cve(self.impact, CVE))
        self.assertNotIn(" su pc-", tenuto.title)
        self.assertEqual(set(cve_sla._host_per_azione(tenuto)), {"pc-a", "pc-b", "pc-c"})


class BackupTests(_Base):
    def test_retry_riuscito_chiude_il_fallimento(self):
        evaluate_event(self._evento("backup_job", {"job_name": "BCK-SINTETICO", "device_name": "", "status": "failed"}))
        evaluate_event(self._evento("backup_job", {"job_name": "BCK-SINTETICO (Retry 1)", "device_name": "", "status": "failed"}))
        self.assertEqual(self.aperti().count(), 1)
        evaluate_event(self._evento("backup_job", {"job_name": "BCK-SINTETICO (Retry 2)", "device_name": "", "status": "completed"}))
        self.assertFalse(self.aperti().exists())

    def test_parser_toglie_il_retry_dal_nome(self):
        payload = parse_veeam_email("[Failed] BCK-SINTETICO (Retry 3) (2 objects)", "Veeam Backup\nBackup job: BCK-SINTETICO (Retry 3)\n")
        self.assertEqual(payload["job_name"], "BCK-SINTETICO")
        self.assertEqual(payload["tentativo"], 3)

    def test_malware_nei_backup_alert_a_parte(self):
        for n in (8, 7):
            evaluate_event(self._evento("backup_job", {"job_name": f"Potential malware activity detected ({n} malware events)",
                                                       "status": "warning"}))
        alert = self.aperti().get()
        self.assertTrue(alert.title.startswith("Veeam: malware nei backup"))
        self.assertEqual(alert.severity, Severity.HIGH)
        self.assertEqual(alert.dedup_hash, make_hash(self.source.pk, "alert", alert_doppioni.EVENTO_MALWARE))
        evaluate_event(self._evento("backup_job", {"job_name": "Daily malware detection report (0 malware events)",
                                                   "status": "completed"}))
        self.assertEqual(self.aperti().count(), 1)

    def test_parser_mail_malware_non_e_un_job(self):
        class Mail:
            pk = None
            subject = "[Warning] Potential malware activity detected (2 malware events)"
            body = "Veeam Backup & Replication\nPotential malware activity detected\n"
            sender = "veeam@example.com"
            received_at = timezone.now()

        report = VeeamBackupEmailParser().parse(Mail())
        self.assertEqual(report.records[0].record_type, "veeam_malware")
        self.assertEqual(report.metrics, {})


class EntraTests(_Base):
    def _audit(self, autore):
        return self._evento("entra_audit", {"attivita": "Consent to application", "etichetta": "Consenso a un'app",
                                            "autore": autore, "target": ["App sintetica"], "esito": "success"})

    def test_amministratore_del_portale_niente_alert(self):
        get_user_model().objects.create(username="admin.sintetico", email="admin.sintetico@example.com", is_superuser=True)
        evaluate_event(self._audit("admin.sintetico@example.com"))
        self.assertFalse(self.aperti().exists())

    def test_autore_in_elenco_niente_alert_altri_si(self):
        set_setting("rumore.entra.autori_fidati", "it.sintetico@example.com")
        evaluate_event(self._audit("IT.Sintetico@example.com"))
        self.assertFalse(self.aperti().exists())
        evaluate_event(self._audit("estraneo@example.com"))
        self.assertEqual(self.aperti().count(), 1)


class ChiudiRumoreTests(_Base):
    def test_comando_chiude_i_blocchi_usb_gia_aperti(self):
        ev = self._usb(4)
        alert = SecurityAlert.objects.create(source=self.source, event=ev, title=ev.payload["title"], severity=Severity.WARNING,
                                             dedup_hash=ev.dedup_hash)
        out = StringIO()
        call_command("security_unisci_doppioni", stdout=out)
        self.assertIn("dispositivi_bloccati: 1", out.getvalue())
        alert.refresh_from_db()
        self.assertIn(alert.status, APERTI)
        call_command("security_unisci_doppioni", "--apply", stdout=StringIO())
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.CLOSED)
        self.assertTrue(SecurityAlertActionLog.objects.filter(alert=alert, action="closed_as_noise").exists())


class AlertFermiTests(_Base):
    def _alert(self, giorni_fa, event_type="backup_job", severity=Severity.WARNING, title="Backup da controllare: BCK-FERMO"):
        quando = timezone.now() - timedelta(days=giorni_fa)
        ev = self._evento(event_type, {"job_name": "BCK-FERMO", "status": "failed"}, quando=quando)
        alert = SecurityAlert.objects.create(source=self.source, event=ev, title=title, severity=severity, dedup_hash=ev.dedup_hash)
        SecurityAlert.objects.filter(pk=alert.pk).update(created_at=quando, updated_at=quando)
        return alert

    def test_fermo_da_30_giorni_proposta_una_volta(self):
        fermo = self._alert(40)
        self._alert(5, title="Backup da controllare: BCK-RECENTE")
        self._alert(40, event_type="cve_sla_scaduta", title=f"Oltre il termine di correzione: {CVE}")
        self._alert(40, severity=Severity.CRITICAL, title="Backup da controllare: BCK-CRITICO")
        self.assertEqual(alert_fermi.proponi_chiusura(), 1)
        proposta = SecurityAlertProposta.objects.get()
        self.assertEqual(proposta.alert_id, fermo.pk)
        self.assertEqual(proposta.esito, "resolved")
        self.assertTrue(proposta.prove)
        self.assertEqual(alert_fermi.proponi_chiusura(), 0)
        proposta.stato = SecurityAlertProposta.SCARTATA
        proposta.save()
        self.assertEqual(alert_fermi.proponi_chiusura(), 0)

    def test_zero_giorni_spento(self):
        self._alert(40)
        set_setting("rumore.fermi.giorni", 0)
        self.assertEqual(alert_fermi.proponi_chiusura(), 0)
