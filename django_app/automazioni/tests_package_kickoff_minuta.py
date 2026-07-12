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
        # anti-doppioni: condizione cooldown_group per-incontro
        ops = {c["operator"] for c in rule["conditions"]}
        self.assertIn("cooldown_group", ops)
        cd = next(c for c in rule["conditions"] if c["operator"] == "cooldown_group")
        self.assertEqual(cd["field"], "id")
        self.assertIn(":", cd["value"])  # formato namespace:minuti

    def test_convocazione_package_shape(self):
        path = (
            Path(__file__).resolve().parent
            / "packages"
            / "au53_kickoff_convocazione_incontro.automation_package.json"
        )
        self.assertTrue(path.exists(), "Package convocazione mancante")
        data = json.loads(path.read_text(encoding="utf-8"))
        rule = data["proposed_rules"][0]
        self.assertEqual(rule["source_code"], "tasks_kickoff")
        self.assertEqual(rule["operation_type"], "insert")
        self.assertEqual(rule["actions"][0]["action_type"], "send_meeting_invite")
