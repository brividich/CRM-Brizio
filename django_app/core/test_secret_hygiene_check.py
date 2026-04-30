from __future__ import annotations

from django.test import SimpleTestCase

from core.management.commands.secret_hygiene_check import _is_sensitive_path, _scan_content


class SecretHygieneCheckTests(SimpleTestCase):
    def test_env_example_placeholders_are_allowed(self):
        findings = _scan_content(
            "django_app/.env.example",
            "\n".join(
                [
                    "DJANGO_SECRET_KEY=CHANGE_ME",
                    "GRAPH_CLIENT_SECRET=<GRAPH_CLIENT_SECRET>",
                    "EMAIL_HOST_PASSWORD=",
                ]
            ),
        )

        self.assertEqual(findings, [])

    def test_env_example_real_graph_id_is_reported(self):
        findings = _scan_content(
            "django_app/.env.example",
            "GRAPH_LIST_ID_RENTRI=7Bbfc2d40b-f679-4bfb-a4b4-ccd122232027",
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "MEDIUM")
        self.assertEqual(findings[0].rule, "graph_id_in_example")

    def test_real_secret_assignment_in_env_is_reported(self):
        findings = _scan_content(
            "django_app/.env",
            "GRAPH_CLIENT_SECRET=real-client-secret-value",
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "HIGH")
        self.assertEqual(findings[0].rule, "sensitive_assignment")

    def test_python_token_variables_are_not_reported_as_assignments(self):
        findings = _scan_content(
            "django_app/example.py",
            'token = str(file_id or "").strip()',
        )

        self.assertEqual(findings, [])

    def test_runtime_env_path_is_sensitive_but_example_is_allowed(self):
        self.assertTrue(_is_sensitive_path("django_app/.env"))
        self.assertFalse(_is_sensitive_path("django_app/.env.example"))
