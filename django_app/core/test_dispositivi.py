"""Accessi da un dispositivo nuovo (core.dispositivi) e push nel primo accesso."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core import dispositivi as svc
from core.models import DispositivoAccesso, NotificaCanali

UA_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"


def _richiesta(cookie=None, ua=UA_WIN, ip="10.0.0.5"):
    req = RequestFactory().post("/login/", HTTP_USER_AGENT=ua, REMOTE_ADDR=ip)
    req.session = SessionStore()
    req.session.create()
    if cookie:
        req.COOKIES[svc.COOKIE] = cookie
    return req


class EtichettaTests(TestCase):
    def test_browser_e_sistema(self):
        self.assertEqual(svc.etichetta(UA_WIN), "Chrome su Windows")
        self.assertEqual(svc.etichetta(UA_IPHONE), "Safari su iPhone")
        self.assertEqual(svc.etichetta("Mozilla/5.0 (Windows NT 10.0) Edg/130.0"), "Edge su Windows")
        self.assertEqual(svc.etichetta(""), "Browser su sistema sconosciuto")


class RegistrazioneTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="m.sintetico", email="m.sintetico@example.com", password="x")

    def test_primo_dispositivo_senza_avviso_poi_nuovo_con_avviso(self):
        with patch("core.dispositivi.avvisa") as avvisa:
            req = _richiesta()
            esito = svc.registra_accesso(req, self.user)
            self.assertEqual((esito["nuovo"], esito["avvisato"]), (True, False))
            cookie = req._nh_dev_cookie
            # Stesso browser (stesso cookie): non è nuovo.
            esito = svc.registra_accesso(_richiesta(cookie=cookie), self.user)
            self.assertFalse(esito["nuovo"])
            # Altro browser: nuovo e avviso.
            esito = svc.registra_accesso(_richiesta(ua=UA_IPHONE, ip="203.0.113.9"), self.user)
            self.assertEqual((esito["nuovo"], esito["avvisato"]), (True, True))
        self.assertEqual(avvisa.call_count, 1)
        self.assertEqual(DispositivoAccesso.objects.filter(user=self.user).count(), 2)

    def test_cookie_di_un_altra_persona_vale_come_nuovo(self):
        altro = get_user_model().objects.create_user(username="altro", password="x")
        req = _richiesta()
        svc.registra_accesso(req, altro)
        with patch("core.dispositivi.avvisa"):
            svc.registra_accesso(_richiesta(), self.user)  # primo dispositivo
            esito = svc.registra_accesso(_richiesta(cookie=req._nh_dev_cookie), self.user)
        self.assertTrue(esito["nuovo"])

    def test_cookie_manomesso_ignorato(self):
        with patch("core.dispositivi.avvisa"):
            svc.registra_accesso(_richiesta(), self.user)
            self.assertTrue(svc.registra_accesso(_richiesta(cookie="falso:valore"), self.user)["nuovo"])

    def test_nel_database_solo_l_impronta(self):
        req = _richiesta()
        svc.registra_accesso(req, self.user)
        from django.core import signing

        token = signing.loads(req._nh_dev_cookie, salt=svc.COOKIE_SALT)
        disp = DispositivoAccesso.objects.get()
        self.assertNotEqual(disp.token_hash, token)
        self.assertEqual(len(disp.token_hash), 64)

    def test_avviso_mail_evento_soc_e_campanella(self):
        from security.models import SecurityEventRecord

        svc.registra_accesso(_richiesta(), self.user)
        with patch("core.dispositivi._legacy_id", return_value=77), patch("core.notifiche.invia_notifica") as campanella, \
             patch("dashboard.scadenze_digest._email_utente", return_value="m.sintetico@example.com"):
            svc.registra_accesso(_richiesta(ua=UA_IPHONE, ip="203.0.113.9"), self.user)
        campanella.assert_called_once()
        self.assertEqual(campanella.call_args.args[1], "accesso_nuovo_dispositivo")
        self.assertIn("Safari su iPhone", campanella.call_args.args[2])
        self.assertEqual(len(mail.outbox), 1)
        ev = SecurityEventRecord.objects.get(event_type=svc.EVENTO_NUOVO)
        self.assertEqual(ev.payload["ip"], "203.0.113.9")

    def test_mail_spenta_dalla_persona(self):
        NotificaCanali.objects.create(user=self.user, sicurezza_mail=False)
        svc.registra_accesso(_richiesta(), self.user)
        with patch("core.dispositivi._legacy_id", return_value=None), \
             patch("dashboard.scadenze_digest._email_utente", return_value="m.sintetico@example.com"):
            svc.registra_accesso(_richiesta(ua=UA_IPHONE), self.user)
        self.assertEqual(len(mail.outbox), 0)

    def test_middleware_scrive_il_cookie(self):
        from django.http import HttpResponse

        mw = svc.DispositivoCookieMiddleware(lambda r: HttpResponse("ok"))
        req = _richiesta()
        req._nh_dev_cookie = "valore"
        resp = mw(req)
        self.assertTrue(resp.cookies[svc.COOKIE]["httponly"])
        self.assertEqual(resp.cookies[svc.COOKIE]["samesite"], "Lax")


@override_settings(LEGACY_AUTH_ENABLED=False)
class PagineTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser(username="adm", email="a@a.it", password="x")
        self.onb = UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)

    def test_non_ero_io_chiude_la_sessione_e_apre_un_alert(self):
        from django.contrib.sessions.models import Session
        from django.utils import timezone

        from security.models import SecurityAlert

        altra = SessionStore()
        altra.create()
        ora = timezone.now()
        disp = DispositivoAccesso.objects.create(user=self.user, token_hash="x" * 64, etichetta="Firefox su Linux",
                                                 ip_ultimo="198.51.100.4", primo_accesso=ora, ultimo_accesso=ora,
                                                 session_key=altra.session_key)
        resp = self.client.get(reverse("notifiche_impostazioni"))
        self.assertContains(resp, "I miei accessi")
        self.assertContains(resp, "Firefox su Linux")
        self.client.post(reverse("notifiche_impostazioni"), {"azione": "non_ero_io", "dispositivo": disp.pk})
        disp.refresh_from_db()
        self.assertTrue(disp.non_riconosciuto)
        self.assertFalse(Session.objects.filter(session_key=altra.session_key).exists())
        alert = SecurityAlert.objects.get()
        self.assertIn("non riconosciuto", alert.title)

    def test_primo_accesso_salva_le_push_per_categoria(self):
        self.onb.completed = False
        self.onb.save()
        with patch("core.views._push_configurato", return_value=True), \
             patch("core.views._push_chiave_pubblica", return_value="chiave-sintetica"):
            resp = self.client.get(reverse("onboarding_wizard"))
            self.assertContains(resp, "Notifiche anche su questo telefono o PC")
            self.assertContains(resp, "Sicurezza dell")
            self.client.post(reverse("onboarding_wizard"), {"notifiche_sicurezza": "1", "push_sicurezza": "1"})
        self.assertIn("sicurezza", NotificaCanali.objects.get(user=self.user).push_categorie)
