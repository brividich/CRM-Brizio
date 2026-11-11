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

    def test_giro_troncato_riprende_da_dove_si_e_fermato(self):
        set_setting("veeam.api.attivo", True)
        sessioni = [_session(sid=f"s-{i:03d}", start=f"2026-10-{1 + i // 10:02d}T{i % 10:02d}:00:00+02:00",
                             end=f"2026-10-{1 + i // 10:02d}T{i % 10:02d}:30:00+02:00") for i in range(5)]
        fake = FakeClient(sessioni, {}, [])
        with patch.object(svc, "MAX_NEW_SESSIONS", 2), patch.object(svc, "VeeamClient", return_value=fake):
            esito = svc.run()
        self.assertEqual(esito["salvate"], 2)
        # Il prossimo giro riparte dalla terza sessione, non da adesso.
        self.assertEqual(svc._since(timezone.now()), svc._dt(sessioni[2]["creationTime"]))

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

    def test_404_spiega_l_indirizzo(self):
        with patch("requests.Session", return_value=self._session_mock(token_status=404)):
            with self.assertRaisesMessage(svc.VeeamError, "non c'è l'API REST di Veeam Backup & Replication"):
                svc.VeeamClient()

    def test_404_con_percorso_o_porta_sbagliata(self):
        cfg = {**svc._config(), "url": "https://veeam-sintetico:9398/api"}
        with patch("requests.Session", return_value=self._session_mock(token_status=404)):
            with self.assertRaisesMessage(svc.VeeamError, "9398"):
                svc.VeeamClient(cfg)

    def test_niente_proxy_dell_ambiente(self):
        http = self._session_mock()
        with patch("requests.Session", return_value=http):
            svc.VeeamClient()
        self.assertFalse(http.trust_env)

    def test_404_da_un_altro_servizio(self):
        http = self._session_mock(token_status=404)
        http.post.return_value.headers = {"Content-Type": "text/html", "Server": "Microsoft-IIS/10.0"}
        with patch("requests.Session", return_value=http):
            with self.assertRaisesMessage(svc.VeeamError, "Microsoft-IIS/10.0"):
                svc.VeeamClient()

    def test_porta_non_numerica_e_versione(self):
        self.assertTrue(svc._problemi_indirizzo("https://veeam-sintetico:abc"))
        base = {"url": "https://veeam-sintetico:9419", "username": "u", "password": "p", "ca_pem": ""}
        self.assertEqual(svc.valida({**base, "version": "1.2-rev1"}), [])
        self.assertEqual(svc.valida({**base, "version": ""}), [])
        self.assertTrue(svc.valida({**base, "version": "12.3"}))

    def test_indirizzo_validato(self):
        self.assertEqual(svc._problemi_indirizzo("https://veeam-sintetico:9419"), [])
        self.assertTrue(svc._problemi_indirizzo("https://veeam-sintetico:9419/api/v1"))
        self.assertTrue(svc._problemi_indirizzo("https://veeam-sintetico"))

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


def _certificato_autofirmato(nome="veeam-sintetico", cartella=None):
    """Certificato autofirmato come quello di serie di Veeam: senza Authority Key Identifier (lo rifiuta il controllo
    rigoroso di Python 3.13). Restituisce (pem, percorso_cert, percorso_chiave)."""
    import ipaddress
    import os
    import tempfile

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    chiave = ec.generate_private_key(ec.SECP256R1())
    soggetto = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nome)])
    adesso = timezone.now()
    cert = (x509.CertificateBuilder().subject_name(soggetto).issuer_name(soggetto).public_key(chiave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(adesso - timedelta(days=1))
            .not_valid_after(adesso + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(chiave, hashes.SHA256()))
    cartella = cartella or tempfile.mkdtemp(prefix="pn_veeam_test_")
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    percorso_cert = os.path.join(cartella, "cert.pem")
    percorso_chiave = os.path.join(cartella, "key.pem")
    with open(percorso_cert, "w", encoding="ascii") as f:
        f.write(pem)
    with open(percorso_chiave, "wb") as f:
        f.write(chiave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))
    return pem, percorso_cert, percorso_chiave


class _VeeamFinto:
    """Un server HTTPS locale con certificato autofirmato che risponde come il login di Veeam."""

    def __init__(self):
        import json
        import ssl
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Gestore(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                corpo = json.dumps({"access_token": "tok-sintetico"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def log_message(self, *args):
                pass

        self.pem, cert, chiave = _certificato_autofirmato()
        self.server = HTTPServer(("127.0.0.1", 0), Gestore)
        contesto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        contesto.load_cert_chain(cert, chiave)
        self.server.socket = contesto.wrap_socket(self.server.socket, server_side=True)
        self.url = f"https://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


class CertificatoServerTests(TestCase):
    """Certificato autofirmato di Veeam: impronta salvata o CA incollata, contro un server TLS locale vero."""

    def setUp(self):
        self.admin = get_user_model().objects.create(username="soc_veeam_cert", is_staff=True, is_superuser=True)

    def _cfg(self, url, **extra):
        return {"url": url, "username": "lettura", "password": "x", "version": svc.DEFAULT_API_VERSION,
                "verify": True, "impronta": "", "ca_incollato": False, **extra}

    def test_senza_niente_il_certificato_autofirmato_e_rifiutato_con_spiegazione(self):
        with _VeeamFinto() as veeam:
            with self.assertRaisesMessage(svc.VeeamError, "Fidati del certificato del server"):
                svc.VeeamClient(self._cfg(veeam.url))

    def test_ca_incollata_autofirmata_senza_controllo_rigoroso(self):
        with _VeeamFinto() as veeam:
            client = svc.VeeamClient(self._cfg(veeam.url, verify=svc._ca_file(veeam.pem), ca_incollato=True))
            self.assertEqual(client.http.headers["Authorization"], "Bearer tok-sintetico")

    def test_impronta_giusta_entra_e_sbagliata_no(self):
        with _VeeamFinto() as veeam:
            info = svc.leggi_certificato(veeam.url)
            self.assertTrue(info["autofirmato"])
            self.assertEqual(info["intestato_a"], "veeam-sintetico")
            self.assertIn("127.0.0.1", info["nomi"])
            client = svc.VeeamClient(self._cfg(veeam.url, impronta=info["sha256"]))
            self.assertEqual(client.http.headers["Authorization"], "Bearer tok-sintetico")
            with self.assertRaisesMessage(svc.VeeamError, "è cambiato"):
                svc.VeeamClient(self._cfg(veeam.url, impronta="0" * 64))

    def test_fidati_salva_l_impronta_e_cambiare_server_la_toglie(self):
        with _VeeamFinto() as veeam:
            self.assertEqual(svc.salva_credenziali({"url": veeam.url, "username": "u", "password": "p"}, self.admin), [])
            info = svc.fidati_del_certificato(self.admin)
            self.assertEqual(svc.credenziali()["impronta"], info["sha256"])
            self.assertTrue(svc.riepilogo()["impronta"])
            self.assertEqual(svc._config()["impronta"], info["sha256"])
            # Stesso server, password cambiata: l'impronta resta. Il form non può impostarla.
            svc.salva_credenziali({"url": veeam.url, "username": "u", "password": "", "impronta": "f" * 64}, self.admin)
            self.assertEqual(svc.credenziali()["impronta"], info["sha256"])
            svc.salva_credenziali({"url": "https://altro-veeam:9419", "username": "u", "password": ""}, self.admin)
            self.assertEqual(svc.credenziali()["impronta"], "")

    def test_pulsante_fidati(self):
        self.client.force_login(self.admin)
        info = {"intestato_a": "veeam-sintetico", "emesso_da": "veeam-sintetico", "scadenza": timezone.now(),
                "sha1": "AB" * 20, "scaduto": False}
        with patch.object(svc, "fidati_del_certificato", return_value=info) as fidati:
            resp = self.client.post(reverse("security:veeam_credenziali"), {"azione": "fidati"}, follow=True)
        fidati.assert_called_once()
        self.assertContains(resp, "Identificazione personale (SHA-1)")

    def test_pulsante_fidati_nel_riquadro_veeam(self):
        svc.salva_credenziali({"url": "https://veeam-sintetico:9419", "username": "u", "password": "p"}, self.admin)
        self.client.force_login(self.admin)
        html = self.client.get(reverse("security:soc_settings")).content.decode()
        inizio = html.index('id="veeam-api"')
        fine = html.index("</section>", inizio)
        self.assertEqual(html.count('value="fidati"'), 1)
        self.assertIn('value="fidati"', html[inizio:fine])

    def test_motivi_del_certificato(self):
        cfg = self._cfg("https://veeam-sintetico:9419")
        self.assertIn("non è intestato a «veeam-sintetico»",
                      svc._motivo_certificato(Exception("hostname mismatch, certificate is not valid for 'x'"), cfg))
        self.assertIn("scaduto", svc._motivo_certificato(Exception("certificate has expired"), cfg))
        self.assertIn("Dettaglio: self-signed certificate.", svc._motivo_certificato(
            Exception("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate (_ssl.c:1032)"), cfg))
        self.assertIn("non è firmato dal certificato incollato",
                      svc._motivo_certificato(Exception("unable to get local issuer certificate"), {**cfg, "ca_incollato": True}))
