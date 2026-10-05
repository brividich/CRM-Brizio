from unittest import mock

from django.test import SimpleTestCase, TestCase

from .credential_crypto import decifra
from .forms import CommunitySNMPForm
from .snmp import SNMPError, costruisci_credenziali, segreto_v3

# Valori sintetici: nessuna credenziale reale.
U, AK, PK = "utente-test", "chiave-auth-test", "chiave-priv-test"


class CredenzialiTests(SimpleTestCase):
    def test_v1_v2c_invariati(self):
        from puresnmp import V1, V2C
        self.assertEqual(costruisci_credenziali("pub", "v1"), V1("pub"))
        cred = costruisci_credenziali("pub", "v2c")
        self.assertIsInstance(cred, V2C)
        self.assertEqual(cred.mpm, 1)

    def test_v3_auth_senza_priv(self):
        cred = costruisci_credenziali(segreto_v3(U, "sha1", AK), "v3")
        self.assertEqual((cred.mpm, cred.username, cred.auth.method), (3, U, "sha1"))
        self.assertIsNone(cred.priv)

    def test_v3_priv_senza_plugin_errore_senza_chiavi(self):
        with mock.patch("importlib.util.find_spec", return_value=None):
            with self.assertRaises(SNMPError) as ctx:
                costruisci_credenziali(segreto_v3(U, "sha1", AK, "aes", PK), "v3")
        self.assertNotIn(PK, str(ctx.exception))
        self.assertNotIn(AK, str(ctx.exception))

    def test_v3_priv_con_plugin(self):
        with mock.patch("importlib.util.find_spec", return_value=object()):
            cred = costruisci_credenziali(segreto_v3(U, "sha1", AK, "aes", PK), "v3")
        self.assertEqual(cred.priv.method, "aes")

    def test_segreto_v3_validazioni(self):
        for args in [("",), (U, "xx", AK), (U, "", "", "aes", PK), (U, "sha1", ""),
                     (U, "sha1", AK, "aes", "")]:
            with self.assertRaises(SNMPError):
                segreto_v3(*args)

    def test_segreto_v3_corrotto(self):
        with self.assertRaises(SNMPError):
            costruisci_credenziali("non-json", "v3")


class CommunityV3FormTests(TestCase):
    base = {"nome": "ilo-test", "versione": "v3", "ordine": 0, "attiva": "on"}

    def test_salva_v3_cifrato(self):
        form = CommunitySNMPForm({**self.base, "v3_utente": U, "v3_auth": "sha1",
                                  "v3_auth_key": AK})
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        self.assertNotIn(AK, obj.segreto_cifrato)
        self.assertIn(AK, decifra(obj.segreto_cifrato))
        self.assertNotIn(AK, form.as_p())

    def test_v3_senza_utente_invalido(self):
        self.assertFalse(CommunitySNMPForm({**self.base, "v3_auth": "sha1"}).is_valid())

    def test_v2c_richiede_community(self):
        form = CommunitySNMPForm({**self.base, "versione": "v2c"})
        self.assertFalse(form.is_valid())
        self.assertIn("valore", form.errors)
        self.assertTrue(CommunitySNMPForm(
            {**self.base, "versione": "v2c", "valore": "pub"}).is_valid())


class DiscoveryV3Tests(SimpleTestCase):
    def test_scansione_accetta_v3_e_segreto_lungo(self):
        from .snmp import scansiona_hosts
        segreto = segreto_v3(U, "sha1", AK)

        class Client:
            def __init__(self, *a, **k):
                pass

            async def get(self, oid):
                raise OSError("nessuna risposta")

        with mock.patch("puresnmp.PyWrapper", lambda c: c), \
                mock.patch("puresnmp.Client", Client):
            self.assertEqual(list(scansiona_hosts(
                ["10.0.0.1"], communities=[segreto + " " * 80], version="v3",
                timeout=1, max_duration=5)), [])
