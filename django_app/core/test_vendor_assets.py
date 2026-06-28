"""Guardrail: librerie front-end self-hostate, niente CDN a runtime.

Verifica che (1) nessun template reale referenzi piu' `<script>`/`<link>` da CDN
(jsdelivr/unpkg/cdnjs) — i Google Fonts sono esclusi: sono un intervento separato
(A2) e degradano comunque a font di sistema — e (2) i file vendorizzati esistano.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

DJANGO_APP = Path(__file__).resolve().parents[1]
VENDOR_DIR = DJANGO_APP / "core" / "static" / "core" / "vendor"

# Solo CDN di LIBRERIE js/css (font esclusi: googleapis/gstatic).
_CDN_TAG_RE = re.compile(
    r"<(?:script|link)\b[^>]*\b(?:src|href)\s*=\s*[\"'][^\"']*"
    r"(?:cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com)",
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
