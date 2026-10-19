"""Setup Wizard: ogni schermata chiama solo metodi che ha davvero.

InstallPage, ReleaseRunPage e ServerDashboard non condividono una base comune
con gli helper: un metodo aggiunto a una sola classe e chiamato da un'altra
rompe l'installazione in produzione a metà (AttributeError dopo l'attivazione,
19/10/2026: ``_q_sync_after_deploy`` esisteva solo in ServerDashboard).
Il controllo legge ``deployment/setup_wizard.py`` senza importarlo (tkinter).
"""
from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase

WIZARD = Path(__file__).resolve().parents[2] / "deployment" / "setup_wizard.py"


def _classi(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}


def _definiti(cls: ast.ClassDef, classi: dict[str, ast.ClassDef]) -> set[str]:
    """Metodi e attributi ``self.X = ...`` della classe e delle sue basi nel file."""
    nomi: set[str] = set()
    for nodo in ast.walk(cls):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nomi.add(nodo.name)
        elif isinstance(nodo, (ast.Assign, ast.AnnAssign)):
            bersagli = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
            for t in bersagli:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                    nomi.add(t.attr)
                elif isinstance(t, ast.Name):
                    nomi.add(t.id)
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id in classi:
            nomi |= _definiti(classi[base.id], classi)
    return nomi


def _chiamati(cls: ast.ClassDef) -> set[str]:
    nomi = set()
    for nodo in ast.walk(cls):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                and isinstance(nodo.func.value, ast.Name) and nodo.func.value.id == "self"
                and nodo.func.attr.startswith("_")):
            nomi.add(nodo.func.attr)
    return nomi


class WizardMetodiPagineTests(SimpleTestCase):
    def test_ogni_schermata_ha_i_metodi_che_chiama(self):
        tree = ast.parse(WIZARD.read_text(encoding="utf-8"))
        classi = _classi(tree)
        mancanti = {}
        for nome in ("InstallPage", "ReleaseRunPage", "UninstallRunPage", "ServerDashboard"):
            self.assertIn(nome, classi, f"classe {nome} non trovata in setup_wizard.py")
            manca = sorted(_chiamati(classi[nome]) - _definiti(classi[nome], classi))
            if manca:
                mancanti[nome] = manca
        self.assertEqual(mancanti, {}, "Metodi chiamati ma non definiti nella classe (AttributeError in esecuzione)")

    def test_riavvio_qcluster_dopo_deploy_in_tutte_le_schermate(self):
        classi = _classi(ast.parse(WIZARD.read_text(encoding="utf-8")))
        for nome in ("InstallPage", "ReleaseRunPage", "ServerDashboard"):
            self.assertIn("_q_sync_after_deploy", _definiti(classi[nome], classi), nome)
