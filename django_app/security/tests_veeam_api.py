"""Backup letti dall'API REST di Veeam (security.services.veeam_api). Veeam sempre simulato, dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from security.models import BackupJobRecord, SecurityAlert, SecurityEventRecord, SecuritySource, SourceType, Status
from security.parsers.base import ParsedRecord
from security.parsers.veeam_backup_email_parser import parse_veeam_email
from security.services import backup_center
from security.services import veeam_api as svc
from security.services.configuration import set_setting
from security.services.parser_engine import _persist_record
from security.services.rule_engine import evaluate_security_rules

GB = 1024 ** 3
VEEAM_ENV = {"VEEAM_API_URL": "https://veeam-sintetico:9419", "VEEAM_API_USERNAME": "lettura", "VEEAM_API_PASSWORD": "x"}


def _session(sid="s-001", name="VM notturno", result="Success", state="Stopped", kind="BackupJob",
             start="2026-10-22T22:00:03.512+02:00", end="2026-10-22T22:41:10+02:00", canceled=False):
    return {
        "id": sid, "name": name, "jobId": "j-001", "sessionType": kind, "state": state,
        "creationTime": start, "endTime": end if state == "Stopped" else None,
        "result": {"result": result, "message": "", "isCanceled": canceled},
    }


def _task(name, result="Success", transferred=8.5 * GB):
    return {
        "name": name, "result": {"result": result, "message": "Snapshot non riuscito" if result == "Failed" else ""},
        "creationTime": "2026-10-22T22:00:10+02:00", "endTime": "2026-10-22T22:20:10+02:00",
        "progress": {"processedSize": 40 * GB, "readSize": 10 * GB, "transferredSize": transferred, "duration": "0:20:00"},
    }


class FakeClient:
    def __init__(self, sessions=(), tasks=None, repositories=()):
        self.sessions, self.tasks, self.repositories = list(sessions), tasks or {}, list(repositories)
        self.task_calls = []

    def get_all(self, path, params=None):
        if path == "/api/v1/sessions":
            return self.sessions
        if path.startswith("/api/v1/sessions/"):
            sid = path.split("/")[4]
            self.task_calls.append(sid)
            return self.tasks.get(sid, [])
        if path == "/api/v1/backupInfrastructure/repositories/states":
            return self.repositories
        raise AssertionError(path)

    def close(self):
        pass


class PayloadTests(TestCase):
    def test_sessione_diventa_payload_come_le_mail(self):
        payload = svc.session_payload(_session(), [_task("SRV-DEMO-01"), _task("SRV-DEMO-02", "Failed", 0)])
        self.assertEqual(payload["vendor"], "veeam")
        self.assertEqual(payload["source"], "veeam_api")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["duration_seconds"], 41 * 60 + 7)
        self.assertEqual(payload["objects_ok"], 1)
        self.assertEqual(payload["objects_error"], 1)
        self.assertAlmostEqual(payload["transferred_size_gb"], 8.5)
        # Le righe per macchina si leggono con lo stesso codice del Centro backup.
        self.assertAlmostEqual(backup_center._size_gb(payload["objects"][0]["transferred"]), 8.5)
        self.assertEqual(backup_center._duration_seconds(payload["objects"][0]["duration"]), 1200)

    def test_esiti(self):
        self.assertEqual(svc.session_payload(_session(result="Warning"), [])["status"], "warning")
        self.assertEqual(svc.session_payload(_session(result="Failed"), [])["status"], "failed")
        self.assertEqual(svc.session_payload(_session(result="None", canceled=True), [])["status"], "warning")

    def test_solo_sessioni_di_backup_concluse(self):
        self.assertTrue(svc.is_backup_session(_session()))
        self.assertTrue(svc.is_backup_session(_session(kind="BackupCopyJob")))
        self.assertFalse(svc.is_backup_session(_session(kind="RestoreVm")))
        self.assertFalse(svc.is_backup_session(_session(kind="ConfigurationBackup")))
        self.assertFalse(svc.is_backup_session(_session(kind="RepositoryMaintenance")))
        self.assertFalse(svc.is_finished(_session(state="Working")))


class SessioniTests(TestCase):
    def test_salva_record_ed_evento_senza_duplicare(self):
        client = FakeClient([_session(), _session("s-002", state="Working"), _session("s-003", kind="RestoreVm")],
                            {"s-001": [_task("SRV-DEMO-01")]})
        esito = svc.record_sessions(client, client.sessions)
        self.assertEqual(esito["salvate"], 1)
        record = BackupJobRecord.objects.get()
        self.assertEqual(record.job_name, "VM notturno")
        self.assertEqual(record.status, "completed")
        self.assertIsNotNone(record.started_at)
        self.assertEqual(SecurityEventRecord.objects.filter(event_type="backup_job").count(), 1)
        self.assertEqual(client.task_calls, ["s-001"])

        esito = svc.record_sessions(client, client.sessions)
        self.assertEqual((esito["salvate"], esito["gia_presenti"]), (0, 1))
        self.assertEqual(BackupJobRecord.objects.count(), 1)
        self.assertEqual(client.task_calls, ["s-001"])  # niente seconda lettura delle macchine

    def test_backup_fallito_apre_alert(self):
        client = FakeClient([_session(result="Failed")], {"s-001": [_task("SRV-DEMO-01", "Failed", 0)]})
        svc.record_sessions(client, client.sessions)
        evaluate_security_rules()
        self.assertTrue(SecurityAlert.objects.filter(title__icontains="VM notturno").exists())


class StessaEsecuzioneMailEApiTests(TestCase):
    def setUp(self):
        self.mail_source = SecuritySource.objects.create(name="Casella sintetica", vendor="veeam", source_type=SourceType.EMAIL)
        body = ("Backup job: VM notturno\nSuccess\n22 ottobre 2026\nStart time 22:00:05\nEnd time 22:41:10\n"
                "Duration 0:41:05\nTransferred 8,5 GB\n")
        self.mail_payload = parse_veeam_email("[Success] VM notturno (1 objects)", body)

    def test_mail_gia_arrivata_api_non_ripete(self):
        _persist_record(self.mail_source, None, ParsedRecord(record_type="backup_job", payload=self.mail_payload))
        self.assertEqual(BackupJobRecord.objects.count(), 1)
        client = FakeClient([_session()], {"s-001": [_task("SRV-DEMO-01")]})
        esito = svc.record_sessions(client, client.sessions)
        self.assertEqual((esito["salvate"], esito["gia_da_mail"]), (0, 1))
        self.assertEqual(BackupJobRecord.objects.count(), 1)

    def test_api_gia_letta_mail_non_ripete(self):
        client = FakeClient([_session()], {"s-001": [_task("SRV-DEMO-01")]})
        svc.record_sessions(client, client.sessions)
        _persist_record(self.mail_source, None, ParsedRecord(record_type="backup_job", payload=self.mail_payload))
        self.assertEqual(BackupJobRecord.objects.count(), 1)

    def test_altro_giorno_dalla_mail_si_salva(self):
        _persist_record(self.mail_source, None, ParsedRecord(record_type="backup_job", payload=self.mail_payload))
        client = FakeClient([_session(start="2026-10-23T22:00:03+02:00", end="2026-10-23T22:40:00+02:00")])
        self.assertEqual(svc.record_sessions(client, client.sessions)["salvate"], 1)


class RepositoryTests(TestCase):
    def _repo(self, free):
        return {"id": "r-001", "name": "Repository NAS", "hostName": "nas-sintetico", "path": "/volume1/veeam",
                "capacityGB": 1000, "freeGB": free}

    def test_sotto_soglia_apre_alert_e_sopra_lo_chiude(self):
        set_setting("veeam.repository.soglia_pct", 15)
        self.assertEqual(svc.record_repositories(svc.repository_rows([self._repo(400)]), 15), 0)
        self.assertEqual(svc.record_repositories(svc.repository_rows([self._repo(90)]), 15), 1)
        evaluate_security_rules()
        alert = SecurityAlert.objects.get(title__icontains="Repository NAS")
        self.assertNotIn(alert.status, (Status.RESOLVED, Status.CLOSED))
        self.assertEqual(svc.record_repositories(svc.repository_rows([self._repo(80)]), 15), 0)  # ancora sotto: niente evento
        self.assertEqual(svc.record_repositories(svc.repository_rows([self._repo(300)]), 15), 1)
        evaluate_security_rules()
        alert.refresh_from_db()
        self.assertEqual(alert.status, Status.RESOLVED)

    def test_righe_ordinate_dal_piu_pieno(self):
        rows = svc.repository_rows([self._repo(500), {**self._repo(50), "id": "r-002", "name": "Pieno"}])
        self.assertEqual(rows[0]["name"], "Pieno")
        self.assertEqual(rows[0]["free_pct"], 5.0)


class GiroTests(TestCase):
    def test_spento_non_contatta_veeam(self):
        with patch.object(svc, "VeeamClient") as client:
            self.assertEqual(svc.run(), {"attivo": False})
        client.assert_not_called()

    @override_settings(VEEAM_API_URL="", VEEAM_API_USERNAME="", VEEAM_API_PASSWORD="")
    def test_senza_credenziali_registra_errore(self):
        set_setting("veeam.api.attivo", True)
        esito = svc.run()
        self.assertFalse(esito["ok"])
        self.assertIn("Credenziali API Veeam", esito["errore"])
        self.assertEqual(svc.last_run()["errore"], esito["errore"])

    def test_giro_completo(self):
        set_setting("veeam.api.attivo", True)
        fake = FakeClient([_session()], {"s-001": [_task("SRV-DEMO-01")]},
                          [{"id": "r-001", "name": "Repository NAS", "capacityGB": 1000, "freeGB": 50}])
        with patch.object(svc, "VeeamClient", return_value=fake):
            esito = svc.run()
        self.assertTrue(esito["ok"])
        self.assertEqual(esito["salvate"], 1)
        self.assertEqual(esito["eventi_repository"], 1)
        self.assertTrue(SecurityAlert.objects.filter(title__icontains="Repository NAS").exists())
        self.assertEqual(svc.panel()["repository"][0]["free_pct"], 5.0)
        # Dal secondo giro si riparte dall'ultimo giro riuscito meno la sovrapposizione.
        self.assertLess(svc._since(timezone.now()), timezone.now() - timedelta(hours=47))


@override_settings(**VEEAM_ENV)
class ClientTests(TestCase):
    def _session_mock(self, token_status=200, pages=None):
        http = MagicMock()
        http.headers = {}
        http.post.return_value = MagicMock(status_code=token_status, json=lambda: {"access_token": "tok"})
        responses = [MagicMock(status_code=200, json=(lambda data=data: data)) for data in (pages or [])]
        http.get.side_effect = responses
        return http

    def test_accesso_con_versione_api_e_paginazione(self):
        pages = [{"data": [{"id": i} for i in range(svc.PAGE_SIZE)], "pagination": {"total": svc.PAGE_SIZE + 1}},
                 {"data": [{"id": "ultimo"}], "pagination": {"total": svc.PAGE_SIZE + 1}}]
        http = self._session_mock(pages=pages)
        with patch("requests.Session", return_value=http):
            client = svc.VeeamClient()
            rows = client.get_all("/api/v1/sessions")
        self.assertEqual(len(rows), svc.PAGE_SIZE + 1)
        self.assertEqual(http.headers["x-api-version"], svc.DEFAULT_API_VERSION)
        self.assertEqual(http.headers["Authorization"], "Bearer tok")
        self.assertTrue(http.post.call_args[0][0].endswith("/api/oauth2/token"))
        self.assertEqual(http.get.call_args_list[1].kwargs["params"]["skip"], svc.PAGE_SIZE)

    def test_credenziali_rifiutate(self):
        with patch("requests.Session", return_value=self._session_mock(token_status=401)):
            with self.assertRaisesMessage(svc.VeeamError, "utente e password"):
                svc.VeeamClient()

    @override_settings(VEEAM_API_URL="http://veeam-sintetico:9419")
    def test_solo_https(self):
        with self.assertRaisesMessage(svc.VeeamError, "https://"):
            svc.VeeamClient()


class PaginaBackupTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create(username="soc_veeam_user", is_staff=True, is_superuser=True)
        self.client.force_login(user)

    def test_riquadro_nascosto_se_spento(self):
        page = self.client.get(reverse("security:backup"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Lettura diretta da Veeam")

    @override_settings(VEEAM_API_URL="", VEEAM_API_USERNAME="", VEEAM_API_PASSWORD="")
    def test_riquadro_acceso_senza_credenziali(self):
        set_setting("veeam.api.attivo", True)
        page = self.client.get(reverse("security:backup"))
        self.assertContains(page, "Lettura diretta da Veeam")
        self.assertContains(page, "Mancano le credenziali dell")


class CredenzialiDalPortaleTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create(username="soc_veeam_cred", is_staff=True, is_superuser=True)
        self.client.force_login(self.admin)

    def _salva(self, **extra):
        dati = {"url": "https://veeam-sintetico:9419/", "username": "DOMINIO\\lettura", "password": "segreta-1", "version": "", "ca_pem": ""}
        dati.update(extra)
        return svc.salva_credenziali(dati, self.admin)

    def test_salvate_cifrate_e_password_tenuta(self):
        from security.models import SecurityCenterSetting

        self.assertEqual(self._salva(), [])
        grezzo = SecurityCenterSetting.objects.get(key=svc.SETTING).value
        self.assertNotIn("segreta-1", grezzo)
        self.assertTrue(grezzo.startswith("fernet:"))
        self.assertEqual(self._salva(password=""), [])  # vuota = resta quella salvata
        self.assertEqual(svc.credenziali()["password"], "segreta-1")
        self.assertEqual(svc._config()["url"], "https://veeam-sintetico:9419")
        self.assertEqual(svc.riepilogo()["fonte"], "portale")
        self.assertNotIn("segreta", str(svc.riepilogo()))

    def test_errori(self):
        self.assertTrue(self._salva(url="http://veeam:9419"))
        self.assertTrue(self._salva(ca_pem="non un certificato"))

    @override_settings(**VEEAM_ENV)
    def test_il_portale_vince_sul_env(self):
        self.assertEqual(svc.riepilogo()["fonte"], "env")
        self._salva()
        self.assertEqual(svc._config()["url"], "https://veeam-sintetico:9419")
        svc.cancella_credenziali(self.admin)
        self.assertEqual(svc._config()["url"], VEEAM_ENV["VEEAM_API_URL"])

    def test_certificato_su_file(self):
        pem = "-----BEGIN CERTIFICATE-----\nMIIBsintetico\n-----END CERTIFICATE-----\n"
        self._salva(ca_pem=pem)
        verify = svc._config()["verify"]
        self.assertTrue(str(verify).endswith(".pem"))
        with open(verify, encoding="ascii") as fh:
            self.assertEqual(fh.read(), pem)
        svc.salva_credenziali({"url": "https://veeam-sintetico:9419", "username": "u", "password": "", "version": "", "ca_pem": ""},
                              self.admin, togli_ca=True)
        self.assertIs(svc._config()["verify"], True)

    def test_pagina_e_permessi(self):
        url = reverse("security:veeam_credenziali")
        self.client.post(url, {"azione": "salva", "url": "https://veeam-sintetico:9419", "username": "u", "password": "p"})
        self.assertTrue(svc.configured())
        page = self.client.get(reverse("security:soc_settings"))
        self.assertContains(page, "Credenziali API Veeam")
        self.assertNotContains(page, 'value="p"')
        user = get_user_model().objects.create(username="soc_veeam_nessuno")
        self.client.force_login(user)
        self.client.post(url, {"azione": "cancella"})
        self.assertTrue(svc.configured())
