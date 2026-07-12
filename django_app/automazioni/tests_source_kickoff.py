from django.test import SimpleTestCase

from automazioni.source_registry import get_source_definition


class KickoffSourceTests(SimpleTestCase):
    def test_kickoff_source_registered(self):
        definition = get_source_definition("tasks_kickoff")
        self.assertIsNotNone(definition)
        self.assertEqual(definition["table_name"], "tasks_kickoffmeeting")
        self.assertEqual(definition["pk_field"], "id")
        field_names = {f["name"] for f in definition["fields"]}
        self.assertTrue({"id", "numero", "note", "project_id"} <= field_names)
