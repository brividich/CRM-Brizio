"""Setup Wizard: rinnovo del certificato HTTPS (IIS + Recovery Kit) da «Gestisci server».

Il file del wizard si legge senza importarlo (tkinter): si eseguono solo le funzioni pure.
"""
from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path

from django.test import SimpleTestCase

WIZARD = Path(__file__).resolve().parents[2] / "deployment" / "setup_wizard.py"


def _sorgente():
    return WIZARD.read_text(encoding="utf-8")


def _funzioni(*nomi):
    sorgente = _sorgente()
    tree = ast.parse(sorgente)
    spazio = {"re": re, "json": json}
    for nome in nomi:
        nodo = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == nome)
        exec(ast.get_source_segment(sorgente, nodo), spazio)
    return [spazio[n] for n in nomi]


class CopertureNomiTests(SimpleTestCase):
    def setUp(self):
        self.coperto, self.scoperti = _funzioni("_cert_name_covered", "_cert_uncovered_hosts")

    def test_nome_esatto_e_maiuscole(self):
        self.assertTrue(self.coperto("Hub.Esempio.local", ["hub.esempio.local"]))

    def test_wildcard_un_solo_livello(self):
        self.assertTrue(self.coperto("hub.esempio.local", ["*.esempio.local"]))
        self.assertFalse(self.coperto("a.hub.esempio.local", ["*.esempio.local"]))
        self.assertFalse(self.coperto("esempio.local", ["*.esempio.local"]))

    def test_elenca_i_nomi_non_coperti_senza_doppioni(self):
        self.assertEqual(
            self.scoperti(["hub.esempio.local", "", "portale.altro.it", "portale.altro.it"], ["*.esempio.local"]),
            ["portale.altro.it"],
        )


class PassphraseENomeKitTests(SimpleTestCase):
    def test_regole_passphrase_come_recovery_kit(self):
        (problema,) = _funzioni("_kit_passphrase_problem")
        buona = "cavallo batteria graffetta corretta lampione"
        self.assertEqual(problema(buona, buona), "")
        self.assertIn("non coincidono", problema(buona, buona + "x"))
        self.assertIn("troppo debole", problema("una due tre quattro", "una due tre quattro"))

    def test_nome_kit_con_ambiente_e_ora(self):
        (nome,) = _funzioni("_cert_kit_filename")
        self.assertEqual(nome("PROD", datetime(2026, 11, 22, 9, 5)), "prod-20261122-0905.hubkit")

    def test_json_dopo_il_marcatore(self):
        (parse,) = _funzioni("_parse_cert_json")
        self.assertEqual(parse('rumore\n@@CERT_JSON@@{"a": 1}\n'), {"a": 1})
        self.assertIsNone(parse("niente"))
        self.assertIsNone(parse("@@CERT_JSON@@{rotto"))


class ScriptPowerShellTests(SimpleTestCase):
    def test_password_mai_sulla_riga_di_comando(self):
        sorgente = _sorgente()
        self.assertIn('"HUB_PFX_PW"', sorgente)
        corpo = sorgente[sorgente.index("def _cert_ps("):sorgente.index("def _cert_manage(")]
        self.assertNotIn("pfx_password]", corpo)          # non è un argomento del processo
        self.assertIn("-PfxPath", corpo)

    def test_recovery_kit_con_passphrase_su_stdin_e_verifica(self):
        sorgente = _sorgente()
        corpo = sorgente[sorgente.index("def _run_cert_renew("):sorgente.index("def _open_live_password_reset(")]
        self.assertIn('"--passphrase-stdin"', corpo)
        self.assertIn('"--pfx-thumbprint", new_tp', corpo)
        self.assertIn('"hub_recovery_kit", "verify"', corpo)
