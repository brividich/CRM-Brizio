from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner

# Cartella dei file temporanei dei test (django_app/.tmp_tests): alcuni test vi
# creano media_root usa-e-getta che, se il test si interrompe, restano su disco.
TMP_TESTS_DIR = Path(__file__).resolve().parents[1] / ".tmp_tests"
TMP_TESTS_ORPHAN_GLOBS = ("tasks_test_media_*",)


def cleanup_tmp_tests(root: Path = TMP_TESTS_DIR) -> None:
    """Rimuove le cartelle temporanee orfane lasciate dai test in `.tmp_tests`."""
    if not root.is_dir():
        return
    for pattern in TMP_TESTS_ORPHAN_GLOBS:
        for path in root.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)


class NovicromDiscoverRunner(DiscoverRunner):
    """Use the release-suite labels when test discovery is invoked bare."""

    def build_suite(self, test_labels=None, **kwargs):
        if not test_labels:
            test_labels = list(getattr(settings, "DEFAULT_TEST_LABELS", ()))
        return super().build_suite(test_labels, **kwargs)

    def teardown_test_environment(self, **kwargs):
        super().teardown_test_environment(**kwargs)
        cleanup_tmp_tests()
