"""Catalogo errori SNMP: codice, causa e azione. Solo dati sintetici, SNMP mai reale."""
import asyncio
import socket
from unittest import mock

from django.test import SimpleTestCase
from puresnmp.exc import ErrorResponse, SnmpError, Timeout
from x690.types import ObjectIdentifier

from . import errori_snmp as es

SYS_DESCR = "1.3.6.1.2.1.1.1.0"


class ClassificaTests(SimpleTestCase):
    def _codice(self, exc, **kw):
        return es.da_eccezione(exc, **kw)["codice"]

    def test_timeout_snmp_003_con_host_e_tempo(self):
        err = es.da_eccezione(Timeout("3 second timeout"), host="192.0.2.7", porta=161, timeout=3)
        self.assertEqual(err["codice"], "SNMP-003")
        self.assertIn("192.0.2.7:161 in 3 s", err["messaggio"])
        self.assertIn("community errata", err["azione"])
        self.assertEqual(self._codice(asyncio.TimeoutError()), "SNMP-003")

    def test_v3_rifiutato_snmp_004(self):
        for testo in ("Unknown user-name", "Wrong message digest", "unable to decrypt"):
            self.assertEqual(self._codice(SnmpError(f"Error response from remote device: {testo}")),
                             "SNMP-004", testo)

    def test_oid_assente_snmp_005(self):
        err = es.da_eccezione(ErrorResponse.construct(2, ObjectIdentifier("1.3.6.1.4.1.99.1.0")))
        self.assertEqual(err["codice"], "SNMP-005")
        self.assertIn("1.3.6.1.4.1.99.1.0", err["messaggio"])
        self.assertIn("profilo", err["azione"])

    def test_permessi_community_snmp_007(self):
        self.assertEqual(self._codice(ErrorResponse.construct(16, ObjectIdentifier(SYS_DESCR))), "SNMP-007")

    def test_testo_gia_salvato_dai_job(self):
        # I job salvano il testo di descrivi_errore: la classificazione funziona anche da li'.
        from .snmp import NESSUNA_RISPOSTA
        self.assertEqual(es.classifica(f"192.0.2.9: {NESSUNA_RISPOSTA}").codice, "SNMP-003")
        self.assertEqual(es.classifica("qualcosa di mai visto").codice, "SNMP-000")

    def test_ogni_voce_ha_titolo_e_azione(self):
        for codice, voce in es.CATALOGO.items():
            self.assertEqual(voce.codice, codice)
            self.assertTrue(voce.titolo and voce.azione, codice)

    def test_testo_con_codice(self):
        testo = es.testo_con_codice(Timeout("x"))
        self.assertTrue(testo.startswith("[SNMP-003] "))
        self.assertLessEqual(len(es.testo_con_codice(ValueError("y" * 900))), 500)


class ValidaHostTests(SimpleTestCase):
    def test_ip_valido(self):
        self.assertEqual(es.valida_host(" 192.0.2.10 "), "192.0.2.10")

    def test_indirizzo_non_valido_snmp_001(self):
        for valore in ("", "300.1.1.1", "host con spazi", "a" * 300, "http://192.0.2.1"):
            with self.assertRaises(es.ErroreSNMPCatalogato) as ctx:
                es.valida_host(valore)
            self.assertEqual(ctx.exception.codice, "SNMP-001", valore)

    def test_nome_non_risolto_snmp_002(self):
        with mock.patch("socket.getaddrinfo", side_effect=socket.gaierror("no")):
            with self.assertRaises(es.ErroreSNMPCatalogato) as ctx:
                es.valida_host("stampante-inesistente.example")
        self.assertEqual(ctx.exception.codice, "SNMP-002")
        self.assertIn("stampante-inesistente.example", str(ctx.exception))

    def test_nome_risolto_in_ipv4(self):
        risposta = [(socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.44", 161))]
        with mock.patch("socket.getaddrinfo", return_value=risposta):
            self.assertEqual(es.valida_host("mfc-sintetica.example"), "192.0.2.44")


class NessunaCommunityPredefinitaTests(SimpleTestCase):
    """La community storica era pubblica su GitHub: nessun default nel codice."""

    def test_nessun_default_nelle_funzioni_snmp(self):
        import inspect
        from . import snmp
        for nome in ("leggi_oids", "leggi_colonna", "leggi_specifiche", "scansiona_rete",
                     "scansiona_hosts", "leggi_consumabili", "leggi_macchina"):
            default = inspect.signature(getattr(snmp, nome)).parameters["community"].default
            self.assertEqual(default, "", nome)

    def test_community_vuota_errore_snmp_008(self):
        from .snmp import costruisci_credenziali
        for versione in ("v1", "v2c", "v3"):
            with self.assertRaises(es.ErroreSNMPCatalogato) as ctx:
                costruisci_credenziali("", versione)
            self.assertEqual(ctx.exception.codice, "SNMP-008")

    def test_default_modello_vuoto(self):
        from .models import ImpostazioniSNMP
        self.assertEqual(ImpostazioniSNMP._meta.get_field("community").default, "")


class ValoreNumericoTests(SimpleTestCase):
    def test_valore_non_numerico_snmp_006(self):
        self.assertEqual(es.valore_numerico(b"1234", "A4 B/N"), 1234)
        for valore in (b"abc", None, -5, 10 ** 13):
            with self.assertRaises(es.ErroreSNMPCatalogato) as ctx:
                es.valore_numerico(valore, "A4 B/N")
            self.assertEqual(ctx.exception.codice, "SNMP-006", valore)
            self.assertIn("A4 B/N", str(ctx.exception))
