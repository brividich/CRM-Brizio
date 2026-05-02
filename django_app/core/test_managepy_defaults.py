from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossibile caricare il modulo da {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManagePySettingsSelectionTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        repo_root = Path(__file__).resolve().parents[2]
        cls.root_manage = _load_module("repo_manage", repo_root / "manage.py")
        cls.django_app_manage = _load_module("django_app_manage", repo_root / "django_app" / "manage.py")

    def test_root_manage_uses_test_settings_for_test_command(self):
        self.assertEqual(
            self.root_manage._default_settings_module(["manage.py", "test"]),
            "config.settings.test",
        )

    def test_django_app_manage_uses_test_settings_for_test_command(self):
        self.assertEqual(
            self.django_app_manage._default_settings_module(["manage.py", "test"]),
            "config.settings.test",
        )

    def test_manage_defaults_to_dev_for_non_test_commands(self):
        self.assertEqual(
            self.root_manage._default_settings_module(["manage.py", "runserver"]),
            "config.settings.dev",
        )
        self.assertEqual(
            self.django_app_manage._default_settings_module(["manage.py", "migrate"]),
            "config.settings.dev",
        )

    def test_manage_keeps_dev_default_when_settings_is_explicit(self):
        argv = ["manage.py", "test", "--settings=config.settings.prod"]
        self.assertEqual(self.root_manage._default_settings_module(argv), "config.settings.dev")
        self.assertEqual(self.django_app_manage._default_settings_module(argv), "config.settings.dev")

    def test_test_settings_force_sqlite_even_if_env_requests_sqlserver(self):
        with patch.dict("os.environ", {"DB_ENGINE": "sqlserver"}, clear=False):
            test_settings = importlib.import_module("config.settings.test")
            test_settings = importlib.reload(test_settings)

        self.assertEqual(test_settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")

    def test_test_settings_define_release_suite_labels_for_bare_discovery(self):
        test_settings = importlib.import_module("config.settings.test")

        self.assertEqual(test_settings.TEST_RUNNER, "config.test_runner.NovicromDiscoverRunner")
        self.assertEqual(test_settings.DEFAULT_TEST_LABELS, ("core", "tasks", "attrezzature"))

    def test_test_runner_uses_release_suite_labels_when_no_labels_are_passed(self):
        from config.test_runner import NovicromDiscoverRunner

        runner = NovicromDiscoverRunner(verbosity=0)
        with patch("django.test.runner.DiscoverRunner.build_suite", return_value="suite") as build_suite:
            suite = runner.build_suite([])

        self.assertEqual(suite, "suite")
        build_suite.assert_called_once()
        args, _kwargs = build_suite.call_args
        self.assertEqual(args[0], ["core", "tasks", "attrezzature"])
