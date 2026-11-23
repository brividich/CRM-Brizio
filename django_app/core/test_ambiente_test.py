"""Barriere dell'ambiente di test sul server (HUB_AMBIENTE_TEST=1). Nessun dato reale."""
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings

from config import ambiente_test as AT
from config import rete_guard
from core import context_processors


class HostConsentitiTests(SimpleTestCase):
    def test_host_senza_schema_e_porta(self):
        self.assertEqual(AT.host_da_uri("ldap://dc1.example.invalid:389"), ["dc1.example.invalid"])
        self.assertEqual(AT.host_da_uri("ldaps://DC1.example.invalid/ dc2.example.invalid"),
                         ["dc1.example.invalid", "dc2.example.invalid"])
        self.assertEqual(AT.host_da_uri("192.0.2.10:636, 192.0.2.11"), ["192.0.2.10", "192.0.2.11"])
        self.assertEqual(AT.host_da_uri(""), [])

    def test_login_di_dominio_piu_aggiunte(self):
        host = AT.host_consentiti("ldap://dc1.example.invalid", "example.invalid", ["192.0.2.20"])
        self.assertEqual(host, {"dc1.example.invalid", "example.invalid", "192.0.2.20"})


class NomeDatabaseTests(SimpleTestCase):
    def test_il_database_deve_avere_test_nel_nome(self):
        AT.controlla_nome_db("default", "PortaleNovicrom_TEST")
        AT.controlla_nome_db("default", "hub_test_2026")
        for nome in ("PortaleNovicrom", "", None):
            with self.assertRaisesMessage(RuntimeError, "TEST nel nome"):
                AT.controlla_nome_db("default", nome)


class ComandiFermiTests(SimpleTestCase):
    def test_qcluster_e_coda_automazioni_non_partono(self):
        self.assertEqual(AT.comando_fermo(["manage.py", "qcluster"]), "qcluster")
        self.assertEqual(AT.comando_fermo(["manage.py", "process_automation_queue", "--settings=x"]),
                         "process_automation_queue")

    def test_gli_altri_comandi_partono(self):
        self.assertEqual(AT.comando_fermo(["manage.py", "migrate"]), "")
        self.assertEqual(AT.comando_fermo(["waitress-serve", "config.wsgi:application"]), "")
        self.assertEqual(AT.comando_fermo([]), "")


class ReteConAmmessiTests(SimpleTestCase):
    def setUp(self):
        rete_guard.install(consentiti=["192.0.2.10"])
        self.addCleanup(rete_guard.uninstall)

    def test_ammesso_passa_il_resto_no(self):
        rete_guard._controlla(("192.0.2.10", 389))
        rete_guard._controlla(("127.0.0.1", 8000))
        with self.assertRaises(rete_guard.ReteBloccata):
            rete_guard._controlla(("198.51.100.7", 25))

    def test_dopo_la_rimozione_gli_ammessi_si_azzerano(self):
        rete_guard.uninstall()
        rete_guard.install()
        with self.assertRaises(rete_guard.ReteBloccata):
            rete_guard._controlla(("192.0.2.10", 389))


class EtichettaTests(SimpleTestCase):
    def test_spenta_di_default(self):
        self.assertEqual(context_processors.ambiente_test(RequestFactory().get("/")), {})

    @override_settings(AMBIENTE_TEST=True)
    def test_accesa_con_la_variabile(self):
        self.assertEqual(context_processors.ambiente_test(RequestFactory().get("/")), {"ambiente_test": True})
        html = render_to_string("core/components/_ambiente_test.html")
        self.assertIn("AMBIENTE DI TEST", html)
        self.assertNotIn("{#", html)
