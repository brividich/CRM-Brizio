"""Regole dell'anonimizzazione e barriere del profilo copia_anonima (nessun dato reale)."""
import socket

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from config import rete_guard
from core.copia_anonima import regole as R


class RegoleTests(SimpleTestCase):
    def test_colonna_sconosciuta_viene_sostituita(self):
        self.assertEqual(R.classifica("app_nuova", "campo_mai_visto", "nvarchar"), R.TESTO)

    def test_persone_e_contatti(self):
        self.assertEqual(R.classifica("anagrafica_dipendenti", "cognome", "nvarchar"), R.COGNOME)
        self.assertEqual(R.classifica("anagrafica_dipendenti", "nome", "nvarchar"), R.NOME)
        self.assertEqual(R.classifica("tickets_ticket", "richiedente_nome", "nvarchar"), R.PERSONA)
        self.assertEqual(R.classifica("anagrafica_dipendenteanagraficacivile", "codice_fiscale", "nvarchar"), R.CONTATTO)
        self.assertEqual(R.classifica("anagrafica_dipendenti", "matricola", "nvarchar"), R.CONTATTO)

    def test_mail_e_segreti_anche_nelle_tabelle_di_configurazione(self):
        self.assertEqual(R.classifica("core_siteconfig", "email_notifica", "nvarchar"), R.EMAIL)
        self.assertEqual(R.classifica("contatori_impostazionisnmp", "snmp_community", "nvarchar"), R.SEGRETO)
        self.assertEqual(R.classifica("auth_user", "password", "nvarchar"), R.SEGRETO)
        self.assertEqual(R.classifica("automazioni_teamswebhookpreset", "webhook_url", "nvarchar"), R.SEGRETO)

    def test_valori_tecnici_restano(self):
        self.assertEqual(R.classifica("tickets_ticket", "stato", "nvarchar"), R.TIENI)
        self.assertEqual(R.classifica("pulsanti", "label", "nvarchar"), R.TIENI)
        self.assertEqual(R.classifica("app_nuova", "campo", "nvarchar", con_scelte=True), R.TIENI)
        self.assertEqual(R.classifica("assets_asset", "name", "nvarchar"), R.TIENI)

    def test_nomi_tecnici_non_scambiati_per_persone(self):
        self.assertEqual(R.classifica("core_catalogo", "chiave", "nvarchar"), R.TIENI)
        self.assertEqual(R.classifica("assets_workmachine", "nome", "nvarchar"), R.TIENI)
        self.assertNotEqual(R.classifica("app_nuova", "macchina", "nvarchar"), R.CONTATTO)
        self.assertNotEqual(R.classifica("app_nuova", "skip_reason", "nvarchar"), R.CONTATTO)

    def test_persone_non_restano_nei_cataloghi(self):
        for colonna in ("responsabile_nome", "ragione_sociale", "tax_code", "updated_by"):
            self.assertEqual(R.classifica("core_siteconfig", colonna, "nvarchar"), R.PERSONA)

    def test_valore_finto_adatto_al_campo(self):
        self.assertEqual(R.adatta_al_campo(R.TESTO, "UUIDField"), R.UUID)
        self.assertEqual(R.adatta_al_campo(R.SEGRETO, "UUIDField"), R.UUID)
        self.assertEqual(R.adatta_al_campo(R.PERSONA, "JSONField"), R.TESTO)
        self.assertEqual(R.adatta_al_campo(R.TIENI, "UUIDField"), R.TIENI)
        self.assertEqual(R.adatta_al_campo(R.PERSONA, "CharField"), R.PERSONA)

    def test_binari_e_tabelle_da_svuotare(self):
        self.assertEqual(R.classifica("qualunque", "pdf_content", "varbinary"), R.BINARIO)
        for tabella in ("django_session", "core_auditlog", "django_q_schedule", "automazioni_emailinviata"):
            self.assertEqual(R.classifica_tabella(tabella), R.SVUOTA)
        self.assertIsNone(R.classifica_tabella("tickets_ticket"))


class ReteGuardTests(SimpleTestCase):
    def setUp(self):
        rete_guard.install()
        self.addCleanup(rete_guard.uninstall)

    def test_host_esterno_bloccato(self):
        with socket.socket() as s:
            with self.assertRaises(rete_guard.ReteBloccata):
                s.connect(("192.0.2.1", 25))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            with self.assertRaises(rete_guard.ReteBloccata):
                s.sendto(b"x", ("192.0.2.1", 514))

    def test_loopback_ammesso(self):
        self.assertTrue(rete_guard.host_locale("127.0.0.1"))
        self.assertTrue(rete_guard.host_locale("localhost"))
        self.assertFalse(rete_guard.host_locale("smtp.example.invalid"))


class BersaglioTests(SimpleTestCase):
    def test_rifiuta_senza_profilo(self):
        with self.assertRaisesMessage(CommandError, "copia_anonima"):
            call_command("anonimizza_copia", "--esegui")

    @override_settings(COPIA_ANONIMA=True)
    def test_rifiuta_altro_motore(self):
        with self.assertRaisesMessage(CommandError, "SQL Server"):
            call_command("anonimizza_copia", "--esegui")
