"""Test del Registro accessi. Solo dati sintetici (account e host inventati)."""
from __future__ import annotations

import gzip
import json
import queue
import shutil
import tempfile
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import archivio, regole
from .models import (
    AccountAD,
    AmministratoreSistema,
    EventoRegistro,
    FonteLog,
    Impostazioni,
    Interruzione,
    SigilloGiorno,
    StatoRaccoglitore,
)

NS = "http://schemas.microsoft.com/win/2004/08/events/event"


def evento_xml(event_id: int, record: int, dati: dict, canale="Security", pc="DC01.esempio.local",
               quando="2026-10-20T08:15:30.1234567Z") -> str:
    campi = "".join(f'<Data Name="{k}">{v}</Data>' for k, v in dati.items())
    return (f'<Event xmlns="{NS}"><System><Provider Name="Microsoft-Windows-Security-Auditing"/>'
            f"<EventID>{event_id}</EventID><TimeCreated SystemTime=\"{quando}\"/><EventRecordID>{record}</EventRecordID>"
            f"<Channel>{canale}</Channel><Computer>{pc}</Computer></System><EventData>{campi}</EventData></Event>")


class _ConArchivio(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="reglog-"))
        imp = Impostazioni.corrente()
        imp.cartella_archivio = str(self.tmp)
        imp.save()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class ArchivioTests(_ConArchivio):
    def _scrivi_giorno(self, giorno: date, righe: int):
        s = archivio.Scrittore()
        ora = timezone.make_aware(datetime.combine(giorno, time(10, 0)))
        for i in range(righe):
            s.scrivi(1, {"id": 4624, "i": i}, ora + timedelta(seconds=i))
        s.chiudi()

    def test_catena_sigillo_e_verifica(self):
        g = date(2026, 10, 1)
        self._scrivi_giorno(g, 5)
        sig = archivio.sigilla(g)
        self.assertEqual(sig.righe, 5)
        self.assertTrue(sig.verifica_ok)
        self.assertTrue(archivio.percorso_gz(g).exists())
        self.assertFalse(archivio.percorso(g).exists())
        ok, testo = archivio.verifica_sigillo(sig)
        self.assertTrue(ok, testo)
        self.assertEqual(archivio.leggi_riga(g, 3)["d"]["i"], 2)

    def test_riga_modificata_rompe_la_verifica(self):
        g = date(2026, 10, 2)
        self._scrivi_giorno(g, 4)
        sig = archivio.sigilla(g)
        gz = archivio.percorso_gz(g)
        righe = gzip.open(gz, "rt", encoding="utf-8").read().splitlines()
        riga = json.loads(righe[1])
        riga["d"]["i"] = 99
        righe[1] = archivio.canonica(riga)
        with gzip.open(gz, "wt", encoding="utf-8") as fh:
            fh.write("\n".join(righe) + "\n")
        ok, testo = archivio.verifica_sigillo(sig)
        self.assertFalse(ok)
        self.assertIn("cambiato", testo)

    def test_giorni_legati_e_giorno_aperto_non_sigillato(self):
        oggi = date(2026, 10, 10)
        for g in (date(2026, 10, 7), date(2026, 10, 9)):
            self._scrivi_giorno(g, 2)
        creati = archivio.sigilla_mancanti(oggi, giorno_aperto=date(2026, 10, 9))
        self.assertEqual([s.giorno for s in creati], [date(2026, 10, 7), date(2026, 10, 8)])
        vuoto = SigilloGiorno.objects.get(giorno=date(2026, 10, 8))
        self.assertEqual(vuoto.righe, 0)
        self.assertEqual(vuoto.hash_precedente, SigilloGiorno.objects.get(giorno=date(2026, 10, 7)).hash_sigillo)
        archivio.sigilla_mancanti(oggi)
        self.assertTrue(SigilloGiorno.objects.filter(giorno=date(2026, 10, 9)).exists())
        self.assertEqual(archivio.verifica(SigilloGiorno.objects.all())["rotti"], [])

    def test_ripresa_dopo_riga_tagliata(self):
        g = date(2026, 10, 3)
        self._scrivi_giorno(g, 3)
        p = archivio.percorso(g)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write('{"d":{"id":1')  # arresto a metà scrittura
        s = archivio.Scrittore()
        s.scrivi(1, {"id": 1}, timezone.make_aware(datetime.combine(g, time(11, 0))))
        s.chiudi()
        self.assertEqual(s.n, 4)
        self.assertTrue(s.riparazioni)
        sig = archivio.sigilla(g)
        self.assertTrue(sig.verifica_ok, sig.verifica_esito)
        self.assertEqual(sig.righe, 4)

    def test_conservazione_mai_sotto_sei_mesi(self):
        imp = Impostazioni.corrente()
        imp.conservazione_mesi = 1
        imp.save()
        vecchio = date(2026, 1, 5)
        self._scrivi_giorno(vecchio, 1)
        archivio.sigilla(vecchio)
        esito = archivio.applica_conservazione(oggi=date(2026, 5, 1))
        self.assertEqual(esito["giorni_eliminati"], 0)
        esito = archivio.applica_conservazione(oggi=date(2026, 8, 1))
        self.assertEqual(esito["giorni_eliminati"], 1)
        s = SigilloGiorno.objects.get(giorno=vecchio)
        self.assertIsNotNone(s.eliminato_il)
        self.assertTrue(archivio.verifica_sigillo(s)[0])


class RegoleWindowsTests(TestCase):
    def _d(self, xml):
        from defusedxml import ElementTree

        return regole.normalizza_windows(ElementTree.fromstring(xml))

    def test_accesso_desktop_remoto(self):
        d = self._d(evento_xml(4624, 10, {"TargetUserName": "mrossi", "TargetDomainName": "ESEMPIO", "LogonType": "10",
                                          "IpAddress": "10.0.0.5"}))
        self.assertEqual(d["id"], 4624)
        self.assertEqual(d["rec"], 10)
        idx = regole.classifica_windows(d)
        self.assertEqual(idx.categoria, "accesso")
        self.assertEqual(idx.tipo_accesso, "Desktop remoto")
        self.assertEqual(idx.ip_origine, "10.0.0.5")
        self.assertEqual(regole.quando_windows(d), datetime(2026, 10, 20, 8, 15, 30, 123456, tzinfo=dt_timezone.utc))

    def test_accesso_di_rete_solo_per_amministratori(self):
        d = self._d(evento_xml(4624, 11, {"TargetUserName": "mrossi", "LogonType": "3"}))
        self.assertIsNone(regole.classifica_windows(d))
        self.assertEqual(regole.classifica_windows(d, {"mrossi"}).categoria, "accesso")
        macchina = self._d(evento_xml(4624, 12, {"TargetUserName": "PC01$", "LogonType": "10"}))
        self.assertIsNone(regole.classifica_windows(macchina))

    def test_accesso_fallito_con_motivo(self):
        d = self._d(evento_xml(4625, 13, {"TargetUserName": "mrossi", "SubStatus": "0xC000006A", "LogonType": "3"}))
        idx = regole.classifica_windows(d)
        self.assertEqual((idx.categoria, idx.esito), ("accesso_fallito", "ko"))
        self.assertIn("password sbagliata", idx.descrizione)

    def test_gruppo_di_amministratori(self):
        d = self._d(evento_xml(4728, 14, {"TargetUserName": "Domain Admins", "MemberName": "CN=Prova Test,OU=IT,DC=esempio",
                                          "SubjectUserName": "admin.it"}))
        idx = regole.classifica_windows(d)
        self.assertEqual(idx.categoria, "gruppo_privilegiato")
        self.assertIn("Prova Test", idx.descrizione)
        self.assertEqual(idx.gravita, "high")

    def test_registro_cancellato(self):
        xml = (f'<Event xmlns="{NS}"><System><Provider Name="Microsoft-Windows-Eventlog"/><EventID>1102</EventID>'
               f'<TimeCreated SystemTime="2026-10-20T08:00:00Z"/><EventRecordID>15</EventRecordID><Channel>Security</Channel>'
               f'<Computer>DC01</Computer></System><UserData><LogFileCleared xmlns="http://manifests.microsoft.com/win/2004/08/windows/eventlog">'
               f"<SubjectUserName>admin.it</SubjectUserName></LogFileCleared></UserData></Event>")
        idx = regole.classifica_windows(self._d(xml))
        self.assertEqual(idx.categoria, "registro_cancellato")
        self.assertEqual(idx.account, "admin.it")

    def test_xpath_sotto_il_limite_di_windows(self):
        q = regole.xpath("Security", 100, tutto=False, fino_a=200)
        self.assertIn("EventRecordID > 100", q)
        self.assertIn("EventRecordID <= 200", q)
        self.assertLessEqual(q.count(" or "), 20)
        self.assertEqual(regole.xpath("ForwardedEvents", None, tutto=True), "*")


class RegoleSyslogTests(TestCase):
    def test_esxi_ssh(self):
        d = regole.parse_syslog(b"<38>2026-10-20T08:00:00.000Z esx01.esempio.local sshd[123]: Accepted password for root "
                                b"from 10.0.0.9 port 51000 ssh2", "10.0.0.20")
        self.assertEqual(d["host"], "esx01.esempio.local")
        idx = regole.classifica_syslog(d)
        self.assertEqual((idx.categoria, idx.account, idx.ip_origine), ("accesso", "root", "10.0.0.9"))

    def test_rfc5424_e_cisco(self):
        d = regole.parse_syslog(b"<189>1 2026-10-20T08:00:00Z sw01 - - - - %SEC_LOGIN-4-LOGIN_FAILED: Login failed "
                                b"[user: admin] [Source: 10.0.0.7] [localport: 22]", "10.0.0.2")
        self.assertEqual(d["host"], "sw01")
        idx = regole.classifica_syslog(d)
        self.assertEqual((idx.categoria, idx.account, idx.ip_origine), ("accesso_fallito", "admin", "10.0.0.7"))

    def test_rfc3164_sudo_e_messaggio_qualsiasi(self):
        d = regole.parse_syslog(b"<86>Oct 20 08:00:00 srv01 sudo:   tecnico : TTY=pts/0 ; PWD=/root ; USER=root ; "
                                b"COMMAND=/usr/bin/systemctl restart nginx", "10.0.0.30")
        self.assertEqual(d["app"], "sudo")
        idx = regole.classifica_syslog(d)
        self.assertEqual(idx.categoria, "comando_privilegiato")
        self.assertIsNone(regole.classifica_syslog(regole.parse_syslog(b"<14>Oct 20 08:00:01 sw01 link up on port 3", "x")))

    def test_ora_syslog_senza_anno(self):
        ricevuto = timezone.make_aware(datetime(2026, 1, 1, 0, 0, 5))
        quando = regole.quando_syslog({"t": "Dec 31 23:59:58"}, ricevuto)
        self.assertEqual(quando.year, 2025)


class WindowsLetturaTests(TestCase):
    def test_segnalibro_ed_eventi_sovrascritti(self):
        from .sorgenti import windows

        uno = evento_xml(4624, 120, {"TargetUserName": "mrossi", "LogonType": "10"})
        risposte = {
            ("qe", "/rd:true"): f"<Events>{evento_xml(4634, 130, {})}</Events>",
            ("gli",): "name: Security\noldestRecordNumber: 110\n",
            ("qe", "/q"): f"<Events>{uno}</Events>",
        }

        def finto(args, timeout=0):
            if args[0] == "gli":
                return risposte[("gli",)]
            if "/rd:true" in args:
                return risposte[("qe", "/rd:true")]
            return risposte[("qe", "/q")]

        with mock.patch.object(windows, "esegui", side_effect=finto):
            esito = windows.leggi_canale("Security", "DC01", 100, tutto=False)
        self.assertEqual(esito.persi, 9)
        self.assertEqual(esito.segnalibro, 130)
        self.assertEqual([e["rec"] for e in esito.eventi], [120])

    def test_messaggio_accesso_negato(self):
        from .sorgenti import windows

        self.assertIn("Event Log Readers", windows.spiega_errore("Failed to read events. Access is denied."))


class RaccoglitoreTests(_ConArchivio):
    def test_scrittore_archivia_indicizza_e_salva_segnalibro(self):
        from .raccoglitore import Raccoglitore

        dc = FonteLog.objects.create(nome="DC01", tipo=FonteLog.TIPO_WINDOWS, ruolo="dc", host="DC01")
        esx = FonteLog.objects.create(nome="ESX01", tipo=FonteLog.TIPO_SYSLOG, ruolo="esxi", indirizzi_ip="10.0.0.20")
        AmministratoreSistema.objects.create(nome="Admin Prova", account="ESEMPIO\\admin.it")
        r = Raccoglitore()
        r.carica()
        self.assertEqual(r.fonte_per_ip("10.0.0.20"), esx.pk)
        self.assertIn("admin.it", r.privilegiati)
        from defusedxml import ElementTree

        dati = regole.normalizza_windows(ElementTree.fromstring(evento_xml(
            4624, 50, {"TargetUserName": "admin.it", "LogonType": "3", "IpAddress": "10.0.0.5"})))
        ora = timezone.now()
        r.coda.put(("windows", dc.pk, dati, ora))
        r.coda.put(("windows", dc.pk, dict(dati, rec=51), ora))  # stesso accesso: dedup nell'indice, non nell'archivio
        r.coda.put(("segnalibro", dc.pk, "Security", 51))
        r.coda.put(("syslog", esx.pk, b"<38>Oct 20 08:00:00 esx01 sshd[1]: Failed password for root from 10.0.0.9 port 1 ssh2",
                    "10.0.0.20", ora))
        r._fermo.set()
        r.ciclo_scrittore()
        self.assertEqual(r.scrittore.n, 3)
        ev = list(EventoRegistro.objects.order_by("id"))
        self.assertEqual([e.categoria for e in ev], ["accesso", "accesso_fallito"])
        self.assertTrue(ev[0].privilegiato)
        self.assertEqual(ev[0].archivio_riga, 1)
        dc.refresh_from_db()
        self.assertEqual(dc.segnalibri, {"Security": 51})
        self.assertEqual(dc.righe_oggi, 2)

    def test_battito_annota_le_righe_riparate(self):
        from .raccoglitore import Raccoglitore

        r = Raccoglitore()
        r.carica()
        r.scrittore.riparazioni.append("registro-x.jsonl: tolta una riga incompleta")
        r.battito()
        self.assertTrue(Interruzione.objects.filter(motivo="file_riparato").exists())
        self.assertIsNotNone(StatoRaccoglitore.objects.get(pk=1).battito_il)


class SyslogRicevitoreTests(TestCase):
    def test_indirizzi_ammessi_e_limite(self):
        from .sorgenti.syslog import Ricevitore

        coda = queue.Queue()
        r = Ricevitore("127.0.0.1", 0, False, coda, {"10.0.0.20": 7}.get)
        r.limitatore.al_secondo = 2
        self.assertFalse(r.ricevi(b"<14>ciao", "10.9.9.9"))
        self.assertTrue(r.ricevi(b"<14>uno", "10.0.0.20"))
        self.assertTrue(r.ricevi(b"<14>due", "10.0.0.20"))
        self.assertFalse(r.ricevi(b"<14>tre", "10.0.0.20"))
        scartati, sconosciuti = r.preleva_contatori()
        self.assertEqual((scartati["10.0.0.20"], sconosciuti["10.9.9.9"]), (1, 1))
        self.assertEqual(coda.qsize(), 2)


class CicloTests(_ConArchivio):
    def setUp(self):
        super().setUp()
        imp = Impostazioni.corrente()
        imp.attivo = True
        imp.save()

    def test_raccoglitore_fermo_apre_e_chiude_interruzione(self):
        from . import ciclo

        StatoRaccoglitore.objects.create(pk=1, battito_il=timezone.now() - timedelta(minutes=30))
        ciclo.controlla_raccoglitore()
        aperta = Interruzione.objects.get(motivo="raccoglitore_fermo")
        self.assertIsNone(aperta.al)
        StatoRaccoglitore.objects.filter(pk=1).update(battito_il=timezone.now(), avviato_il=timezone.now())
        ciclo.controlla_raccoglitore()
        aperta.refresh_from_db()
        self.assertIsNotNone(aperta.al)

    def test_evento_critico_diventa_alert_del_soc(self):
        from security.models import SecurityAlert, SecurityCenterSetting

        from . import ciclo

        for chiave in ("registro.alert.attivo", "registro.alert.gruppo_privilegiato"):
            SecurityCenterSetting.objects.update_or_create(key=chiave, defaults={"value": True, "value_type": "bool",
                                                                                 "category": "avvisi"})
        ev = EventoRegistro.objects.create(quando=timezone.now(), categoria="gruppo_privilegiato", gravita="high",
                                           host="DC01", account="admin.it",
                                           descrizione="utente.prova aggiunto al gruppo «Domain Admins» da admin.it")
        EventoRegistro.objects.create(quando=timezone.now(), categoria="accesso", host="DC01", account="mrossi")
        esito = ciclo.invia_al_soc()
        self.assertEqual(esito["eventi_soc"], 1)
        self.assertTrue(SecurityAlert.objects.filter(title__icontains="Domain Admins").exists())
        self.assertFalse(EventoRegistro.objects.filter(inviato_soc=False).exists())
        self.assertEqual(ciclo.invia_al_soc()["eventi_soc"], 0)
        self.assertTrue(ev.pk)

    def test_spento_non_fa_nulla(self):
        from . import ciclo

        imp = Impostazioni.corrente()
        imp.attivo = False
        imp.save()
        self.assertEqual(ciclo.esegui(), {"attivo": False})


class AdTests(TestCase):
    def test_abbinamento_e_segnalazioni(self):
        from . import ad

        utenti = [
            {"sAMAccountName": "mrossi", "mail": "m.rossi@esempio.it", "userAccountControl": 512,
             "lastLogonTimestamp": 133700000000000000, "displayName": "Mario Rossi"},
            {"sAMAccountName": "ex.dip", "mail": "ex.dip@esempio.it", "userAccountControl": 66048},
            {"sAMAccountName": "svc-backup", "userAccountControl": 66048},
        ]
        indice = {
            "m.rossi@esempio.it": {"id": 1, "nome": "Mario Rossi", "cessato_il": None},
            "ex.dip@esempio.it": {"id": 2, "nome": "Ex Dipendente", "cessato_il": date(2026, 1, 31)},
        }
        esito = ad.applica(utenti, {"mrossi": ["Domain Admins"]}, indice)
        self.assertEqual(esito["account"], 3)
        self.assertEqual(esito["cessati_attivi"], 1)
        m = AccountAD.objects.get(sam="mrossi")
        self.assertEqual((m.anagrafica_id, m.tipo, m.gruppi_privilegiati), (1, "persona", ["Domain Admins"]))
        self.assertIsNotNone(m.ultimo_accesso)
        titoli = [s["titolo"] for s in ad.segnalazioni()]
        self.assertIn("Ex dipendenti con l'account ancora attivo", titoli)
        self.assertIn("Amministratori senza nomina", titoli)
        self.assertIn("Account senza una persona", titoli)
        AmministratoreSistema.objects.create(nome="Mario Rossi", account="mrossi")
        self.assertNotIn("Amministratori senza nomina", [s["titolo"] for s in ad.segnalazioni()])
        ad.applica(utenti[:1], {}, indice)
        self.assertIsNotNone(AccountAD.objects.get(sam="svc-backup").sparito_il)


class ReportTests(_ConArchivio):
    def test_riepilogo_e_pdf(self):
        from . import report

        AmministratoreSistema.objects.create(nome="Admin Prova", account="admin.it", nominato_il=date(2026, 1, 1))
        EventoRegistro.objects.create(quando=timezone.now(), categoria="accesso", host="DC01", account="ESEMPIO\\admin.it",
                                      fuori_orario=True, privilegiato=True)
        c = report.riepilogo(timezone.localdate().year)
        self.assertEqual(c["amministratori"][0]["accessi"], 1)
        self.assertEqual(c["amministratori"][0]["fuori_orario"], 1)
        voce = next(x for x in c["controlli"] if x["voce"].startswith("Ogni amministratore ha la nomina"))
        self.assertFalse(voce["ok"])
        self.assertEqual(len(c["impronta"]), 64)
        self.assertTrue(report.pdf(c).startswith(b"%PDF"))


class RouterTests(TestCase):
    def test_tabelle_nel_database_a_parte_solo_se_configurato(self):
        from .router import RegistroLogRouter

        r = RegistroLogRouter()
        self.assertTrue(r.allow_migrate("default", "registro_log"))
        with override_settings(DATABASES={"default": {}, "registro_log": {}}):
            self.assertFalse(r.allow_migrate("default", "registro_log"))
            self.assertTrue(r.allow_migrate("registro_log", "registro_log"))
            self.assertFalse(r.allow_migrate("registro_log", "security"))
            self.assertEqual(r.db_for_read(EventoRegistro), "registro_log")


class PagineTests(_ConArchivio):
    def setUp(self):
        super().setUp()
        from core.models import UserOnboarding

        User = get_user_model()
        self.admin = User.objects.create_user("admin.soc", password="pass-di-prova-123", is_staff=True, is_superuser=True)
        UserOnboarding.objects.update_or_create(user=self.admin, defaults={"completed": True})
        self.client.force_login(self.admin)
        self.fonte = FonteLog.objects.create(nome="DC01", tipo=FonteLog.TIPO_WINDOWS, ruolo="dc", host="DC01")
        self.ev = EventoRegistro.objects.create(quando=timezone.now(), categoria="accesso", host="DC01", account="mrossi",
                                                descrizione="Accesso desktop remoto", fonte_id=self.fonte.pk, fonte_nome="DC01")

    def test_tutte_le_pagine_si_aprono(self):
        AmministratoreSistema.objects.create(nome="Admin Prova", account="admin.it")
        AccountAD.objects.create(sam="mrossi", gruppi_privilegiati=["Domain Admins"])
        rotte = ["registro_log", "registro_log_eventi", "registro_log_ads", "registro_log_account", "registro_log_verifica",
                 "registro_log_archivio", "registro_log_fonti", "registro_log_infra"]
        for nome in rotte:
            r = self.client.get(reverse(f"security:{nome}"))
            self.assertEqual(r.status_code, 200, nome)
            testo = r.content.decode()
            self.assertNotIn("{#", testo, nome)
            self.assertNotIn("{%", testo, nome)
        r = self.client.get(reverse("security:registro_log_evento", args=[self.ev.pk]))
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse("security:registro_log_eventi") + "?vista=ads&giorni=30&q=mrossi")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse("security:registro_log_verifica") + "?pdf=1")
        self.assertEqual(r["Content-Type"], "application/pdf")

    def test_salva_fonte_e_impostazioni(self):
        r = self.client.post(reverse("security:registro_log_fonti"), {
            "azione": "fonte", "nome": "ESX01", "tipo": "syslog", "ruolo": "esxi", "indirizzi_ip": "10.0.0.20; 10.0.0.21",
            "canali": "", "eventi": "accessi", "silenzio_max_ore": 24, "attiva": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(FonteLog.objects.get(nome="ESX01").lista_ip(), ["10.0.0.20", "10.0.0.21"])
        r = self.client.post(reverse("security:registro_log_fonti"), {
            "azione": "fonte", "nome": "Sbagliata", "tipo": "syslog", "ruolo": "esxi", "indirizzi_ip": "non-un-ip",
            "eventi": "accessi", "silenzio_max_ore": 24})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FonteLog.objects.filter(nome="Sbagliata").exists())
        r = self.client.post(reverse("security:registro_log_fonti"), {
            "azione": "impostazioni", "attivo": "on", "conservazione_mesi": 3, "syslog_indirizzo": "0.0.0.0",
            "syslog_porta": 514, "orario_inizio": "07:00", "orario_fine": "19:00"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "almeno 6 mesi")

    def test_utente_senza_permessi_non_entra(self):
        from core.models import UserOnboarding

        utente = get_user_model().objects.create_user("operaio.prova", password="pass-di-prova-123")
        UserOnboarding.objects.update_or_create(user=utente, defaults={"completed": True})
        self.client.force_login(utente)
        r = self.client.get(reverse("security:registro_log"))
        self.assertIn(r.status_code, (302, 403))
        r = self.client.post(reverse("security:registro_log_fonti"), {"azione": "elimina", "id": self.fonte.pk})
        self.assertIn(r.status_code, (302, 403))
        self.fonte.refresh_from_db()
        self.assertTrue(self.fonte.attiva)


class FileStampeUsbTests(TestCase):
    def test_file_eliminato_modificato_e_letture_solo_a_richiesta(self):
        base = {"SubjectUserName": "mrossi", "SubjectDomainName": "ESEMPIO", "ObjectType": "File",
                "ObjectName": "D:\\Dati\\Progetti\\disegno.dwg"}

        def d(mask):
            return {"id": 4663, "dati": dict(base, AccessMask=mask)}

        self.assertIsNone(regole.classifica_windows(d("0x10000")))  # senza livello: niente indice
        self.assertEqual(regole.classifica_windows(d("0x10000"), livello_file="modifiche").categoria, "file_eliminato")
        self.assertEqual(regole.classifica_windows(d("0x2"), livello_file="modifiche").categoria, "file_modificato")
        self.assertIsNone(regole.classifica_windows(d("0x1"), livello_file="modifiche"))
        letto = regole.classifica_windows(d("0x1"), livello_file="tutto")
        self.assertEqual((letto.categoria, letto.oggetto), ("file_letto", "D:\\Dati\\Progetti\\disegno.dwg"))
        tmp = {"id": 4663, "dati": dict(base, ObjectName="D:\\Dati\\~$offerta.docx", AccessMask="0x2")}
        self.assertIsNone(regole.classifica_windows(tmp, livello_file="tutto"))

    def test_stampa_e_nome_documento_minimizzato(self):
        from .raccoglitore import minimizza

        d = {"id": 307, "prov": "Microsoft-Windows-PrintService",
             "dati": {"Param2": "Offerta riservata.pdf", "Param3": "mrossi", "Param4": "\\\\PC-UFF12",
                      "Param5": "MFC-Ufficio", "Param8": "12"}}
        fonte = FonteLog(nome="PRINT01", tipo="windows", stampe_nomi=False)
        ridotto = minimizza(d, fonte)
        self.assertEqual(ridotto["dati"]["Param2"], regole.DOCUMENTO_NASCOSTO)
        self.assertEqual(d["dati"]["Param2"], "Offerta riservata.pdf")  # l'originale non viene toccato
        idx = regole.classifica_windows(ridotto)
        self.assertEqual((idx.categoria, idx.account, idx.oggetto, idx.quantita, idx.ip_origine),
                         ("stampa", "mrossi", "MFC-Ufficio", 12, "PC-UFF12"))
        self.assertNotIn("Offerta", idx.descrizione)
        fonte.stampe_nomi = True
        self.assertIn("Offerta", regole.classifica_windows(minimizza(d, fonte)).descrizione)

    def test_usb(self):
        part = {"id": 1006, "prov": "Microsoft-Windows-Partition",
                "dati": {"BusType": "7", "Capacity": "32000000000", "Manufacturer": "Kingston", "Model": "DataTraveler",
                         "SerialNumber": "ABC123"}}
        idx = regole.classifica_windows(part)
        self.assertEqual(idx.categoria, "usb_collegato")
        self.assertIn("ABC123", idx.oggetto)
        self.assertIsNone(regole.classifica_windows({**part, "dati": dict(part["dati"], BusType="11")}))  # disco SATA
        self.assertIsNone(regole.classifica_windows({**part, "dati": dict(part["dati"], Capacity="0")}))  # scollegata
        mouse = {"id": 6416, "dati": {"ClassName": "Mouse", "DeviceId": "HID\\VID_1"}}
        self.assertIsNone(regole.classifica_windows(mouse))
        disco = {"id": 6416, "dati": {"ClassName": "DiskDrive", "DeviceId": "USBSTOR\\DISK&VEN_X", "DeviceDescription": "Disco USB"}}
        self.assertEqual(regole.classifica_windows(disco).categoria, "usb_collegato")

    def test_xpath_con_file_usb_e_canali_aggiuntivi(self):
        q = regole.xpath("Security", 1, tutto=False, file=True, usb=True)
        self.assertIn("EventID=4663", q)
        self.assertIn("EventID=6416", q)
        self.assertLessEqual(q.count(" or "), 20)
        self.assertIn("EventID=307", regole.xpath("Microsoft-Windows-PrintService/Operational", 1, tutto=False))
        f = FonteLog(canali="Security,System", audit_stampe=True, audit_usb=True)
        self.assertEqual(len(f.lista_canali()), 4)


class IndaginiTests(_ConArchivio):
    def setUp(self):
        super().setUp()
        from core.models import UserOnboarding

        self.admin = get_user_model().objects.create_user("admin.ind", password="pass-di-prova-123", is_staff=True,
                                                          is_superuser=True)
        UserOnboarding.objects.update_or_create(user=self.admin, defaults={"completed": True})
        self.client.force_login(self.admin)
        self.fonte = FonteLog.objects.create(nome="FS01", tipo="windows", ruolo="server", host="FS01")
        self.file = EventoRegistro.objects.create(quando=timezone.now(), categoria="file_eliminato", account="mrossi",
                                                  descrizione="Eliminato D:\\Dati\\disegno.dwg",
                                                  oggetto="D:\\Dati\\disegno.dwg", host="FS01", fonte_id=self.fonte.pk)
        EventoRegistro.objects.create(quando=timezone.now(), categoria="stampa", account="altro",
                                      descrizione="Stampate 3 pagine", quantita=3, host="PRINT01")

    def test_fonte_riservata_bloccata_senza_conferma(self):
        dati = {"azione": "fonte", "nome": "FS02", "tipo": "windows", "ruolo": "server", "host": "FS02",
                "canali": "Security", "eventi": "accessi", "silenzio_max_ore": 24, "attiva": "on", "audit_file": "modifiche"}
        r = self.client.post(reverse("security:registro_log_fonti"), dati)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FonteLog.objects.filter(nome="FS02").exists())
        imp = Impostazioni.corrente()
        imp.controlli_lavoratori_ok = True
        imp.save()
        r = self.client.post(reverse("security:registro_log_fonti"), dati)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(FonteLog.objects.get(nome="FS02").audit_file, "modifiche")

    def test_eventi_riservati_solo_dentro_un_indagine(self):
        from core.models import AuditLog

        from .models import Indagine

        r = self.client.get(reverse("security:registro_log_eventi") + "?giorni=30")
        self.assertNotContains(r, "disegno.dwg")
        r = self.client.get(reverse("security:registro_log_evento", args=[self.file.pk]))
        self.assertEqual(r.status_code, 403)
        r = self.client.post(reverse("security:registro_log_indagini"), {
            "motivo": "Sospetto furto dei disegni del cliente segnalato dal responsabile tecnico",
            "account": "ESEMPIO\\mrossi", "dal": (timezone.localdate() - timedelta(days=7)).isoformat(),
            "al": timezone.localdate().isoformat()})
        self.assertEqual(r.status_code, 302)
        ind = Indagine.objects.get()
        r = self.client.get(reverse("security:registro_log_indagine", args=[ind.pk]))
        self.assertContains(r, "disegno.dwg")
        self.assertNotContains(r, "Stampate 3 pagine")  # altra persona
        r = self.client.get(reverse("security:registro_log_evento", args=[self.file.pk]) + f"?indagine={ind.pk}")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse("security:registro_log_indagine", args=[ind.pk]) + "?vista=file&export=csv")
        self.assertIn("disegno.dwg", r.content.decode("utf-8"))
        azioni = set(AuditLog.objects.filter(modulo="registro_log").values_list("azione", flat=True))
        self.assertTrue({"registro_log_indagine_aperta", "registro_log_indagine_consultata",
                         "registro_log_indagine_export"} <= azioni)
        self.client.post(reverse("security:registro_log_indagine", args=[ind.pk]), {"esito": "Nessuna sottrazione"})
        r = self.client.get(reverse("security:registro_log_evento", args=[self.file.pk]) + f"?indagine={ind.pk}")
        self.assertEqual(r.status_code, 403)

    def test_alert_file_a_raffica_e_usb_su_server(self):
        from security.models import SecurityAlert, SecurityCenterSetting

        from . import ciclo

        for chiave, valore, tipo in (("registro.alert.attivo", True, "bool"), ("registro.alert.file_massivi", True, "bool"),
                                     ("registro.alert.file_soglia", 20, "int"), ("registro.alert.usb_server", True, "bool")):
            SecurityCenterSetting.objects.update_or_create(key=chiave, defaults={"value": valore, "value_type": tipo,
                                                                                 "category": "avvisi"})
        EventoRegistro.objects.bulk_create([EventoRegistro(quando=timezone.now(), categoria="file_eliminato", account="mrossi",
                                                           descrizione=f"Eliminato D:\\Dati\\f{i}.dwg") for i in range(25)])
        EventoRegistro.objects.create(quando=timezone.now(), categoria="usb_collegato", host="FS01",
                                      fonte_id=self.fonte.pk, descrizione="Collegata Kingston")
        esito = ciclo.invia_al_soc()
        self.assertEqual(esito["eventi_soc"], 2)
        titoli = list(SecurityAlert.objects.values_list("title", flat=True))
        self.assertTrue(any("file eliminati in 10 minuti" in t for t in titoli))
        self.assertTrue(any("USB" in t for t in titoli))
        self.assertFalse(any(".dwg" in t for t in titoli))  # nessun dettaglio riservato nel SOC


class RobustezzaTests(_ConArchivio):
    def test_scrittura_fallita_si_riprova_senza_perdere_ne_duplicare(self):
        from .raccoglitore import Raccoglitore

        fonte = FonteLog.objects.create(nome="DC01", tipo="windows", ruolo="dc", host="DC01")
        r = Raccoglitore()
        r.carica()
        vero = r.scrittore.scrivi
        chiamate = {"n": 0}

        def a_volte(*args, **kwargs):
            chiamate["n"] += 1
            if chiamate["n"] == 2:
                raise OSError("disco pieno")
            return vero(*args, **kwargs)

        ora = timezone.now()
        for rec in (1, 2, 3):
            r.coda.put(("windows", fonte.pk, {"id": 4634, "rec": rec, "dati": {}}, ora))
        r._fermo.set()
        with mock.patch.object(r.scrittore, "scrivi", side_effect=a_volte), mock.patch("registro_log.raccoglitore.time.sleep"):
            r.ciclo_scrittore()
        self.assertEqual(r.scrittore.n, 3)
        g = timezone.localdate(ora)
        righe = [json.loads(x) for x in archivio.percorso(g).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x["d"]["rec"] for x in righe], [1, 2, 3])
        self.assertEqual(archivio.ricalcola(archivio.percorso(g).read_text(encoding="utf-8").splitlines(), g)["errore"], "")

    def test_pausa_dopo_errori_e_lettura_in_parallelo(self):
        from .raccoglitore import Raccoglitore, aggiorna_stato_fonte, pausa_dopo_errori

        self.assertEqual([pausa_dopo_errori(n).seconds // 60 for n in (1, 2, 3, 6, 9)], [1, 2, 4, 30, 30])
        rotta = FonteLog.objects.create(nome="SPENTO", tipo="windows", host="SPENTO")
        buona = FonteLog.objects.create(nome="DC01", tipo="windows", host="DC01")
        aggiorna_stato_fonte(rotta, ["Security: server non raggiungibile"])
        aggiorna_stato_fonte(rotta, ["Security: server non raggiungibile"])
        rotta.refresh_from_db()
        self.assertEqual(rotta.errori_consecutivi, 2)
        self.assertGreater(rotta.riprova_dopo, timezone.now())
        r = Raccoglitore()
        r.carica()
        lette = []
        with mock.patch.object(r, "leggi_fonte", side_effect=lambda f: lette.append(f.nome)):
            r.leggi_windows()
            r._lettori.shutdown(wait=True)
        self.assertEqual(lette, ["DC01"])  # quello in pausa non si interroga
        aggiorna_stato_fonte(rotta, [])
        rotta.refresh_from_db()
        self.assertEqual((rotta.errori_consecutivi, rotta.riprova_dopo, rotta.stato), (0, None, "ok"))
        self.assertTrue(buona.pk)

    def test_sigillo_anche_nell_audit_e_conservazione_a_blocchi(self):
        from core.models import AuditLog

        g = date(2026, 1, 3)
        s = archivio.Scrittore()
        s.scrivi(1, {"id": 1}, timezone.make_aware(datetime.combine(g, time(9, 0))))
        s.chiudi()
        sig = archivio.sigilla(g)
        ancora = AuditLog.objects.get(azione="registro_log_sigillo")
        self.assertEqual(ancora.dettaglio["hash_sigillo"], sig.hash_sigillo)
        EventoRegistro.objects.bulk_create([EventoRegistro(quando=timezone.make_aware(datetime(2025, 1, 1, 9)),
                                                           categoria="accesso") for _ in range(7)])
        esito = archivio.applica_conservazione(oggi=date(2026, 3, 1))
        self.assertEqual(esito["eventi_eliminati"], 7)

    def test_spazio_libero(self):
        self.assertGreater(archivio.spazio_libero_mb(self.tmp), 0)

    def test_scarto_orologio_syslog(self):
        from .raccoglitore import Raccoglitore

        esx = FonteLog.objects.create(nome="ESX01", tipo="syslog", indirizzi_ip="10.0.0.20")
        r = Raccoglitore()
        r.carica()
        ricevuto = timezone.now()
        dieci_minuti_fa = (ricevuto - timedelta(minutes=10)).astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        r.coda.put(("syslog", esx.pk, f"<38>{dieci_minuti_fa} esx01 hostd[1]: messaggio qualsiasi".encode(), "10.0.0.20", ricevuto))
        r._fermo.set()
        r.ciclo_scrittore()
        esx.refresh_from_db()
        self.assertAlmostEqual(esx.scarto_orologio_s, 600, delta=2)


class UxTests(PagineTests):
    def test_export_csv_eventi_e_precompilazione_nomina(self):
        from core.models import AuditLog

        r = self.client.get(reverse("security:registro_log_eventi") + "?giorni=7&export=csv")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("mrossi", r.content.decode("utf-8"))
        self.assertTrue(AuditLog.objects.filter(azione="registro_log_eventi_export").exists())
        AccountAD.objects.create(sam="adm.nuovo", nome="Admin Nuovo", gruppi_privilegiati=["Domain Admins"])
        r = self.client.get(reverse("security:registro_log_account"))
        self.assertContains(r, "Aggiungi la nomina")
        r = self.client.get(reverse("security:registro_log_ads") + "?account=adm.nuovo&nome=Admin+Nuovo")
        self.assertContains(r, 'value="adm.nuovo"')
        self.assertContains(r, "precompilata")

    def test_grafico_e_modulo_fonte_chiuso(self):
        r = self.client.get(reverse("security:registro_log"))
        self.assertContains(r, "rl-grafico")
        self.assertEqual(r.content.decode().count('class="rl-barra '), 14)
        r = self.client.get(reverse("security:registro_log_fonti"))
        self.assertContains(r, 'id="nuova" style="margin-top:12px">')  # chiuso: c'è già una fonte
        r = self.client.get(reverse("security:registro_log_fonti") + "?nuova=1")
        self.assertContains(r, 'id="nuova" style="margin-top:12px" open>')
