from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from core import checks

_DBCACHE = "django.core.cache.backends.db.DatabaseCache"
_LOCMEM = "django.core.cache.backends.locmem.LocMemCache"


class EnvDuplicateKeyCheckTests(SimpleTestCase):
    """core.E001: una stessa chiave su piu' righe di un .env runtime fa fallire `check`."""

    def _run(self, content: str):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".env"
            p.write_text(content, encoding="utf-8")
            with mock.patch("config.env_config.iter_runtime_env_paths", return_value=[p]):
                return checks.check_env_no_duplicate_keys(None)

    def test_rileva_chiave_duplicata(self):
        errs = self._run("OLLAMA_EMBED_ENABLED=True\nFOO=1\nOLLAMA_EMBED_ENABLED=0\n")
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0].id, "core.E001")
        self.assertIn("OLLAMA_EMBED_ENABLED", errs[0].msg)
        self.assertIn("[1, 3]", errs[0].msg)  # numeri di riga delle occorrenze

    def test_nessun_duplicato_ok(self):
        self.assertEqual(self._run("OLLAMA_EMBED_ENABLED=0\nFOO=1\n"), [])

    def test_ignora_commenti_e_righe_vuote(self):
        # la riga commentata non conta come occorrenza
        self.assertEqual(self._run("# OLLAMA_EMBED_ENABLED=True\n\nOLLAMA_EMBED_ENABLED=0\n"), [])

    def test_file_inesistente_non_rompe(self):
        with mock.patch(
            "config.env_config.iter_runtime_env_paths",
            return_value=[Path(tempfile.gettempdir()) / "non_esiste_xyz.env"],
        ):
            self.assertEqual(checks.check_env_no_duplicate_keys(None), [])


class RagCacheSizingCheckTests(SimpleTestCase):
    """core.W001: embeddings attivi + DatabaseCache con MAX_ENTRIES basso = warning."""

    def _caches(self, backend, max_entries=None):
        opts = {} if max_entries is None else {"MAX_ENTRIES": max_entries}
        return {"default": {"BACKEND": backend, "LOCATION": "c", "OPTIONS": opts}}

    def test_warning_se_max_entries_basso(self):
        with override_settings(OLLAMA_EMBED_ENABLED=True, CACHES=self._caches(_DBCACHE, 5000)):
            warns = checks.check_rag_cache_sizing(None)
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0].id, "core.W001")

    def test_ok_se_max_entries_alto(self):
        with override_settings(OLLAMA_EMBED_ENABLED=True, CACHES=self._caches(_DBCACHE, 50000)):
            self.assertEqual(checks.check_rag_cache_sizing(None), [])

    def test_nessun_warning_se_embeddings_off(self):
        with override_settings(OLLAMA_EMBED_ENABLED=False, CACHES=self._caches(_DBCACHE, 5000)):
            self.assertEqual(checks.check_rag_cache_sizing(None), [])

    def test_nessun_warning_se_non_databasecache(self):
        with override_settings(OLLAMA_EMBED_ENABLED=True, CACHES=self._caches(_LOCMEM)):
            self.assertEqual(checks.check_rag_cache_sizing(None), [])
