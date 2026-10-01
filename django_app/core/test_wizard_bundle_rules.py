"""Il bundle di SetupWizard.exe non deve mai imbarcare dati personali locali.

Le esclusioni stanno in deployment/setup_wizard_bundle_rules.json e le legge
SetupWizard.spec: se una cartella sensibile manca, finisce dentro l'exe.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.test import SimpleTestCase

RULES_PATH = Path(__file__).resolve().parents[2] / "deployment" / "setup_wizard_bundle_rules.json"


class WizardBundleRulesTests(SimpleTestCase):
    def setUp(self):
        self.rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))

    def test_cartelle_con_dati_personali_escluse(self):
        dirs = set(self.rules["exclude_dir_names"])
        for name in ("media", "media_private", "logs", ".tmp_tests", ".claude", ".venv", "venv"):
            self.assertIn(name, dirs)

    def test_file_sensibili_esclusi(self):
        patterns = set(self.rules["exclude_file_patterns"])
        for pattern in (".env", "*.sqlite3", "DIPENDENTI.csv", "medical-examinations-people.xlsx", "*.bak"):
            self.assertIn(pattern, patterns)
