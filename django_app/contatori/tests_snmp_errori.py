import asyncio
from unittest import mock

from django.test import SimpleTestCase
from puresnmp.exc import ErrorResponse, Timeout
from x690.types import ObjectIdentifier

from .snmp import NESSUNA_RISPOSTA, SNMPError, descrivi_errore, leggi_oids

SYS_DESCR = "1.3.6.1.2.1.1.1.0"


class DescriviErroreTests(SimpleTestCase):
    def test_authorization_error_spiega_permessi_non_oid(self):
        exc = ErrorResponse.construct(16, ObjectIdentifier(SYS_DESCR))
        testo = descrivi_errore(exc)
        self.assertIn("authorizationError, codice 16", testo)
        self.assertIn("Non e' un problema di OID", testo)
        self.assertIn("snmpv3 only", testo)
        self.assertNotIn("unknown error", testo)

    def test_no_such_name_indica_oid_e_profilo(self):
        testo = descrivi_errore(ErrorResponse.construct(
            2, ObjectIdentifier("1.3.6.1.4.1.11.2.14.11.5.1.1.2.0")))
        self.assertIn("1.3.6.1.4.1.11.2.14.11.5.1.1.2.0", testo)
        self.assertIn("noSuchName, codice 2", testo)
        self.assertIn("profilo", testo)

    def test_timeout_elenca_cause(self):
        self.assertEqual(descrivi_errore(Timeout("3 second timeout")), NESSUNA_RISPOSTA)
        self.assertEqual(descrivi_errore(asyncio.TimeoutError()), NESSUNA_RISPOSTA)
        self.assertIn("UDP 161", NESSUNA_RISPOSTA)

    def test_report_snmpv3(self):
        from puresnmp.exc import SnmpError
        testo = descrivi_errore(SnmpError("Error response from remote device: Unknown user-name"))
        self.assertIn("utente SNMPv3 sconosciuto", testo)
        testo = descrivi_errore(SnmpError("Error response from remote device: Wrong message digest"))
        self.assertIn("MD5/SHA", testo)

    def test_porta_chiusa_e_fallback(self):
        self.assertIn("non e' attivo", descrivi_errore(ConnectionResetError(10054, "reset")))
        self.assertEqual(descrivi_errore(SNMPError("gia' tradotto")), "gia' tradotto")
        self.assertEqual(descrivi_errore(ValueError("boh")), "boh")


class LetturaConErroreTests(SimpleTestCase):
    def test_leggi_oids_riporta_messaggio_dettagliato(self):
        async def rifiuta(_oid):
            raise ErrorResponse.construct(16, ObjectIdentifier(SYS_DESCR))

        client = mock.Mock()
        client.get = rifiuta
        with mock.patch("puresnmp.PyWrapper", return_value=client):
            with self.assertRaises(SNMPError) as ctx:
                leggi_oids("192.0.2.10", [SYS_DESCR], community="test", version="v2c")
        messaggio = str(ctx.exception)
        self.assertTrue(messaggio.startswith("192.0.2.10: "))
        self.assertIn("codice 16", messaggio)
        self.assertNotIn("test", messaggio.replace("192.0.2.10", ""))
