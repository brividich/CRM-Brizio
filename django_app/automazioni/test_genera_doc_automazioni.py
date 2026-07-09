"""Generatore documentazione automazioni (genera_doc_automazioni).

Verifica che il doc si generi da SCHEDULES, includa ogni automazione, sia
idempotente (--check passa subito dopo la generazione) e traduca la cadenza.
"""
from __future__ import annotations

from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from automazioni.management.commands.genera_doc_automazioni import _descr_cron
from automazioni.schedules import SCHEDULES


class DescrCronTests(SimpleTestCase):
    def test_traduzioni_cadenza(self):
        self.assertIn("07:00", _descr_cron("0 7 * * *"))
        self.assertIn("da lun a ven", _descr_cron("0 7 * * 1-5"))
        self.assertIn("giorno 1", _descr_cron("0 8 1 1,4,7,10 *"))
        self.assertEqual(_descr_cron("non-un-cron"), "cron `non-un-cron`")


class GeneraDocTests(SimpleTestCase):
    def test_genera_e_check_idempotente(self):
        call_command("genera_doc_automazioni", verbosity=0)
        # subito dopo la generazione, --check non deve sollevare
        out = StringIO()
        call_command("genera_doc_automazioni", check=True, stdout=out)
        self.assertIn("allineato", out.getvalue())

    def test_doc_contiene_ogni_automazione(self):
        import automazioni.schedules as sched_mod

        call_command("genera_doc_automazioni", verbosity=0)
        md = (Path(sched_mod.__file__).resolve().parents[2] / "docs" / "AUTOMAZIONI.md").read_text(encoding="utf-8")
        self.assertIn(f"**Totale automazioni attive:** {len(SCHEDULES)}", md)
        for spec in SCHEDULES:
            self.assertIn(f"`{spec['name']}`", md, spec["name"])
