"""Guardrail: librerie front-end self-hostate, niente CDN a runtime.

Verifica che (1) nessun template reale referenzi piu' `<script>`/`<link>` da CDN —
librerie (jsdelivr/unpkg/cdnjs) **e** font (Google Fonts) — e (2) i file
vendorizzati esistano (incluso il font Outfit self-hostato in A2).
"""
from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

DJANGO_APP = Path(__file__).resolve().parents[1]
VENDOR_DIR = DJANGO_APP / "core" / "static" / "core" / "vendor"

# CDN di librerie js/css E font (tutto va self-hostato in vendor/).
_CDN_TAG_RE = re.compile(
    r"<(?:script|link)\b[^>]*\b(?:src|href)\s*=\s*[\"'][^\"']*"
    r"(?:cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com"
    r"|fonts\.googleapis\.com|fonts\.gstatic\.com)",
    re.IGNORECASE,
)

EXPECTED_VENDOR_FILES = [
    "chartjs/chart.umd.min.js",
    "fullcalendar-6.1.11/index.global.min.js",
    "fullcalendar-6.1.17/index.global.min.js",
    "fullcalendar-6.1.17/locales-all.global.min.js",
    "frappe-gantt-0.6.1/frappe-gantt.min.js",
    "frappe-gantt-0.6.1/frappe-gantt.css",
    "sortablejs/Sortable.min.js",
    "html2canvas/html2canvas.min.js",
    "outfit/outfit.css",
    "tom-select/tom-select.complete.min.js",
    "tom-select/tom-select.min.css",
    "flatpickr/flatpickr.min.js",
    "flatpickr/flatpickr.min.css",
    "flatpickr/l10n-it.js",
]


class VendorAssetsTests(SimpleTestCase):
    def test_no_cdn_library_refs_in_real_templates(self):
        offenders: list[str] = []
        # Solo le directory `templates/` reali caricate da Django (esclude p.es.
        # i file orfani sotto */migrations/).
        for tpl in DJANGO_APP.glob("*/templates/**/*.html"):
            try:
                text = tpl.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in _CDN_TAG_RE.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{tpl.relative_to(DJANGO_APP)}:{line}")
        self.assertEqual(
            offenders,
            [],
            "Riferimenti CDN a runtime trovati (self-hostare in core/static/core/vendor/): "
            + ", ".join(offenders),
        )

    def test_vendored_files_present(self):
        missing = [rel for rel in EXPECTED_VENDOR_FILES if not (VENDOR_DIR / rel).is_file()]
        self.assertEqual(missing, [], f"File vendorizzati mancanti: {missing}")

    def test_tomselect_wired_in_base(self):
        base = (DJANGO_APP / "core" / "templates" / "core" / "base.html").read_text(
            encoding="utf-8", errors="ignore"
        )
        self.assertIn("tom-select/tom-select.min.css", base)
        self.assertIn("tom-select/tom-select.complete.min.js", base)
        self.assertIn("core/js/tomselect-init.js", base)
        self.assertTrue(
            (DJANGO_APP / "core" / "static" / "core" / "js" / "tomselect-init.js").is_file()
        )

    def test_tomselect_applied_to_pilot_select(self):
        rc = (
            DJANGO_APP / "dpi" / "templates" / "dpi" / "pages" / "report_conformita.html"
        ).read_text(encoding="utf-8", errors="ignore")
        self.assertIn('id="dipendente_id" class="js-searchable"', rc)

    def test_flatpickr_wired_in_base(self):
        base = (DJANGO_APP / "core" / "templates" / "core" / "base.html").read_text(
            encoding="utf-8", errors="ignore"
        )
        self.assertIn("flatpickr/flatpickr.min.css", base)
        self.assertIn("flatpickr/flatpickr.min.js", base)
        self.assertIn("flatpickr/l10n-it.js", base)
        self.assertIn("core/js/flatpickr-init.js", base)
        self.assertTrue(
            (DJANGO_APP / "core" / "static" / "core" / "js" / "flatpickr-init.js").is_file()
        )

    def test_flatpickr_applied_to_pilot_input(self):
        audit = (
            DJANGO_APP / "admin_portale" / "templates" / "admin_portale" / "pages" / "audit_log.html"
        ).read_text(encoding="utf-8", errors="ignore")
        self.assertIn('name="data" value="{{ filtro_data }}" class="js-datepicker"', audit)

    def test_command_palette_wired(self):
        base = (DJANGO_APP / "core" / "templates" / "core" / "base.html").read_text(
            encoding="utf-8", errors="ignore"
        )
        self.assertIn("command-palette-data", base)
        self.assertIn("core/js/command-palette.js", base)
        self.assertIn("core/css/command-palette.css", base)
        self.assertTrue((DJANGO_APP / "core" / "static" / "core" / "js" / "command-palette.js").is_file())
        self.assertTrue((DJANGO_APP / "core" / "static" / "core" / "css" / "command-palette.css").is_file())

    def test_chart_helper_present_and_used_in_pilot(self):
        self.assertTrue(
            (DJANGO_APP / "core" / "static" / "core" / "js" / "chart-helper.js").is_file()
        )
        stats = (
            DJANGO_APP / "anomalie" / "templates" / "anomalie" / "pages" / "anomalie_statistiche.html"
        ).read_text(encoding="utf-8", errors="ignore")
        self.assertIn("core/vendor/chartjs/chart.umd.min.js", stats)
        self.assertIn("core/js/chart-helper.js", stats)
        self.assertIn('id="chart-mese"', stats)
