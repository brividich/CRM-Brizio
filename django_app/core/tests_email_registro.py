"""Ogni mail di send_hub_mail compare in Automazioni → Mail inviate, e l'invio non ne dipende."""
from __future__ import annotations

from unittest.mock import patch

from django.core import mail
from django.test import TestCase

from automazioni.models import EmailInviata
from core.email_utils import send_hub_mail


class RegistroMailTests(TestCase):
    def test_mail_inviata_nel_registro(self):
        send_hub_mail("Oggetto sintetico", "Testo", ["a@example.com"], email_type="Scadenzario", cc=["b@example.com"])
        self.assertEqual(len(mail.outbox), 1)
        riga = EmailInviata.objects.get()
        self.assertEqual((riga.origine, riga.sorgente, riga.oggetto, riga.esito),
                         ("hub", "Scadenzario", "Oggetto sintetico", EmailInviata.ESITO_INVIATA))
        self.assertEqual((riga.destinatari, riga.copia), ("a@example.com", "b@example.com"))

    def test_errore_registrato_e_rilanciato(self):
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp sintetico")):
            with self.assertRaises(OSError):
                send_hub_mail("Oggetto", "Testo", ["a@example.com"])
        riga = EmailInviata.objects.get()
        self.assertEqual(riga.esito, EmailInviata.ESITO_ERRORE)
        self.assertIn("smtp sintetico", riga.errore)

    def test_registro_rotto_non_ferma_la_mail(self):
        with patch("automazioni.mail_inviate.registra", side_effect=RuntimeError("sintetico")):
            self.assertEqual(send_hub_mail("Oggetto", "Testo", ["a@example.com"]), 1)
        self.assertEqual(len(mail.outbox), 1)
