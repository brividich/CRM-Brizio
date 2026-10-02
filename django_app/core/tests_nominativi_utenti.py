"""Nominativo utente nel formato unico del portale: ``COGNOME NOME`` maiuscolo."""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase

from core.form_fields import user_display_label
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.legacy_utils import provision_legacy_user
from core.models import Profile


class UserFullNameTests(SimpleTestCase):
    def test_tiene_ordine_salvato_e_mette_maiuscolo(self):
        # first_name contiene il cognome: nasce da utenti.nome «Cognome Nome».
        user = get_user_model()(username="l.bova", first_name="Bova", last_name="luca")
        self.assertEqual(user.get_full_name(), "BOVA LUCA")

    def test_cognome_composto_resta_intero(self):
        user = get_user_model()(username="m.de", first_name="De", last_name="Luca Mario")
        self.assertEqual(user.get_full_name(), "DE LUCA MARIO")

    def test_senza_nome_ricade_sullo_username(self):
        user = get_user_model()(username="svc.backup")
        self.assertEqual(user.get_full_name(), "")
        self.assertEqual(user_display_label(user), "svc.backup")


class ProvisionLegacyUserNameTests(TestCase):
    def test_nuovo_utente_ad_salvato_in_maiuscolo(self):
        legacy = provision_legacy_user("n.uovo@example.local", full_name="Nuovo  Utente")
        self.assertEqual(legacy.nome, "NUOVO UTENTE")

    def test_login_non_riscrive_un_nome_gia_normalizzato(self):
        UtenteLegacy.objects.create(
            nome="ROSSI MARIO", email="m.rossi@example.local", password="*AD_MANAGED*", attivo=True
        )
        legacy = provision_legacy_user("m.rossi@example.local", full_name="Rossi Mario")
        self.assertEqual(legacy.nome, "ROSSI MARIO")


class NormalizzaNomiUtentiCommandTests(TestCase):
    def setUp(self):
        self.collegato = UtenteLegacy.objects.create(
            nome="Mario Rossi", email="m.rossi@example.local", password="x", attivo=True
        )
        self.libero = UtenteLegacy.objects.create(
            nome="Verdi  anna", email="a.verdi@example.local", password="x", attivo=True
        )
        AnagraficaDipendente.objects.create(
            nome="Mario", cognome="Rossi", aliasusername="m.rossi", email="m.rossi@example.local"
        )
        self.django_user = get_user_model().objects.create(
            username="m.rossi@example.local", first_name="Mario", last_name="Rossi"
        )
        Profile.objects.create(user=self.django_user, legacy_user_id=self.collegato.id)

    def _nome(self, legacy_id):
        with connection.cursor() as cur:
            cur.execute("SELECT nome FROM utenti WHERE id = %s", [legacy_id])
            return cur.fetchone()[0]

    def test_dry_run_non_scrive(self):
        out = StringIO()
        call_command("normalizza_nomi_utenti", stdout=out)
        self.assertIn("Dry-run", out.getvalue())
        self.assertEqual(self._nome(self.collegato.id), "Mario Rossi")

    def test_apply_usa_anagrafica_o_solo_maiuscolo(self):
        call_command("normalizza_nomi_utenti", "--apply", stdout=StringIO())
        # Collegato al dipendente: ordine certo dall'anagrafica.
        self.assertEqual(self._nome(self.collegato.id), "ROSSI MARIO")
        # Non collegato: stesso ordine, solo maiuscolo e spazi ripuliti.
        self.assertEqual(self._nome(self.libero.id), "VERDI ANNA")
        self.django_user.refresh_from_db()
        self.assertEqual(self.django_user.get_full_name(), "ROSSI MARIO")
