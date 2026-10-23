"""Canale unico degli eventi di sicurezza del portale verso il SOC (core.eventi_sicurezza)."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core import eventi_sicurezza as ev
from security.models import SecurityAlert, SecurityEventRecord
from security.services import soc_settings
from security.services.configuration import set_setting


class SegnalaTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("u.sintetico", "u.sintetico@example.local", "x")
        self.request = RequestFactory().get("/", REMOTE_ADDR="10.1.2.3")

    def test_evento_con_alert_valutato_subito(self):
        evento = ev.segnala("postazione_pin_bloccato", utente=self.user, request=self.request, chiave=(7,),
                            titolo="PIN bloccato: prova", dettaglio={"postazione_id": 1})
        evento.refresh_from_db()
        self.assertEqual(evento.source.name, ev.FONTE_SOC)
        self.assertEqual((evento.payload["utente"], evento.payload["ip"]), ("u.sintetico", "10.1.2.3"))
        self.assertEqual(evento.decision_trace["decision"], "alert")
        alert = SecurityAlert.objects.get()
        self.assertEqual(alert.title, "PIN bloccato: prova")
        self.assertEqual(alert.severity, "warning")
        # Stessa chiave: stesso alert finché è aperto.
        ev.segnala("postazione_pin_bloccato", utente=self.user, chiave=(7,))
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_interruttore_spento_solo_kpi(self):
        set_setting(ev.chiave_interruttore("postazione_pin_bloccato"), False, category=soc_settings.CATEGORY)
        evento = ev.segnala("postazione_pin_bloccato", utente=self.user, chiave=(7,))
        evento.refresh_from_db()
        self.assertEqual(evento.decision_trace["decision"], "kpi_only")
        self.assertFalse(SecurityAlert.objects.exists())

    def test_canale_spento_nessun_evento(self):
        set_setting("portale.eventi.attivo", False, category=soc_settings.CATEGORY)
        self.assertIsNone(ev.segnala("login_bloccato", utente="x"))
        self.assertFalse(SecurityEventRecord.objects.exists())

    def test_tipo_senza_alert_resta_kpi(self):
        evento = ev.segnala("impersonazione_avviata", utente=self.user)
        evento.refresh_from_db()
        self.assertEqual(evento.decision_trace["decision"], "kpi_only")
        self.assertFalse(SecurityAlert.objects.exists())

    def test_finestra_e_una_volta(self):
        self.assertIsNotNone(ev.segnala("login_bloccato", utente="x", chiave=("x", "1.1.1.1"), finestra_minuti=60))
        self.assertIsNone(ev.segnala("login_bloccato", utente="x", chiave=("x", "1.1.1.1"), finestra_minuti=60))
        SecurityEventRecord.objects.update(occurred_at=timezone.now() - timedelta(minutes=61))
        self.assertIsNotNone(ev.segnala("login_bloccato", utente="x", chiave=("x", "1.1.1.1"), finestra_minuti=60))
        self.assertIsNotNone(ev.segnala("impersonazione_avviata", chiave=(1,), una_volta=True))
        self.assertIsNone(ev.segnala("impersonazione_avviata", chiave=(1,), una_volta=True))

    def test_codice_sconosciuto(self):
        self.assertIsNone(ev.segnala("non_esiste"))

    def test_interruttori_dal_catalogo(self):
        for tipo in ev.CATALOGO:
            presente = ev.chiave_interruttore(tipo.codice) in soc_settings.OPTIONS
            self.assertEqual(presente, tipo.alert and tipo.interruttore, tipo.codice)

    def test_blocco_axes(self):
        from axes.signals import user_locked_out

        for _ in range(3):  # axes lo manda a ogni tentativo durante il blocco
            user_locked_out.send("axes", request=self.request, username="mario.prova", ip_address="10.1.2.3")
        evento = SecurityEventRecord.objects.get(event_type="login_bloccato")
        self.assertIn("mario.prova", evento.payload["titolo"])
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_codice_mail_2fa_esaurito(self):
        from twofa.models import TwoFactorChallenge
        from twofa.utils import _MAX_ATTEMPTS, verify_email_otp

        TwoFactorChallenge.objects.create(user=self.user, code_hash="x" * 64,
                                          expires_at=timezone.now() + timedelta(minutes=10))
        for _ in range(_MAX_ATTEMPTS):
            verify_email_otp(self.user, "000000")
        self.assertEqual(SecurityEventRecord.objects.filter(event_type="twofa_bloccato").count(), 1)
