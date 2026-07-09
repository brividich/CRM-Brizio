"""Report + riassegnazione guidata dei dipendenti con reparto legacy 'orfano'
(management command report_reparti_orfani).

Contesto: il campo REPARTO mostrato in lista Persone legge il testo libero
legacy su anagrafica_dipendenti, non il catalogo Reparto. Cancellare un
reparto dal catalogo lascia i dipendenti che lo avevano ancora con quel
valore testuale "orfano".
"""
from __future__ import annotations

from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from .models import DipendenteAnagraficaAziendale, DipendenteCambiamentoOrganizzativo, Reparto
from .tests import _ensure_anagrafica_table

User = get_user_model()


def _insert_dipendente(nome: str, cognome: str, reparto: str, *, attivo: int = 1) -> int:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO anagrafica_dipendenti (nome, cognome, reparto, attivo) VALUES (%s, %s, %s, %s)",
            [nome, cognome, reparto, attivo],
        )
        if connection.vendor == "sqlite":
            return int(cur.lastrowid)
    with connection.cursor() as cur:
        cur.execute("SELECT TOP 1 id FROM anagrafica_dipendenti ORDER BY id DESC")
        return int(cur.fetchone()[0])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReportRepartiOrfaniTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        self.admin = User.objects.create_superuser(
            username="reparti_orfani_admin", email="reparti_orfani_admin@x.local", password="x"
        )

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("report_reparti_orfani", *args, stdout=out)
        return out.getvalue()

    def test_nessun_orfano_se_tutti_i_reparti_sono_a_catalogo(self):
        Reparto.objects.create(nome="CNC")
        _insert_dipendente("Mario", "Rossi", "CNC")
        output = self._run()
        self.assertIn("Nessun reparto orfano", output)

    def test_segnala_dipendente_con_reparto_cancellato_dal_catalogo(self):
        Reparto.objects.create(nome="CNC")
        _insert_dipendente("Mario", "Rossi", "CNC5G")
        output = self._run()
        self.assertIn("CNC5G", output)
        self.assertIn("Rossi", output)
        self.assertIn("1 dipendenti", output)

    def test_esclude_ex_dipendenti_cessati(self):
        Reparto.objects.create(nome="CNC")
        legacy_id = _insert_dipendente("Mario", "Rossi", "CNC5G")
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=legacy_id, data_cessazione=date(2026, 1, 1),
        )
        output = self._run()
        self.assertIn("Nessun reparto orfano", output)

    def test_reassign_dry_run_non_scrive(self):
        Reparto.objects.create(nome="CNC")
        legacy_id = _insert_dipendente("Mario", "Rossi", "CNC5G")
        output = self._run("--reassign", "CNC5G=CNC")
        self.assertIn("Dry-run", output)
        self.assertEqual(
            DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).count(), 0
        )

    def test_reassign_con_target_non_a_catalogo_solleva_errore(self):
        Reparto.objects.create(nome="CNC")
        _insert_dipendente("Mario", "Rossi", "CNC5G")
        with self.assertRaises(CommandError):
            self._run("--reassign", "CNC5G=NONESISTENTE")

    def test_reassign_formato_non_valido_solleva_errore(self):
        with self.assertRaises(CommandError):
            self._run("--reassign", "formatosbagliato")

    def test_apply_riassegna_reparto_storicizza_e_sincronizza_area(self):
        rep = Reparto.objects.create(nome="CNC", caporeparto_legacy_id=501)
        legacy_id = _insert_dipendente("Mario", "Rossi", "CNC5G")

        output = self._run("--reassign", "CNC5G=CNC", "--apply", "--eseguito-da", self.admin.username)

        self.assertIn("1 dipendenti riassegnati", output)
        with connection.cursor() as cur:
            cur.execute("SELECT reparto FROM anagrafica_dipendenti WHERE id = %s", [legacy_id])
            self.assertEqual(cur.fetchone()[0], "CNC")

        storico = DipendenteCambiamentoOrganizzativo.objects.get(
            legacy_anagrafica_id=legacy_id, tipo=DipendenteCambiamentoOrganizzativo.TIPO_REPARTO,
        )
        self.assertEqual(storico.valore_precedente, "CNC5G")
        self.assertEqual(storico.valore_nuovo, "CNC")
        self.assertEqual(storico.created_by_id, self.admin.pk)

        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=legacy_id)
        self.assertEqual(az.area, "CNC")
        self.assertEqual(az.caporeparto_legacy_id, 501)

    def test_apply_senza_eseguito_da_non_solleva_errore(self):
        Reparto.objects.create(nome="CNC")
        self._insert_and_apply()

    def _insert_and_apply(self):
        legacy_id = _insert_dipendente("Luigi", "Verdi", "CNC5G")
        output = self._run("--reassign", "CNC5G=CNC", "--apply")
        self.assertIn("1 dipendenti riassegnati", output)

    def test_eseguito_da_utente_inesistente_solleva_errore(self):
        Reparto.objects.create(nome="CNC")
        _insert_dipendente("Mario", "Rossi", "CNC5G")
        with self.assertRaises(CommandError):
            self._run("--reassign", "CNC5G=CNC", "--apply", "--eseguito-da", "utente_fantasma")
