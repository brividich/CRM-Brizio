"""Setup Wizard: riquadro «Collector CNC» (task CollectorCnc_<ENV>, stesso account del qcluster).

Il controllo legge ``deployment/setup_wizard.py`` senza importarlo (tkinter) e gli script
PowerShell come testo.
"""
from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase

DEPLOY = Path(__file__).resolve().parents[2] / "deployment"
WIZARD = DEPLOY / "setup_wizard.py"
INSTALLA = DEPLOY / "scripts" / "install-collector-cnc-task.ps1"
LAUNCHER = DEPLOY / "start_collector_cnc.ps1"


def _metodi() -> dict[str, str]:
    tree = ast.parse(WIZARD.read_text(encoding="utf-8"))
    dash = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ServerDashboard")
    return {n.name: ast.unparse(n) for n in dash.body if isinstance(n, ast.FunctionDef)}


class WizardCollectorCncTests(SimpleTestCase):
    def test_installa_con_lo_script_della_release_e_password_da_stdin(self):
        metodi = _metodi()
        installa = metodi["_cnc_install_task"]
        self.assertIn("install-collector-cnc-task.ps1", installa)
        self.assertIn("'current'", installa)
        esegui = metodi["_cnc_run_install"]
        # La password passa solo da stdin: nello script PowerShell non c'è.
        self.assertIn("[Console]::In.ReadLine()", esegui)
        self.assertIn("stdin_text=password", esegui)
        ps = esegui.split("ps = ", 1)[1].split("def _done", 1)[0]
        self.assertNotIn("password", ps.replace("ConvertTo-SecureString", ""))

    def test_stato_letto_nella_stessa_powershell_del_qcluster(self):
        fetch = _metodi()["_fetch_status"]
        self.assertEqual(fetch.count("subprocess.run("), 3)  # IIS, task (qcluster + collector), servizi
        self.assertIn("_cnc_task_name(env)", fetch)
        self.assertIn("collector_cnc.log", fetch)

    def test_script_ascii_e_stesso_account_del_qcluster(self):
        for script in (INSTALLA, LAUNCHER):
            self.assertTrue(script.read_bytes().isascii(), script.name)
        testo = INSTALLA.read_text(encoding="ascii")
        self.assertIn("'QCluster_' + $Environment", testo)
        self.assertIn("-Principal $worker.Principal", testo)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", testo)
        self.assertIn(r"current\deployment\start_collector_cnc.ps1", testo)
        self.assertIn("$register.Remove('Password')", testo)
