from __future__ import annotations

from django.test import TestCase

from core.legacy_anagrafica import resolve_notification_email
from core.notifiche import invia_notifica, invia_notifica_email


class ResolveNotificationEmailTests(TestCase):
    """Fix 3 — mai inviare al login legacy: il fallback su `email` vale solo se
    sembra un vero indirizzo (contiene @)."""

    def test_preferisce_email_notifica(self):
        self.assertEqual(
            resolve_notification_email(email="mrossi", email_notifica="m.rossi@novicrom.it"),
            "m.rossi@novicrom.it",
        )

    def test_scarta_login_senza_chiocciola(self):
        # 'email' in anagrafica_dipendenti è il LOGIN legacy, non un indirizzo.
        self.assertEqual(resolve_notification_email(email="mrossi", email_notifica=""), "")

    def test_usa_email_se_e_un_indirizzo(self):
        self.assertEqual(
            resolve_notification_email(email="m.rossi@novicrom.it", email_notifica=""),
            "m.rossi@novicrom.it",
        )


class InviaNotificaLoggingTests(TestCase):
    """Fix 4 — le notifiche non consegnate non spariscono in silenzio: warning nei log."""

    def test_invia_notifica_senza_utente_logga_warning(self):
        with self.assertLogs("core.notifiche", level="WARNING") as cm:
            invia_notifica(None, "generico", "messaggio di prova")
        self.assertTrue(cm.output, "atteso almeno un WARNING")

    def test_invia_notifica_email_nessun_destinatario_logga_warning(self):
        with self.assertLogs("core.notifiche", level="WARNING") as cm:
            created = invia_notifica_email("nessuno@inesistente.local", "generico", "prova")
        self.assertEqual(created, 0)
        self.assertTrue(cm.output, "atteso almeno un WARNING")
