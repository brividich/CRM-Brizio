"""Test del manifest di build e del badge git di sviluppo.

Il badge e' uno strumento diagnostico: se git non c'e', non risponde o mente,
deve sparire — mai rompere una pagina. I test qui sotto tengono ferma questa regola.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from core import build_info
from core.context_processors import dev_git_badge


class BuildInfoTempRoot:
    """Context manager: BASE_DIR fittizio con (o senza) BUILD_INFO.json alla radice."""

    def __init__(self, content: str | None):
        self._content = content
        self._tmp = tempfile.TemporaryDirectory()

    def __enter__(self):
        root = Path(self._tmp.name)
        base_dir = root / "django_app"
        base_dir.mkdir()
        if self._content is not None:
            (root / build_info.BUILD_INFO_FILENAME).write_text(self._content, encoding="utf-8")
        self._override = override_settings(BASE_DIR=base_dir)
        self._override.enable()
        return root

    def __exit__(self, *exc):
        self._override.disable()
        self._tmp.cleanup()
        return False


class ReadBuildInfoTests(SimpleTestCase):
    def test_file_assente_significa_sviluppo(self):
        with BuildInfoTempRoot(None):
            self.assertIsNone(build_info.read_build_info())

    def test_pacchetto_sano_da_branch(self):
        payload = {
            "source": "branch",
            "commit": "a" * 40,
            "commit_short": "aaaaaaa",
            "branch": "release/prod",
            "built_at": "2026-07-14T10:00:00.000000+02:00",
            "built_by": "l.bova",
            "dirty": False,
            "dirty_files": [],
            "delta_vs_export_branch": 0,
        }
        with BuildInfoTempRoot(json.dumps(payload)):
            info = build_info.read_build_info()

        self.assertFalse(info["malformed"])
        self.assertEqual(info["source"], "branch")
        self.assertEqual(info["commit_short"], "aaaaaaa")
        self.assertEqual(info["branch"], "release/prod")
        self.assertEqual(info["delta_vs_export_branch"], 0)
        self.assertFalse(info["has_drift"])

    def test_pacchetto_da_working_tree_e_in_deriva(self):
        payload = {
            "source": "working-tree",
            "commit": None,
            "commit_short": None,
            "branch": None,
            "dirty": True,
            "dirty_files": ["M  django_app/core/views.py", "A  docs/nota.md"],
            "delta_vs_export_branch": 3,
        }
        with BuildInfoTempRoot(json.dumps(payload)):
            info = build_info.read_build_info()

        self.assertEqual(info["source"], "working-tree")
        self.assertIsNone(info["commit"])
        self.assertIsNone(info["branch"])
        self.assertTrue(info["dirty"])
        self.assertEqual(info["dirty_count"], 2)
        self.assertEqual(info["delta_vs_export_branch"], 3)
        self.assertTrue(info["has_drift"])

    def test_delta_assente_non_diventa_zero(self):
        """Pacchetti anteriori a questo campo: 'non lo so' != 'va tutto bene'."""
        payload = {"source": "branch", "commit_short": "bbbbbbb", "branch": "release/prod", "dirty": False}
        with BuildInfoTempRoot(json.dumps(payload)):
            info = build_info.read_build_info()

        self.assertIsNone(info["delta_vs_export_branch"])
        self.assertFalse(info["has_drift"])

    def test_file_malformato_e_segnalato_non_ignorato(self):
        with BuildInfoTempRoot("{ questo non e' json"):
            info = build_info.read_build_info()

        self.assertTrue(info["malformed"])
        self.assertTrue(info["has_drift"])

    def test_json_valido_ma_non_oggetto(self):
        with BuildInfoTempRoot('["lista", "non", "oggetto"]'):
            self.assertTrue(build_info.read_build_info()["malformed"])


class PorcelainParsingTests(SimpleTestCase):
    def test_parsing_stati_e_raggruppamento_per_app(self):
        output = (
            "M  django_app/assenze/views.py\n"
            "A  django_app/schede_sicurezza/admin.py\n"
            " M django_app/core/tests.py\n"
            "?? formazione_export.json\n"
            "R  docs/vecchio.md -> docs/nuovo.md\n"
            "M  deployment/setup_wizard.py\n"
        )
        files = build_info.parse_porcelain(output)

        self.assertEqual(len(files), 6)
        self.assertEqual(files[0], {"status": "M", "path": "django_app/assenze/views.py", "app": "assenze"})
        self.assertEqual(files[2]["status"], "M")  # " M" — modificato ma non staged
        self.assertEqual(files[3]["app"], "(root)")
        self.assertEqual(files[4]["path"], "docs/nuovo.md")  # rinomina: conta la destinazione
        self.assertEqual(files[5]["app"], "deployment")

    def test_righe_vuote_o_troncate_ignorate(self):
        self.assertEqual(build_info.parse_porcelain("\n  \nM\n"), [])


class DevGitBadgeTests(SimpleTestCase):
    def setUp(self):
        cache.delete("core:dev_git_state:v1")

    def tearDown(self):
        cache.delete("core:dev_git_state:v1")

    @contextmanager
    def fake_repo(self):
        """Radice fittizia che contiene un .git: il collector prosegue oltre la guardia."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            with patch("core.build_info._repo_root", return_value=root):
                yield root

    @override_settings(DEBUG=False)
    def test_in_produzione_nessuna_chiave_e_nessuna_chiamata_a_git(self):
        with patch("core.build_info.subprocess.run") as run:
            self.assertEqual(dev_git_badge(None), {})
        run.assert_not_called()

    @override_settings(DEBUG=True)
    def test_git_assente_non_solleva_e_non_mostra_il_badge(self):
        with patch("core.build_info.subprocess.run", side_effect=FileNotFoundError("git")):
            self.assertEqual(dev_git_badge(None), {})

    @override_settings(DEBUG=True)
    def test_git_lento_non_blocca_la_pagina(self):
        with patch(
            "core.build_info.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            self.assertEqual(dev_git_badge(None), {})

    @override_settings(DEBUG=True)
    def test_stato_completo_con_due_contatori(self):
        def fake_git(cmd, **kwargs):
            args = cmd[3:]  # salta ["git", "-C", <root>]
            if args[:2] == ["status", "--porcelain"]:
                out = "M  django_app/assenze/views.py\nA  django_app/assenze/urls.py\n?? scratch.json\n"
            elif args[:1] == ["rev-parse"]:
                out = "feature/guardrail\n"
            elif args[:1] == ["rev-list"]:
                out = "4\n"
            else:
                out = ""
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        with self.fake_repo(), patch("core.build_info.subprocess.run", side_effect=fake_git):
            ctx = dev_git_badge(None)

        state = ctx["dev_git"]
        self.assertEqual(state["branch"], "feature/guardrail")
        self.assertFalse(state["detached"])
        self.assertEqual(state["dirty_count"], 3)
        self.assertEqual(state["ahead_count"], 4)
        self.assertEqual(dict(state["dirty_groups"]), {"assenze": 2, "(root)": 1})
        self.assertEqual(state["release_branch"], "release/prod")

    @override_settings(DEBUG=True)
    def test_head_detached_non_calcola_il_delta(self):
        def fake_git(cmd, **kwargs):
            args = cmd[3:]
            if args[:2] == ["status", "--porcelain"]:
                out = ""
            elif args[:1] == ["rev-parse"]:
                out = "HEAD\n"
            else:
                self.fail("con HEAD detached il delta non va nemmeno tentato")
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        with self.fake_repo(), patch("core.build_info.subprocess.run", side_effect=fake_git):
            state = dev_git_badge(None)["dev_git"]

        self.assertTrue(state["detached"])
        self.assertIsNone(state["ahead_count"])
        self.assertFalse(state["alert"])

    @override_settings(DEBUG=True)
    def test_branch_di_release_assente_lascia_il_delta_ignoto(self):
        def fake_git(cmd, **kwargs):
            args = cmd[3:]
            if args[:2] == ["status", "--porcelain"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if args[:1] == ["rev-parse"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="main\n", stderr="")
            # rev-list contro un branch inesistente: git esce non-zero
            return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="unknown revision")

        with self.fake_repo(), patch("core.build_info.subprocess.run", side_effect=fake_git):
            state = dev_git_badge(None)["dev_git"]

        self.assertIsNone(state["ahead_count"])

    @override_settings(DEBUG=True)
    def test_alert_oltre_soglia(self):
        def fake_git(cmd, **kwargs):
            args = cmd[3:]
            if args[:2] == ["status", "--porcelain"]:
                out = "".join(f"M  django_app/core/f{i}.py\n" for i in range(6))
            elif args[:1] == ["rev-parse"]:
                out = "main\n"
            else:
                out = "0\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        with self.fake_repo(), patch("core.build_info.subprocess.run", side_effect=fake_git):
            state = dev_git_badge(None)["dev_git"]

        self.assertEqual(state["dirty_count"], 6)
        self.assertTrue(state["alert"])
