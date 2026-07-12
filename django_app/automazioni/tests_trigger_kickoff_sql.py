from pathlib import Path

from django.test import SimpleTestCase


class KickoffTriggerSqlTests(SimpleTestCase):
    def test_trigger_file_targets_kickoff_table(self):
        path = (
            Path(__file__).resolve().parent
            / "migrations"
            / "trg_tasks_kickoff_automation.sql"
        )
        self.assertTrue(path.exists(), "File trigger mancante")
        sql = path.read_text(encoding="utf-8")
        self.assertIn("tasks_kickoffmeeting", sql)
        self.assertIn("automation_event_queue", sql)
        self.assertIn("tasks_kickoff", sql)  # source_code
        self.assertIn("old_note", sql)       # valore precedente nell'update
