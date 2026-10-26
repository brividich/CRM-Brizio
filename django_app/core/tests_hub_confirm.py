"""Finestra di conferma del portale (core/js/hub-confirm.js) al posto di confirm() in tutti i moduli."""
from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

RADICE = Path(__file__).resolve().parent.parent
HUB_CONFIRM = RADICE / "core" / "static" / "core" / "js" / "hub-confirm.js"
NATIVO = re.compile(r"(?<![\w.$])(?:window\.)?confirm\(")


def _file_del_portale():
    """Template e script statici delle app, senza librerie di terzi e copie fuori uso."""
    for f in RADICE.rglob("*"):
        if f.suffix not in (".html", ".js") or not f.is_file():
            continue
        parti = f.relative_to(RADICE).parts
        if parti[0] in ("staticfiles", "media", "media_private") or "vendor" in parti or "node_modules" in parti:
            continue
        if parti[:2] == ("core", "migrations") or f.name.endswith(".min.js") or f == HUB_CONFIRM:
            continue
        if f.suffix == ".js" and "static" not in parti:
            continue
        yield f


class NienteConfirmDelBrowserTests(SimpleTestCase):
    def test_nessun_confirm_nativo(self):
        """Le conferme passano da data-hub-confirm, hx-confirm o hubConfirm(): mai la finestra del browser."""
        trovati = [
            f"{f.relative_to(RADICE)}:{n}"
            for f in _file_del_portale()
            for n, riga in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
            if NATIVO.search(riga)
        ]
        self.assertEqual(trovati, [])

    def test_testi_di_conferma_senza_escapejs(self):
        """Dentro un attributo basta l'autoescape: |escapejs mostrerebbe \\u0027 a video."""
        attr = re.compile(r'(?:data-hub-confirm|hx-confirm)="[^"]*\|escapejs')
        trovati = [
            str(f.relative_to(RADICE))
            for f in _file_del_portale()
            if f.suffix == ".html" and attr.search(f.read_text(encoding="utf-8", errors="ignore"))
        ]
        self.assertEqual(trovati, [])

    def test_vecchi_attributi_di_conferma_spariti(self):
        """data-confirm (contatori) e data-af-confirm (scheda asset) non hanno più chi li ascolta."""
        vecchio = re.compile(r"\sdata-(?:af-)?confirm=")
        trovati = [
            str(f.relative_to(RADICE))
            for f in _file_del_portale()
            if f.suffix == ".html" and vecchio.search(f.read_text(encoding="utf-8", errors="ignore"))
        ]
        self.assertEqual(trovati, [])


class ComponenteHubConfirmTests(SimpleTestCase):
    def test_copre_invii_clic_e_htmx(self):
        js = HUB_CONFIRM.read_text(encoding="utf-8")
        self.assertIn("document.addEventListener('submit'", js)
        self.assertIn("document.addEventListener('click'", js)
        self.assertIn("document.addEventListener('htmx:confirm'", js)
        self.assertIn("issueRequest(true)", js)
        self.assertIn("window.hubConfirm = hubConfirm", js)

    def test_caricato_dalla_base(self):
        base = (RADICE / "core" / "templates" / "core" / "base.html").read_text(encoding="utf-8")
        self.assertRegex(base, r"core/js/hub-confirm\.js' %\}\?v=\d+")
        self.assertRegex(base, r"core/css/hub-confirm\.css' %\}\?v=\d+")
