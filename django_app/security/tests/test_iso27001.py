"""Conformità ISO 27001: verifiche dei controlli, pagina, pacchetto mensile di evidenze. Dati sintetici.

I servizi ``cve_sla`` e ``iso_incidenti`` vivono su altri rami: qui si simulano con ``_modulo`` finto.
"""
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_q.models import Schedule

from security.models import BackupJobRecord, SecurityCveRecord, SecurityCveRisoluzione, SecurityIncident, SecurityLetturaLog, SecurityPacchettoIso, SecuritySource
from security.services import battito, iso27001, iso_pacchetto, letture, soc_settings

OGGI = date(2026, 10, 27)
DAL, AL = date(2026, 10, 1), date(2026, 10, 27)

INCIDENTI_OK = {
    "triage": {"target": "4 ore", "presi_in_tempo": 3, "presi_in_ritardo": 0, "non_presi": 0, "mediana_ore": 1.5},
    "incidenti": {"aperti": 1, "chiusi": 2, "chiusi_con_riesame": 2, "senza_riesame": [], "azioni_scadute": 0},
    "evidenze": {"totali": 4, "verificate": 4, "alterate": 0},
    "ruoli": {"completi": True, "mancanti": []},
    "ripristini": {"ultimo_test": "2026-10-10", "esito_ultimo": "riuscito", "in_ritardo": False, "test_periodo": 1, "falliti_periodo": 0},
}
SLA_OK = {"classi": [{"classe": "critica", "etichetta": "Critica", "giorni": 7, "corrette": 2, "in_tempo": 2, "in_ritardo": 0, "aperte": 0, "aperte_scadute": 0}],
          "aperte_scadute": [], "percentuale_in_tempo": 100}


def _moduli(**finti):
    """``_modulo`` finto: ritorna il modulo simulato o None."""
    return lambda nome: finti.get(nome)


def _finto(riepilogo):
    return SimpleNamespace(riepilogo=lambda dal, al: riepilogo)


class PeriodoTests(TestCase):
    def test_preset(self):
        self.assertEqual(iso27001.periodo("mese_scorso", oggi=OGGI)[:2], (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(iso27001.periodo("mese_corrente", oggi=OGGI)[:2], (date(2026, 10, 1), OGGI))
        self.assertEqual(iso27001.periodo("sconosciuto", oggi=OGGI)[3], "mese_corrente")
        dal, al, etichetta, preset = iso27001.periodo("libero", date(2026, 3, 10), date(2026, 3, 1), oggi=OGGI)
        self.assertEqual((dal, al, preset), (date(2026, 3, 1), date(2026, 3, 10), "libero"))
        self.assertEqual(iso27001.mese_precedente(OGGI), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(iso27001.etichetta_mese(date(2026, 9, 1), date(2026, 9, 30)), "settembre 2026")


class ControlliTests(TestCase):
    def _esito(self, codice, **finti):
        with mock.patch.object(iso27001, "_modulo", _moduli(**finti)):
            return iso27001.verifica_controllo(iso27001.PER_CODICE[codice], DAL, AL)

    def test_servizi_assenti_dicono_non_disponibile(self):
        for codice in ("5.24", "5.25", "5.26", "5.27", "5.28", "5.30", "8.8"):
            esito = self._esito(codice)
            self.assertEqual(esito["stato"], iso27001.NON_DISPONIBILE, codice)
            self.assertTrue(esito["azioni"], codice)

    def test_incidenti_con_servizio(self):
        for codice in ("5.24", "5.25", "5.26", "5.27", "5.28", "5.30"):
            self.assertEqual(self._esito(codice, iso_incidenti=_finto(INCIDENTI_OK))["stato"], iso27001.OK, codice)
        ko = {**INCIDENTI_OK, "incidenti": {"aperti": 0, "chiusi": 1, "chiusi_con_riesame": 0, "senza_riesame": [{"id": 1, "titolo": "Phishing", "chiuso_il": "2026-10-03"}], "azioni_scadute": 2},
              "triage": {"target": "4 ore", "presi_in_tempo": 1, "presi_in_ritardo": 1, "non_presi": 0, "mediana_ore": 5},
              "ruoli": {"completi": False, "mancanti": ["Responsabile degli incidenti"]}, "evidenze": {"totali": 2, "verificate": 1, "alterate": 1},
              "ripristini": {"ultimo_test": None, "esito_ultimo": "", "in_ritardo": True, "test_periodo": 0, "falliti_periodo": 0}}
        self.assertEqual(self._esito("5.24", iso_incidenti=_finto(ko))["stato"], iso27001.NON_CONFORME)
        self.assertEqual(self._esito("5.25", iso_incidenti=_finto(ko))["stato"], iso27001.ATTENZIONE)
        self.assertEqual(self._esito("5.26", iso_incidenti=_finto(ko))["stato"], iso27001.NON_CONFORME)
        e = self._esito("5.27", iso_incidenti=_finto(ko))
        self.assertEqual(e["stato"], iso27001.NON_CONFORME)
        self.assertIn("Phishing", e["frase"])
        self.assertEqual(self._esito("5.28", iso_incidenti=_finto(ko))["stato"], iso27001.NON_CONFORME)
        self.assertEqual(self._esito("5.30", iso_incidenti=_finto(ko))["stato"], iso27001.NON_CONFORME)

    def test_vulnerabilita_con_sla(self):
        e = self._esito("8.8", cve_sla=_finto(SLA_OK))
        self.assertEqual(e["stato"], iso27001.OK)
        self.assertEqual(e["numeri"]["corrette_in_tempo_pct"], 100)
        self.assertTrue(e["numeri_tabelle"])  # le classi come tabella
        scadute = {**SLA_OK, "percentuale_in_tempo": 85,
                   "aperte_scadute": [{"cve": "CVE-2099-1", "host": "PC-01", "classe": "alta", "scadenza": "2026-10-01", "giorni_ritardo": 9, "accettata": False}]}
        e = self._esito("8.8", cve_sla=_finto(scadute))
        self.assertEqual(e["stato"], iso27001.NON_CONFORME)
        self.assertIn("CVE-2099-1 su PC-01", e["azioni"][0])
        accettate = {**scadute, "aperte_scadute": [{**scadute["aperte_scadute"][0], "accettata": True}]}
        self.assertEqual(self._esito("8.8", cve_sla=_finto(accettate))["stato"], iso27001.ATTENZIONE)

    def test_threat_intelligence(self):
        soc_settings.save({"cve.arricchimento.attivo": False}, None)
        self.assertEqual(self._esito("5.7")["stato"], iso27001.NON_CONFORME)
        soc_settings.save({"cve.arricchimento.attivo": True}, None)
        self.assertEqual(self._esito("5.7")["stato"], iso27001.NON_CONFORME)  # mai riuscita
        ora = timezone.now()
        SecurityLetturaLog.objects.create(codice="cve", stato="ok", avviata_il=ora - timedelta(hours=1), finita_il=ora)
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0001", kev=True, nvd_fetched_at=ora)
        e = iso27001.verifica_controllo(iso27001.PER_CODICE["5.7"], timezone.localdate() - timedelta(days=3), timezone.localdate())
        self.assertEqual(e["stato"], iso27001.OK)
        self.assertEqual(e["numeri"]["cve_sfruttate_kev"], 1)
        SecurityLetturaLog.objects.update(avviata_il=ora - timedelta(hours=30))
        e = iso27001.verifica_controllo(iso27001.PER_CODICE["5.7"], timezone.localdate() - timedelta(days=3), timezone.localdate())
        self.assertEqual(e["stato"], iso27001.ATTENZIONE)

    def test_segnalazione_eventi(self):
        e = self._esito("6.8")
        self.assertEqual(e["stato"], iso27001.ATTENZIONE)
        self.assertIn("da definire", e["frase"])
        soc_settings.save({"iso.segnalazioni.canale": "soc@esempio.local"}, None)
        self.assertEqual(self._esito("6.8")["stato"], iso27001.OK)

    def test_malware_senza_dispositivi(self):
        self.assertEqual(self._esito("8.7")["stato"], iso27001.NON_DISPONIBILE)
        righe = [{"nome": "PC-01", "watchguard": True, "defender": False}, {"nome": "PC-02", "watchguard": False, "defender": False}]
        with mock.patch("security.services.pc_copertura.righe", return_value=righe):
            e = self._esito("8.7")
        self.assertEqual(e["stato"], iso27001.NON_CONFORME)  # 50 %
        self.assertIn("PC-02", e["azioni"][0])

    def test_backup(self):
        self.assertEqual(self._esito("8.13")["stato"], iso27001.NON_DISPONIBILE)
        src = SecuritySource.objects.create(name="Veeam", source_type="email")
        for stato in ("completed", "completed", "failed"):
            BackupJobRecord.objects.create(source=src, job_name="Job", status=stato, dedup_hash=f"h{stato}{timezone.now().timestamp()}")
        with mock.patch("security.services.pc_copertura.righe", return_value=[]):
            e = iso27001.verifica_controllo(iso27001.PER_CODICE["8.13"], timezone.localdate() - timedelta(days=1), timezone.localdate())
        self.assertEqual(e["stato"], iso27001.NON_CONFORME)
        self.assertEqual(e["numeri"]["falliti"], 1)

    def test_logging_e_orologi(self):
        from registro_log.models import FonteLog, Impostazioni, SigilloGiorno

        self.assertEqual(self._esito("8.15")["stato"], iso27001.NON_CONFORME)  # spento
        imp = Impostazioni.corrente()
        imp.attivo = True
        imp.save()
        ieri = timezone.localdate() - timedelta(days=1)
        SigilloGiorno.objects.create(giorno=ieri, hash_precedente="0" * 64, hash_sigillo="1" * 64, verifica_ok=True)
        e = iso27001.verifica_controllo(iso27001.PER_CODICE["8.15"], ieri, timezone.localdate())
        self.assertEqual(e["stato"], iso27001.OK)
        SigilloGiorno.objects.update(verifica_ok=False)
        e = iso27001.verifica_controllo(iso27001.PER_CODICE["8.15"], ieri, timezone.localdate())
        self.assertEqual(e["stato"], iso27001.NON_CONFORME)
        self.assertEqual(self._esito("8.17")["stato"], iso27001.NON_DISPONIBILE)
        FonteLog.objects.create(nome="ESXi", tipo="syslog", attiva=True, scarto_orologio_s=12)
        self.assertEqual(self._esito("8.17")["stato"], iso27001.OK)
        FonteLog.objects.create(nome="Switch", tipo="syslog", attiva=True, scarto_orologio_s=-400)
        e = self._esito("8.17")
        self.assertEqual(e["stato"], iso27001.NON_CONFORME)
        self.assertIn("Switch", e["azioni"][0])

    def test_monitoraggio(self):
        e = self._esito("8.16")
        self.assertEqual(e["stato"], iso27001.NON_CONFORME)  # coda dei lavori mai partita
        self.assertIn("coda", e["frase"].lower())
        Schedule.objects.create(name="security_cve_enrichment", func="security.tasks.enrich_cve_task", schedule_type="H", repeats=-1,
                                next_run=timezone.now() + timedelta(minutes=5))
        soc_settings.save({"cve.arricchimento.attivo": True}, None)
        ora = timezone.now()
        for h in range(1, 6):
            SecurityLetturaLog.objects.create(codice="cve", stato="ok", avviata_il=ora - timedelta(hours=h), finita_il=ora - timedelta(hours=h))
        e = iso27001.verifica_controllo(iso27001.PER_CODICE["8.16"], timezone.localdate() - timedelta(days=2), timezone.localdate())
        self.assertIn(e["stato"], (iso27001.ATTENZIONE, iso27001.NON_CONFORME))  # 5 giri su 48 attesi circa
        self.assertEqual(e["numeri"]["giri_riusciti"], 5)
        self.assertGreater(e["numeri"]["giri_attesi"], 5)

    def test_valuta_e_registri(self):
        with mock.patch.object(iso27001, "_modulo", _moduli()):
            v = iso27001.valuta(DAL, AL)
        self.assertEqual(v["conteggi"]["totale"], len(iso27001.CONTROLLI))
        self.assertEqual(sum(v["conteggi"][s] for s, _l in iso27001.STATI), len(iso27001.CONTROLLI))
        self.assertTrue(all(c["stato_label"] for c in v["controlli"]))
        self.assertIn("pacchetto_iso", letture.PER_CODICE)
        self.assertEqual(battito.SCHEDULE_DI_LETTURA["pacchetto_iso"][0], "security_pacchetto_iso")
        from automazioni.schedules import SCHEDULES

        s = next(x for x in SCHEDULES if x["name"] == "security_pacchetto_iso")
        self.assertEqual((s["func"], s["cron"]), ("security.tasks.pacchetto_iso_task", "30 6 1 * *"))


class PacchettoTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = override_settings(PRIVATE_ATTACHMENTS_ROOT=self.tmp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.tmp.cleanup)
        cve = SecurityCveRecord.objects.create(cve_id="CVE-2099-0002", cvss=9.1)
        ora = timezone.now()
        SecurityCveRisoluzione.objects.create(cve=cve, host="pc-01", host_display="PC-01", software="Acme Viewer", versione_prima="1.0",
                                              versione_dopo="2.0", come="aggiornato", aperta_dal=ora - timedelta(days=4), risolta_il=ora - timedelta(days=1))
        SecurityIncident.objects.create(title="Mail sospetta", status="closed", detected_at=ora - timedelta(days=2), resolved_at=ora - timedelta(days=1))
        self.admin = get_user_model().objects.create(username="iso_admin", is_staff=True, is_superuser=True)

    def test_genera_archivia_con_impronta_e_audit(self):
        from core.models import AuditLog

        dal, al = timezone.localdate() - timedelta(days=10), timezone.localdate()
        with mock.patch.object(iso27001, "_modulo", _moduli(cve_sla=_finto(SLA_OK), iso_incidenti=_finto(INCIDENTI_OK))):
            p = iso_pacchetto.genera(dal, al, utente=self.admin)
        self.assertTrue(p.file.name.startswith("security/iso27001/"))
        contenuto = p.file.storage.open(p.file.name, "rb").read()
        self.assertTrue(contenuto.startswith(b"%PDF"))
        self.assertEqual(len(p.sha256), 64)
        self.assertEqual(p.riepilogo["correzioni"], 1)
        self.assertEqual(p.riepilogo["incidenti"], 1)
        self.assertEqual(p.copia_esito, "")  # copia SharePoint spenta
        audit = AuditLog.objects.get(azione="pacchetto_iso_generato")
        self.assertEqual(audit.dettaglio["sha256"], p.sha256)

    def test_giro_mensile_non_duplica(self):
        with mock.patch.object(iso27001, "_modulo", _moduli()):
            out = iso_pacchetto.giro_mensile()
            self.assertIn("sha256", out)
            self.assertEqual(SecurityPacchettoIso.objects.filter(automatico=True).count(), 1)
            self.assertIn("già generato", iso_pacchetto.giro_mensile()["skipped"])
        self.assertEqual(letture.esito(out)[0], SecurityLetturaLog.OK)

    def test_pagina_genera_e_scarica(self):
        from core.models import AuditLog

        self.client.force_login(self.admin)
        with mock.patch.object(iso27001, "_modulo", _moduli()):
            r = self.client.get(reverse("security:iso27001") + "?periodo=mese_scorso")
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Conformità ISO 27001")
            self.assertContains(r, "Threat intelligence")
            self.assertContains(r, "Genera ora")
            self.assertContains(r, "Dato non disponibile")
            self.assertNotIn("{%", r.content.decode())
            r = self.client.post(reverse("security:iso27001"), {"periodo": "mese_scorso"})
        self.assertEqual(r.status_code, 302)
        p = SecurityPacchettoIso.objects.get()
        self.assertEqual(p.generato_da, self.admin)
        self.assertFalse(p.automatico)
        r = self.client.get(reverse("security:iso27001_pacchetto", args=[p.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(AuditLog.objects.filter(azione="pacchetto_iso_scaricato").exists())
        utente = get_user_model().objects.create(username="iso_semplice")
        self.client.force_login(utente)
        self.assertIn(self.client.post(reverse("security:iso27001"), {"periodo": "mese_scorso"}).status_code, (302, 403))  # negato
        self.assertEqual(SecurityPacchettoIso.objects.count(), 1)
