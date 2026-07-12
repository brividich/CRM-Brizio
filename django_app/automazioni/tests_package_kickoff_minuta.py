import json
from pathlib import Path

from django.test import SimpleTestCase


class KickoffMinutaPackageTests(SimpleTestCase):
    def test_package_shape(self):
        path = (
            Path(__file__).resolve().parent
            / "packages"
            / "au52_kickoff_minuta_incontro.automation_package.json"
        )
        self.assertTrue(path.exists(), "Package mancante")
        data = json.loads(path.read_text(encoding="utf-8"))
        rule = data["proposed_rules"][0]
        self.assertEqual(rule["source_code"], "tasks_kickoff")
        self.assertEqual(rule["operation_type"], "update")
        self.assertEqual(rule["watched_field"], "note")
        self.assertEqual(rule["actions"][0]["action_type"], "send_meeting_minute")
