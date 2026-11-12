"""Correzioni del SOC: numeri unici (backup ko, CVE per PC), elenchi senza tagli silenziosi, testi in italiano.

Dati sintetici.
"""
import importlib
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding
from security.models import (
    BackupJobRecord,
    SecurityAlert,
    SecurityAsset,
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityMailboxSource,
    SecurityRemediationTicket,
    SecuritySource,
    SecurityVulnerabilityFinding,
    Severity,
    SourceType,
    Status,
)
from security.services import metriche, pc_copertura
from security.services import segnalazioni as seg
from security.services.pc_overview import cve_uniche, pc_overview


class _Base(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="socfix_user", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)
        self.source = SecuritySource.objects.create(name="Fonte sintetica", vendor="Demo", source_type=SourceType.EMAIL)


class BackupKoUnicoTests(_Base):
    def test_elenco_dispositivi_e_barra_usano_la_stessa_finestra(self):
        # Ultimo backup fallito 45 giorni fa: fuori dai vecchi 30 giorni dell'elenco, dentro i 90 della barra.
        BackupJobRecord.objects.create(source=self.source, job_name="Job PC", status="failed",
                                       completed_at=timezone.now() - timedelta(days=45),
                                       payload={"device_name": "PC-FERMO"}, dedup_hash="bk1")
        rows = {r["key"]: r for r in pc_copertura.righe(proposte=False)}
        self.assertTrue(rows["pc-fermo"]["backup_ko"])
        self.assertEqual(metriche.pc_backup_ko().value, 1)
        self.assertEqual(pc_copertura.conteggi(list(rows.values()))["backup_ko"], metriche.pc_backup_ko().value)


class CveUnichePerPcTests(_Base):
    def setUp(self):
        super().setUp()
        uno = SecurityCveRecord.objects.create(cve_id="CVE-2099-1001", cvss=9.8)
        due = SecurityCveRecord.objects.create(cve_id="CVE-2099-1002", cvss=5.0)
        SecurityCveRecord.objects.create(cve_id="CVE-2099-1003", cvss=6.0, kev=True)
        for cve in (uno, due):
            SecurityCveImpact.objects.create(cve=cve, host="pc-cve.dominio.local", outcome=SecurityCveImpact.IMPACTS, explanation="sintetico")
        asset = SecurityAsset.objects.create(source=self.source, hostname="PC-CVE")
        # Defender: una CVE già vista dall'inventario e una nuova (in KEV secondo il catalogo).
        for cve, cvss in (("CVE-2099-1001", 9.8), ("CVE-2099-1003", 6.0)):
            SecurityVulnerabilityFinding.objects.create(source=self.source, asset=asset, cve=cve, affected_product="Prodotto", cvss=cvss,
                                                        severity=Severity.HIGH, status=Status.OPEN, dedup_hash=f"v{cve}")

    def test_una_cve_conta_una_volta(self):
        self.assertEqual(cve_uniche()["pc-cve"], {"cves": 3, "kev": 1, "gravi": 2})
        self.assertEqual(cve_uniche("PC-CVE")["pc-cve"]["cves"], 3)

    def test_scheda_pannello_ed_elenco_dicono_lo_stesso_numero(self):
        pc = pc_overview("PC-CVE")
        self.assertEqual(pc["cve_uniche"], 3)
        self.assertEqual(pc["cve_gravi"], 2)
        # La CVE già nell'inventario non si ripete tra quelle di Defender.
        self.assertEqual([v.cve for v in pc["vulns"]], ["CVE-2099-1003"])
        rows = {r["key"]: r for r in pc_copertura.righe(proposte=False)}
        self.assertEqual(rows["pc-cve"]["cve"]["cves"], 3)
        scheda = self.client.get(reverse("security:pc_detail") + "?nome=PC-CVE").content.decode()
        self.assertIn("<span>CVE</span><strong>3</strong>", scheda)  # KPI in testata
        self.assertIn("<span><strong>3</strong>CVE</span>", scheda)  # anello per gravità
        for cve in ("CVE-2099-1001", "CVE-2099-1002", "CVE-2099-1003"):
            self.assertEqual(scheda.count(f"<strong>{cve}</strong>"), 1, cve)
        pannello = self.client.get(reverse("security:preview_pc") + "?nome=PC-CVE")
        self.assertContains(pannello, "3 CVE, 2 gravi")
        for cve in ("CVE-2099-1001", "CVE-2099-1002", "CVE-2099-1003"):  # inventario e Defender, ognuna una volta
            self.assertContains(pannello, f"<strong>{cve}</strong>", count=1)


class ElenchiPaginatiTests(_Base):
    def test_alert_oltre_cento_si_paginano(self):
        SecurityAlert.objects.bulk_create([
            SecurityAlert(source=self.source, title=f"Alert sintetico {i}", severity=Severity.LOW, status=Status.OPEN, dedup_hash=f"pg{i}")
            for i in range(105)
        ])
        prima = self.client.get(reverse("security:alerts_list"))
        self.assertEqual(len(prima.context["alerts"]), 100)
        self.assertEqual(prima.context["total"], 105)
        self.assertContains(prima, 'data-fm-last-page="2"')
        seconda = self.client.get(reverse("security:alerts_list") + "?page=2")
        self.assertEqual(len(seconda.context["alerts"]), 5)

    def test_ticket_e_incidenti_hanno_il_pager(self):
        SecurityRemediationTicket.objects.bulk_create([
            SecurityRemediationTicket(source=self.source, title=f"Ticket sintetico {i}", status=Status.OPEN, dedup_hash=f"tk{i}")
            for i in range(101)
        ])
        pagina = self.client.get(reverse("security:tickets_list"))
        self.assertEqual(len(pagina.context["tickets"]), 100)
        self.assertContains(pagina, "101 ticket")
        self.assertEqual(self.client.get(reverse("security:incidents")).status_code, 200)

    def test_segnalazioni_chiuse_contano_e_avvisano_del_taglio(self):
        for i in range(3):
            SecurityAlert.objects.create(source=self.source, title=f"Chiuso {i}", severity=Severity.LOW, status=Status.CLOSED, dedup_hash=f"ch{i}")
        SecurityAlert.objects.create(source=self.source, title="Aperto", severity=Severity.LOW, status=Status.OPEN, dedup_hash="ap1")
        self.assertEqual(seg.conteggi(stato="chiuse")["alert"], 3)
        self.assertEqual(seg.conteggi()["alert"], 1)
        with mock.patch.object(seg, "PER_KIND_LIMIT", 2):
            pagina = self.client.get(reverse("security:segnalazioni") + "?stato=chiuse&tipo=alert")
            self.assertTrue(pagina.context["troncata"])
            self.assertContains(pagina, "mostrate 2 di 3")
            aperte = self.client.get(reverse("security:segnalazioni") + "?tipo=alert")
            self.assertFalse(aperte.context["troncata"])


class TitoliItalianiTests(TestCase):
    def test_migrazione_traduce_i_prefissi_noti(self):
        mig = importlib.import_module("security.migrations.0039_titoli_in_italiano")
        casi = {
            "Source silent: Caselle firewall": "Sorgente silenziosa: Caselle firewall",
            "Critical exposed vulnerability CVE-2099-1": "Vulnerabilità critica esposta CVE-2099-1",
            "Critical exposed vulnerability CVE-2099-1 on Prodotto": "Vulnerabilità critica esposta CVE-2099-1 su Prodotto",
            "Backup job requires attention: JOB-1": "Backup da controllare: JOB-1",
            "VPN authentication spike detected": "Picco di autenticazioni VPN",
            "Possible sender spoofing: Veeam report from esempio.test": "Possibile mittente falso: report Veeam da esempio.test",
            "Unreadable vulnerability data for CVE-2099-2 (manual review)": "Dati della vulnerabilità illeggibili per CVE-2099-2 (verifica manuale)",
            "Remediate 3 critical CVEs on Prodotto": "Correggere 3 CVE critiche su Prodotto",
            "Remediate CVE-2099-3 on Prodotto": "Correggere CVE-2099-3 su Prodotto",
            "Investigate backup issue: JOB-2": "Verificare il problema di backup: JOB-2",
            "Titolo già italiano": "Titolo già italiano",
        }
        for prima, dopo in casi.items():
            self.assertEqual(mig.traduci(prima), dopo)

    def test_ticket_di_rimedio_con_titolo_italiano(self):
        from security.services.ticketing import _ticket_title

        self.assertEqual(_ticket_title("Prodotto", ["CVE-2099-1"]), "Correggere CVE-2099-1 su Prodotto")
        self.assertEqual(_ticket_title("Prodotto", ["CVE-2099-1", "CVE-2099-2"]), "Correggere 2 CVE critiche su Prodotto")


class CaselleInRitardoTests(_Base):
    def test_filtro_ritardo_coerente_con_la_barra(self):
        SecurityMailboxSource.objects.create(name="Casella ferma", code="ferma", source_type="graph", enabled=True,
                                             mailbox_address="ferma@example.test", expected_every_hours=24)
        SecurityMailboxSource.objects.create(name="Casella senza cadenza", code="libera", source_type="graph", enabled=True,
                                             mailbox_address="libera@example.test", expected_every_hours=0)
        metrica = metriche.sorgenti_mute()
        self.assertEqual(metrica.value, 1)
        self.assertTrue(metrica.url.endswith("?stato=ritardo"))
        pagina = self.client.get(metrica.url)
        self.assertEqual(len(pagina.context["sources"]), metrica.value)
        self.assertContains(pagina, "Lettura ferma")
        self.assertEqual(len(self.client.get(reverse("security:admin_mailbox_sources_list")).context["sources"]), 2)


class MinoriTests(_Base):
    def test_vecchio_indirizzo_asset_collegati(self):
        risposta = self.client.get(reverse("security:assets") + "?stato=collegati")
        self.assertTrue(risposta["Location"].endswith("?f=collegati"))
        self.assertEqual(self.client.get(risposta["Location"]).context["codice"], "collegati")

    def test_carica_report_nel_menu_impostazioni(self):
        pagina = self.client.get(reverse("security:inbox"))
        self.assertContains(pagina, "Carica report")
        self.assertNotContains(pagina, "Inbox report")
        self.assertContains(self.client.get(reverse("security:letture")), reverse("security:inbox"))
