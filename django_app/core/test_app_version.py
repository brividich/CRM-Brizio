"""Lettura della versione dal file VERSION (single source of truth).

Regressione: il file VERSION era committato in UTF-8 **con BOM** e veniva letto
con ``encoding="utf-8"``. Poiche' ``str.strip()`` non rimuove U+FEFF (non e'
whitespace), la versione risultava ``"﻿1.3.0"``: un carattere invisibile in
testa che finiva nel footer del portale, nelle chiavi di versione scritte nel
.env e che faceva fallire `validate_deployment --format json` su stdout cp1252
(UnicodeEncodeError) — bloccando il release guard.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config.app_version import DEFAULT_APP_VERSION, load_app_version, version_file_path


class LoadAppVersionTests(SimpleTestCase):
    def _load_from(self, raw_bytes: bytes) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "VERSION"
            path.write_bytes(raw_bytes)
            with mock.patch("config.app_version.version_file_path", return_value=path):
                return load_app_version()

    def test_bom_is_stripped(self):
        # UTF-8 with BOM: e' quello che producono Notepad e PowerShell.
        self.assertEqual(self._load_from(b"\xef\xbb\xbf1.3.0\n"), "1.3.0")

    def test_plain_utf8_is_read(self):
        self.assertEqual(self._load_from(b"1.3.0\n"), "1.3.0")

    def test_version_has_no_invisible_characters(self):
        version = self._load_from(b"\xef\xbb\xbf1.3.0\n")
        self.assertNotIn("﻿", version)
        # Deve essere serializzabile anche su una console legacy (cp1252).
        version.encode("cp1252")

    def test_missing_file_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "NON_ESISTE"
            with mock.patch("config.app_version.version_file_path", return_value=path):
                self.assertEqual(load_app_version(), DEFAULT_APP_VERSION)

    def test_repo_version_file_is_clean(self):
        # Il file VERSION del repo non deve reintrodurre il BOM.
        raw = version_file_path().read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "VERSION ha di nuovo il BOM")
