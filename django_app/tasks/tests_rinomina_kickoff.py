"""Rinomina dei KICK-OFF storici: tocca le proposte automatiche, non le scelte a mano."""
from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from tasks.models import Project


class RinominaKickoffTests(TestCase):
    def setUp(self):
        autore = get_user_model().objects.create_user(username="rinomina", password="x")
        self.automatico = Project.objects.create(
            name="KICK-OFF 1", kickoff_number=1, client_name="ACME",
            part_number="PN-9", created_by=autore,
        )
        self.manuale = Project.objects.create(
            name="Revamping linea 3", kickoff_number=2, client_name="Beta",
            created_by=autore,
        )

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("rinomina_kickoff", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_non_scrive(self):
        output = self._run()
        self.automatico.refresh_from_db()
        self.assertEqual(self.automatico.name, "KICK-OFF 1")
        self.assertIn("ACME", output)

    def test_apply_ricompone_il_nome_automatico(self):
        self._run("--apply")
        self.automatico.refresh_from_db()
        self.assertEqual(self.automatico.name, "ACME \u00b7 PN-9 \u00b7 KICK-OFF 1")

    def test_le_scritture_avvengono_dopo_aver_letto_tutto(self):
        """Regressione HY010: su SQL Server l'UPDATE non puo' partire mentre il
        cursore di lettura e' ancora aperto. La lettura deve chiudersi prima."""
        autore = self.automatico.created_by
        for numero in range(3, 8):
            Project.objects.create(
                name=f"KICK-OFF {numero}", kickoff_number=numero,
                client_name=f"Cliente {numero}", created_by=autore,
            )
        self._run("--apply")
        rinominati = Project.objects.filter(name__startswith="Cliente ").count()
        self.assertEqual(rinominati, 5)

    def test_nome_scritto_a_mano_resta(self):
        self._run("--apply")
        self.manuale.refresh_from_db()
        self.assertEqual(self.manuale.name, "Revamping linea 3")

    def test_all_sovrascrive_anche_i_nomi_manuali(self):
        self._run("--apply", "--all")
        self.manuale.refresh_from_db()
        self.assertEqual(self.manuale.name, "Beta \u00b7 KICK-OFF 2")
