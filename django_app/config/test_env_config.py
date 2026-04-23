from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from config.env_config import default_env_path, iter_runtime_env_paths, load_dotenv_into_environ, primary_runtime_env_path


def _make_workspace_tempdir(prefix: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".tmp_tests"
    root.mkdir(exist_ok=True)
    path = root / f"{prefix}{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class RuntimeEnvPathTests(SimpleTestCase):
    def test_deploy_current_layout_prefers_persistent_config_env(self):
        tmpdir = _make_workspace_tempdir("env-config-current-")
        try:
            env_root = tmpdir / "test"
            project_dir = env_root / "current" / "django_app"
            persistent_env = env_root / "config" / ".env"
            release_env = project_dir / ".env"
            persistent_env.parent.mkdir(parents=True)
            project_dir.mkdir(parents=True)
            persistent_env.write_text("LDAP_ENABLED=1\n", encoding="utf-8")
            release_env.write_text("LDAP_ENABLED=0\n", encoding="utf-8")

            paths = iter_runtime_env_paths(project_dir)

            self.assertEqual(paths[0], persistent_env)
            self.assertEqual(paths[-1], release_env)
            self.assertEqual(primary_runtime_env_path(project_dir), persistent_env)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_runtime_env_loading_keeps_persistent_values_over_release_copy(self):
        tmpdir = _make_workspace_tempdir("env-config-precedence-")
        try:
            env_root = tmpdir / "test"
            project_dir = env_root / "current" / "django_app"
            persistent_env = env_root / "config" / ".env"
            release_env = project_dir / ".env"
            persistent_env.parent.mkdir(parents=True)
            project_dir.mkdir(parents=True)
            persistent_env.write_text(
                "LDAP_ENABLED=1\nLDAP_SERVER=ldap://persistent.example.local\n",
                encoding="utf-8",
            )
            release_env.write_text(
                "LDAP_ENABLED=0\nLDAP_SERVER=ldap://release.example.local\nONLY_RELEASE=ok\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                for path in iter_runtime_env_paths(project_dir):
                    load_dotenv_into_environ(path)

                self.assertEqual(os.environ["LDAP_ENABLED"], "1")
                self.assertEqual(os.environ["LDAP_SERVER"], "ldap://persistent.example.local")
                self.assertEqual(os.environ["ONLY_RELEASE"], "ok")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_default_env_path_honors_explicit_persistent_env_override(self):
        tmpdir = _make_workspace_tempdir("env-config-explicit-")
        try:
            persistent_env = tmpdir / "config" / ".env"
            persistent_env.parent.mkdir(parents=True)
            persistent_env.write_text("LDAP_ENABLED=1\n", encoding="utf-8")

            with patch.dict(os.environ, {"PORTAL_CONFIG_ENV_FILE": str(persistent_env)}, clear=True):
                self.assertEqual(default_env_path(), persistent_env)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
