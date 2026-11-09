"""«Scarica CSV» degli elenchi del SOC: tutte le righe del filtro, celle protette, accesso come la pagina. Dati sintetici."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, UserOnboarding
from security.models import (
    BackupJobRecord,
    BackupRestoreTest,
    SecurityAlert,
    SecurityAsset,
    SecurityCveRecord,
    SecurityEventRecord,
    SecurityRemediationTicket,
    SecuritySource,
    SecurityVpnAccess,
    Severity,
    SoftwareCpeMapping,
    SoftwareInstallation,
    SourceType,
    Status,
)
from security.services import cve_gestione, cve_impact
from security.services import incidents as inc_svc


def _testo(risposta):
    return b"".join(risposta).decode("utf-8-sig")


class EsportaCsvTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create(username="csv_admin", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.estraneo = get_user_model().objects.create(username="csv_estraneo")
        UserOnboarding.objects.create(user=self.estraneo, completed=True)
        self.client.force_login(self.admin)
        self.source = SecuritySource.objects.create(name="Fonte CSV", vendor="Demo", source_type=SourceType.EMAIL)

    def _csv(self, nome, params=None, args=None):
        risposta = self.client.get(reverse(f"security:{nome}", args=args), {**(params or {}), "formato": "csv"})
        self.assertEqual(risposta.status_code, 200, nome)
        self.assertTrue(risposta["Content-Type"].startswith("text/csv"), nome)
        self.assertIn("attachment;", risposta["Content-Disposition"])
        return _testo(risposta)

    def _negato(self, nome):
        self.client.force_login(self.estraneo)
        risposta = self.client.get(reverse(f"security:{nome}"), {"formato": "csv"})
        self.assertNotEqual(risposta.status_code, 200, nome)
        self.assertFalse(risposta.get("Content-Type", "").startswith("text/csv"), nome)
        self.client.force_login(self.admin)

    def test_alert_filtri_formula_audit_e_accesso(self):
        SecurityAlert.objects.create(source=self.source, title="=HYPERLINK(\"x\")", severity=Severity.CRITICAL, status=Status.OPEN, dedup_hash="c1")
        SecurityAlert.objects.create(source=self.source, title="Alert basso CSV", severity=Severity.LOW, status=Status.OPEN, dedup_hash="c2")
        testo = self._csv("alerts_list", {"severity": "critical"})
        self.assertIn("N.;Creato il;Severità;Alert;Sorgente", testo)
        self.assertIn("'=HYPERLINK", testo)  # cella protetta dalle formule
        self.assertIn("Critico", testo)       # gravità tradotta
        self.assertNotIn("Alert basso CSV", testo)
        self.assertTrue(AuditLog.objects.filter(azione="soc_alert_export", modulo="security").exists())
        self.assertContains(self.client.get(reverse("security:alerts_list")), "Scarica CSV")
        self._negato("alerts_list")

    def test_alert_oltre_la_pagina(self):
        for i in range(105):
            SecurityAlert.objects.create(source=self.source, title=f"Alert massa {i}", severity=Severity.LOW, status=Status.OPEN, dedup_hash=f"m{i}")
        testo = self._csv("alerts_list")
        self.assertEqual(testo.count("Alert massa"), 105)

    def test_ticket(self):
        SecurityRemediationTicket.objects.create(source=self.source, title="Ticket CSV aperto", severity=Severity.HIGH, status=Status.OPEN, dedup_hash="t1")
        SecurityRemediationTicket.objects.create(source=self.source, title="Ticket CSV chiuso", severity=Severity.HIGH, status=Status.CLOSED, dedup_hash="t2")
        testo = self._csv("tickets_list")
        self.assertIn("N.;Aperto il;Stato;Severità;Ticket", testo)
        self.assertIn("Ticket CSV aperto", testo)
        self.assertNotIn("Ticket CSV chiuso", testo)  # di default solo i ticket attivi, come la pagina
        self.assertIn("Ticket CSV chiuso", self._csv("tickets_list", {"status": "closed"}))
        self._negato("tickets_list")

    def test_incidenti(self):
        inc_svc.create_incident(self.admin, title="+Incidente CSV", detected_at=timezone.now() - timedelta(hours=2), is_significant=True)
        testo = self._csv("incidents")
        self.assertIn("Codice;Titolo;Categoria;Gravità;Stato", testo)
        self.assertIn("'+Incidente CSV", testo)
        self.assertIn("Significativo (NIS2)", testo)
        self.assertNotIn("Incidente CSV", self._csv("incidents", {"q": "niente"}))
        self._negato("incidents")

    def test_eventi(self):
        SecurityEventRecord.objects.create(source=self.source, event_type="evento_csv", severity=Severity.HIGH, fingerprint="f1", dedup_hash="e1",
                                           payload={"title": "@SUM(1)"})
        SecurityEventRecord.objects.create(source=self.source, event_type="altro_csv", severity=Severity.LOW, fingerprint="f2", dedup_hash="e2")
        testo = self._csv("events", {"type": "evento_csv"})
        self.assertIn("N.;Quando;Evento;Dettaglio;Severità;Decisione del motore", testo)
        self.assertIn("'@SUM(1)", testo)
        self.assertNotIn("altro_csv", testo)
        self._negato("events")

    def test_vpn(self):
        now = timezone.now()
        SecurityVpnAccess.objects.create(source=self.source, action="denied", username="-utente.csv", source_ip="10.0.0.1", login_at=now,
                                         kind="vpn", dedup_hash="v1")
        SecurityVpnAccess.objects.create(source=self.source, action="allowed", username="altro.csv", source_ip="10.0.0.2", login_at=now,
                                         kind="vpn", dedup_hash="v2")
        testo = self._csv("vpn_history", {"action": "denied"})
        self.assertIn("Esito;Utente;IP origine;Accesso;Uscita", testo)
        self.assertIn("'-utente.csv", testo)
        self.assertIn("Negato", testo)
        self.assertNotIn("altro.csv", testo)
        self._negato("vpn_history")

    def test_segnalazioni_oltre_il_taglio_per_tipo(self):
        from security.services import segnalazioni

        for i in range(segnalazioni.PER_KIND_LIMIT + 5):
            SecurityAlert.objects.create(source=self.source, title=f"Segn {i}", severity=Severity.LOW, status=Status.OPEN, dedup_hash=f"s{i}")
        SecurityAlert.objects.create(source=self.source, title="=Segn formula", severity=Severity.HIGH, status=Status.OPEN, dedup_hash="sf")
        testo = self._csv("segnalazioni", {"tipo": "alert"})
        self.assertIn("Tipo;N.;Titolo;Gravità;Stato;Urgente", testo)
        self.assertEqual(testo.count(";Segn "), segnalazioni.PER_KIND_LIMIT + 5)
        self.assertIn("'=Segn formula", testo)
        solo_alti = self._csv("segnalazioni", {"gravita": "high"})
        self.assertNotIn("Segn 1", solo_alti)
        self.assertContains(self.client.get(reverse("security:segnalazioni")), "Scarica CSV")
        self._negato("segnalazioni")

    def test_dispositivi(self):
        SecurityAsset.objects.create(source=self.source, hostname="=pc-csv-01")
        SecurityAsset.objects.create(source=self.source, hostname="pc-altro-02")
        testo = self._csv("pc_copertura", {"q": "csv"})
        self.assertIn("Dispositivo;Utente;Produttore e modello", testo)
        self.assertIn("'=pc-csv-01", testo)
        self.assertNotIn("pc-altro-02", testo)
        self.assertContains(self.client.get(reverse("security:pc_copertura")), "Scarica CSV")
        self._negato("pc_copertura")

    def test_log_backup_senza_tetto(self):
        now = timezone.now()
        for i in range(305):
            BackupJobRecord.objects.create(source=self.source, job_name=f"Job {i}", status="success", completed_at=now, dedup_hash=f"b{i}")
        BackupJobRecord.objects.create(source=self.source, job_name="=Job ko", status="failed", completed_at=now, dedup_hash="bko")
        testo = self._csv("backup_log")
        self.assertIn("Quando;Esito;Oggetti in errore;Job", testo)
        self.assertEqual(testo.count("Job "), 306)
        self.assertIn("'=Job ko", testo)
        self.assertEqual(self._csv("backup_log", {"esito": "failed"}).count("Job"), 2)  # intestazione + la riga fallita
        self._negato("backup_log")

    def test_prove_di_ripristino(self):
        BackupRestoreTest.objects.create(data=timezone.localdate(), sistema="=Server CSV", cosa_ripristinato="Cartella sintetica",
                                         esito=BackupRestoreTest.ESITO_KO, durata_minuti=12, eseguito_da="Tecnico sintetico", note="Nota")
        testo = self._csv("backup_ripristini")
        self.assertIn("Data;Esito;Sistema;Job;Cosa è stato ripristinato;Durata (minuti);Eseguita da;Note;Allegato", testo)
        self.assertIn("'=Server CSV", testo)
        self.assertIn("Fallita", testo)
        self.assertIn(";no;", testo)  # allegato
        self.assertContains(self.client.get(reverse("security:backup_ripristini")), "Scarica CSV")
        self._negato("backup_ripristini")


class EsportaCsvCveTests(TestCase):
    def setUp(self):
        SoftwareCpeMapping.objects.create(vendor="acme", product="viewer", cpe_vendor="acme", cpe_product="viewer", confirmed=True)
        self.records = [
            SecurityCveRecord.objects.create(cve_id=f"CVE-2099-090{i}", description=f"=Sintetica {i}", cvss=9.1,
                                             configurations=[{"vendor": "acme", "product": "viewer", "end_excluding": "2.0"}])
            for i in range(2)
        ]
        now = timezone.now()
        SoftwareInstallation.objects.create(
            dedup_key="pc-csv|viewer|1.0", source_kind="watchguard", host="pc-csv", host_display="PC-CSV",
            vendor="acme", vendor_raw="Acme", product="viewer", product_raw="Acme Viewer", version_raw="1.0",
            fonti=["watchguard"], still_detected=True, seen_at=now, last_seen_at=now, last_inventory_date=timezone.localdate(),
        )
        for r in self.records:
            cve_impact.recompute(r)
        self.admin = get_user_model().objects.create(username="csv_cve_admin", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=self.admin, completed=True)
        self.client.force_login(self.admin)

    def test_limite_solo_a_video(self):
        self.assertEqual(len(cve_gestione.elenco_cve(limite=1)["righe"]), 1)
        self.assertTrue(cve_gestione.elenco_cve(limite=1)["troncato"])
        self.assertEqual(len(cve_gestione.elenco_cve(limite=None)["righe"]), 2)

    def test_csv_completo_e_filtri(self):
        url = reverse("security:vulnerabilities")
        risposta = self.client.get(url, {"formato": "csv"})
        self.assertTrue(risposta["Content-Type"].startswith("text/csv"))
        testo = _testo(risposta)
        self.assertIn("CVE;Gravità;CVSS;EPSS;Sfruttata (KEV)", testo)
        self.assertIn("CVE-2099-0900", testo)
        self.assertIn("CVE-2099-0901", testo)
        self.assertIn("'=Sintetica 0", testo)
        self.assertIn("9,1", testo)
        self.assertNotIn("CVE-2099-0900", _testo(self.client.get(url, {"formato": "csv", "q": "CVE-2099-0901"})))
        self.assertContains(self.client.get(url), "Scarica CSV")
        estraneo = get_user_model().objects.create(username="csv_cve_no")
        self.client.force_login(estraneo)
        self.assertNotEqual(self.client.get(url, {"formato": "csv"}).status_code, 200)
