"""Setup Wizard: il migrate applica solo le migrazioni pendenti.

Prima ogni installazione/release lanciava ~30 ``manage.py migrate`` (uno per app,
più un globale) anche senza niente da applicare. Ora un solo
``showmigrations --plan`` decide: nessuna pendente → nessun migrate.
Il file si legge senza importarlo (tkinter).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase

WIZARD = Path(__file__).resolve().parents[2] / "deployment" / "setup_wizard.py"


def _funzione(nome: str):
    sorgente = WIZARD.read_text(encoding="utf-8")
    tree = ast.parse(sorgente)
    nodo = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == nome)
    spazio = {"re": re}
    exec(ast.get_source_segment(sorgente, nodo), spazio)
    return spazio[nome]


class WizardMigratePendentiTests(SimpleTestCase):
    def test_estrae_solo_le_non_applicate(self):
        parse = _funzione("_parse_pending_migrations")
        uscita = (
            "[X]  contenttypes.0001_initial\n"
            "[X]  core.0106_qualcosa\n"
            "[ ]  core.0107_sapere_cataloghi\n"
            "[ ]  dpi.0015_banco\n"
        )
        self.assertEqual(parse(uscita), ["core.0107_sapere_cataloghi", "dpi.0015_banco"])

    def test_tutto_applicato_lista_vuota(self):
        parse = _funzione("_parse_pending_migrations")
        self.assertEqual(parse("[X]  auth.0001_initial\n[X]  core.0001_initial\n"), [])

    def test_le_due_pagine_usano_la_funzione_condivisa(self):
        sorgente = WIZARD.read_text(encoding="utf-8")
        self.assertEqual(sorgente.count("return run_migrate_pendenti("), 2)
        self.assertNotIn('"migrate", m["app_label"]', sorgente)
