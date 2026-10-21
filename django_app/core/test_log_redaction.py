"""GDPR 21/10/2026 (E7): codici fiscali e IBAN mascherati nei log. Valori sintetici."""
import logging

from django.test import SimpleTestCase

from core.log_redaction import MascheraDatiPersonali, maschera


class LogRedactionTests(SimpleTestCase):
    def test_codice_fiscale_e_iban(self):
        testo = maschera("cedolino RSSMRA80A01H501U conto IT60X0542811101000000123456 ok")
        self.assertNotIn("RSSMRA80A01H501U", testo)
        self.assertNotIn("0542811101000000123456", testo)
        self.assertIn("RSS***********01U", testo)
        self.assertIn("ok", testo)

    def test_testo_normale_invariato(self):
        self.assertEqual(maschera("Import completato: 12 righe, mese 2026-09"), "Import completato: 12 righe, mese 2026-09")

    def test_filtro_su_messaggio_argomenti_e_traceback(self):
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "CF=%s", ("RSSMRA80A01H501U",), None)
        try:
            raise ValueError("duplicato RSSMRA80A01H501U")
        except ValueError:
            import sys

            record.exc_info = sys.exc_info()
        self.assertTrue(MascheraDatiPersonali().filter(record))
        self.assertNotIn("RSSMRA80A01H501U", record.getMessage())
        self.assertNotIn("RSSMRA80A01H501U", record.exc_text)
