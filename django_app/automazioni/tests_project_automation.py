import json
from pathlib import Path

from django.test import SimpleTestCase

from automazioni.source_registry import get_source_definition


class ProjectSourceTests(SimpleTestCase):
    def test_project_source_registered(self):
        d = get_source_definition("tasks_project")
        self.assertIsNotNone(d)
        self.assertEqual(d["table_name"], "tasks_project")
        names = {f["name"] for f in d["fields"]}
        self.assertTrue({"phase", "safety_impact", "vrf_status", "project_manager_id"} <= names)

    def test_trigger_file_targets_project_table(self):
        path = Path(__file__).resolve().parent / "migrations" / "trg_tasks_project_automation.sql"
        self.assertTrue(path.exists(), "File trigger progetto mancante")
        sql = path.read_text(encoding="utf-8")
        self.assertIn("tasks_project", sql)
        self.assertIn("automation_event_queue", sql)
        self.assertIn("old_safety_impact", sql)
        self.assertIn("old_vrf_status", sql)


class ProjectAlertPackagesTests(SimpleTestCase):
    def _rule(self, filename):
        path = Path(__file__).resolve().parent / "packages" / filename
        self.assertTrue(path.exists(), f"Package {filename} mancante")
        return json.loads(path.read_text(encoding="utf-8"))["proposed_rules"][0]

    def test_safety_package(self):
        rule = self._rule("au54_kickoff_impatto_sicurezza.automation_package.json")
        self.assertEqual(rule["source_code"], "tasks_project")
        self.assertEqual(rule["watched_field"], "safety_impact")
        self.assertEqual(rule["actions"][0]["action_type"], "send_project_alert")
        self.assertEqual(rule["actions"][0]["alert"], "safety")

    def test_vrf_pending_package(self):
        rule = self._rule("au55_kickoff_vrf_pending.automation_package.json")
        self.assertEqual(rule["source_code"], "tasks_project")
        self.assertEqual(rule["watched_field"], "phase")
        ops = {(c["field"], c["operator"]) for c in rule["conditions"]}
        self.assertIn(("phase", "changed_to"), ops)
        self.assertIn(("vrf_status", "equals"), ops)
        self.assertEqual(rule["actions"][0]["alert"], "vrf_pending")
