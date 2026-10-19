"""Tema scuro: il CSS generato deve restare allineato al generatore e agganciato a base.html."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]
CSS = REPO / "django_app" / "core" / "static" / "core" / "css" / "dark-safety.css"
GEN = REPO / "tools" / "gen_dark_safety.py"
BASE = REPO / "django_app" / "core" / "templates" / "core" / "base.html"


class DarkSafetyCssTests(SimpleTestCase):
    def _load_generator(self):
        spec = importlib.util.spec_from_file_location("gen_dark_safety", GEN)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_css_allineato_al_generatore(self):
        mod = self._load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "dark-safety.css"
            mod.main(str(out))
            self.assertEqual(
                out.read_text(encoding="utf-8"),
                CSS.read_text(encoding="utf-8"),
                "dark-safety.css non coincide con tools/gen_dark_safety.py: rigenerarlo",
            )

    def test_base_html_carica_il_css(self):
        self.assertIn("core/css/dark-safety.css", BASE.read_text(encoding="utf-8"))

    def test_regole_solo_sotto_tema_scuro(self):
        for line in CSS.read_text(encoding="utf-8").splitlines():
            if line.startswith(("/*", " ", "")) or line.startswith("   "):
                continue
            self.assertTrue(line.startswith("body.theme-dark"), line[:80])
