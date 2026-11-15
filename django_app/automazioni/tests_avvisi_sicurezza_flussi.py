"""Avvisi di sicurezza all'utente come flussi spegnibili (il codice 2FA resta fuori)."""
from types import SimpleNamespace

from django.core import mail
from django.test import TestCase, override_settings

from .managed_flows import assicura_installati
from .models import EmailInviata, ManagedFlow


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@test.local")
class AvvisiSicurezzaFlussiTests(TestCase):
    def setUp(self):
        assicura_installati()
        self.utente = SimpleNamespace(email="utente@example.com", pk=None)

    def _accendi(self, codice, acceso):
        rule = ManagedFlow.objects.get(code=codice).rule
        rule.is_active, rule.is_draft = acceso, False
        rule.save(update_fields=["is_active", "is_draft"])
        return rule

    def test_avviso_account_parte_ed_e_collegato_al_flusso(self):
        from core.security_notify import notify_security_event

        rule = self._accendi("sicurezza_avvisi_account", True)
        self.assertTrue(notify_security_event(self.utente, "Password cambiata", "Test sintetico."))
        self.assertEqual(len(mail.outbox), 1)
        riga = EmailInviata.objects.get()
        self.assertEqual((riga.sorgente, riga.regola_id), ("sicurezza_avvisi_account", rule.pk))

    def test_avviso_account_spento_non_parte(self):
        from core.security_notify import notify_security_event

        self._accendi("sicurezza_avvisi_account", False)
        self.assertFalse(notify_security_event(self.utente, "Password cambiata", "Test sintetico."))
        self.assertEqual(len(mail.outbox), 0)

    def test_nuovo_dispositivo_spento_non_parte_acceso_si(self):
        from unittest.mock import patch

        from core import dispositivi

        with patch("dashboard.scadenze_digest._email_utente", return_value="utente@example.com"):
            self._accendi("sicurezza_nuovo_dispositivo", False)
            dispositivi._mail(self.utente, "Nuovo accesso sintetico")
            self.assertEqual(len(mail.outbox), 0)
            rule = self._accendi("sicurezza_nuovo_dispositivo", True)
            dispositivi._mail(self.utente, "Nuovo accesso sintetico")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailInviata.objects.get().regola_id, rule.pk)
