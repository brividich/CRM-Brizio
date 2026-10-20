"""Setup Wizard: il pannello server non deve consumare RAM a ogni giro.

Due difetti storici (20/10/2026): ogni pulsante IIS/qcluster e «Aggiorna ora»
apriva un ciclo di aggiornamento in più che non si fermava (3 PowerShell ogni
5 s per ciclo), e i log venivano letti per intero a ogni giro solo per
mostrarne le ultime righe. Il controllo legge ``deployment/setup_wizard.py``
senza importarlo (tkinter).
"""
from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

WIZARD = Path(__file__).resolve().parents[2] / "deployment" / "setup_wizard.py"


def _albero() -> ast.Module:
    return ast.parse(WIZARD.read_text(encoding="utf-8"))


def _metodo(cls: ast.ClassDef, nome: str) -> ast.FunctionDef:
    for nodo in cls.body:
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nome:
            return nodo
    raise AssertionError(f"{cls.name}.{nome} non trovato")


def _dashboard(tree: ast.Module) -> ast.ClassDef:
    return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ServerDashboard")


def _funzione_modulo(tree: ast.Module, nome: str):
    """Compila una funzione di modulo del wizard da sola (senza tkinter)."""
    nodo = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == nome)
    spazio = {"os": os, "Path": Path}
    exec(compile(ast.Module(body=[nodo], type_ignores=[]), str(WIZARD), "exec"), spazio)
    return spazio[nome]


class WizardRisorseTests(SimpleTestCase):
    def test_nessun_ciclo_parallelo_di_aggiornamento(self):
        dash = _dashboard(_albero())
        # Solo _refresh_done e _auto_refresh_tick programmano il giro automatico;
        # tutti gli altri passano da _refresh(), che annulla quello già programmato.
        for metodo in dash.body:
            if not isinstance(metodo, ast.FunctionDef):
                continue
            testo = ast.unparse(metodo)
            if metodo.name not in ("_refresh_done", "_auto_refresh_tick"):
                self.assertNotIn("self._auto_refresh_tick)", testo, metodo.name)
        update_ui = ast.unparse(_metodo(dash, "_update_ui"))
        self.assertNotIn("REFRESH_MS", update_ui, "_update_ui non deve riprogrammare il giro")
        refresh = ast.unparse(_metodo(dash, "_refresh"))
        self.assertIn("after_cancel", refresh)
        self.assertIn("_refresh_running", refresh)

    def test_log_letti_solo_in_coda(self):
        fetch = ast.unparse(_metodo(_dashboard(_albero()), "_fetch_status"))
        self.assertNotIn("readlines", fetch)
        self.assertIn("_read_log_tail", fetch)

    def test_read_log_tail(self):
        leggi = _funzione_modulo(_albero(), "_read_log_tail")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "waitress_stdout.log"
            path.write_text("".join(f"riga {i}\n" for i in range(50_000)), encoding="utf-8")
            coda = leggi(path, 40, max_bytes=4096)
            righe = coda.splitlines()
            self.assertEqual(len(righe), 40)
            self.assertEqual(righe[-1], "riga 49999")
            self.assertEqual(righe[0], "riga 49960")

            corto = Path(tmp) / "qcluster.log"
            corto.write_text("a\nb\nc\n", encoding="utf-8")
            self.assertEqual(leggi(corto, 20), "a\nb\nc\n")

            vuoto = Path(tmp) / "vuoto.log"
            vuoto.write_bytes(b"")
            self.assertEqual(leggi(vuoto, 20), "")
