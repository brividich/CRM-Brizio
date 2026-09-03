from __future__ import annotations

import importlib
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models as django_models
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from attrezzature.services.kickoff_integration import (
    normalize_part_number as normalize_attrezzature_part_number,
)

from .identity import normalize_client_name, normalize_part_number
from .models import Project
from .tests import (
    TasksBaseTestCase,
    _create_user_with_legacy,
    _ensure_role,
    _grant_role_actions,
)

User = get_user_model()


class ProjectIdentityNormalizerTests(SimpleTestCase):
    def test_part_number_normalizer_matches_attrezzature_on_edge_cases(self):
        cases = (
            None,
            "",
            "   ",
            "pn-001",
            "  4a-77 821 ",
            "AA\t  99",
            "già-10",
            "  mixed\nCASE  value  ",
            "ß-12",
        )

        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_part_number(value),
                    normalize_attrezzature_part_number(value),
                )

    def test_client_normalizer_preserves_case_and_collapses_whitespace(self):
        self.assertEqual(normalize_client_name("  Cliente\t Alfa  S.p.A. "), "Cliente Alfa S.p.A.")
        self.assertEqual(normalize_client_name(None), "")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ProjectIdentityPersistenceTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="identity-owner", password="pass12345")

    def test_project_save_normalizes_identity_on_create_and_update(self):
        project = Project.objects.create(
            name="",
            client_name="  Cliente   Alfa  ",
            part_number="  4a-77\t821 ",
            created_by=self.user,
        )

        self.assertEqual(project.client_name, "Cliente Alfa")
        self.assertEqual(project.part_number, "4A-77 821")

        project.client_name = " cliente   Beta srl "
        project.part_number = " pn-  900 b "
        project.save()
        project.refresh_from_db()

        self.assertEqual(project.client_name, "cliente Beta srl")
        self.assertEqual(project.part_number, "PN- 900 B")

    def test_kickoff_number_retry_still_runs_after_integrity_error(self):
        project = Project(
            name="",
            client_name="  Cliente Retry ",
            part_number=" pn-retry ",
            created_by=self.user,
        )
        original_model_save = django_models.Model.save
        calls = {"count": 0}

        def flaky_model_save(instance, *args, **kwargs):
            if instance is project:
                calls["count"] += 1
                if calls["count"] == 1:
                    raise IntegrityError("simulated kickoff collision")
            return original_model_save(instance, *args, **kwargs)

        with patch("tasks.models._next_kickoff_number", side_effect=[101, 102]), patch.object(
            django_models.Model,
            "save",
            new=flaky_model_save,
        ):
            project.save()

        self.assertEqual(calls["count"], 2)
        self.assertEqual(project.kickoff_number, 102)
        self.assertEqual(project.name, "KICK-OFF 102")
        self.assertEqual(project.client_name, "Cliente Retry")
        self.assertEqual(project.part_number, "PN-RETRY")

    def test_data_migration_is_idempotent_and_preserves_kickoff_numbers(self):
        first = Project.objects.create(
            name="",
            client_name="Cliente Uno",
            part_number="PN-10",
            revisione="A",
            versione="1",
            created_by=self.user,
        )
        second = Project.objects.create(
            name="",
            client_name="Cliente Due",
            part_number="PN-20",
            revisione="B",
            versione="2",
            created_by=self.user,
        )
        kickoff_numbers = {
            first.id: first.kickoff_number,
            second.id: second.kickoff_number,
        }
        Project.objects.filter(pk=first.pk).update(
            client_name="  Cliente   Uno  ",
            part_number=" pn-  10 ",
        )
        Project.objects.filter(pk=second.pk).update(
            client_name=" Cliente\tDue ",
            part_number=" pn-20 ",
        )

        migration = importlib.import_module("tasks.migrations.0035_normalize_project_identity")
        first_output = io.StringIO()
        with redirect_stdout(first_output):
            migration.normalize_project_identity(django_apps, None)

        first.refresh_from_db()
        second.refresh_from_db()
        state_after_first_run = list(
            Project.objects.order_by("id").values_list(
                "id", "client_name", "part_number", "kickoff_number"
            )
        )
        self.assertEqual(first.client_name, "Cliente Uno")
        self.assertEqual(first.part_number, "PN- 10")
        self.assertEqual(second.client_name, "Cliente Due")
        self.assertEqual(second.part_number, "PN-20")
        self.assertEqual(
            {first.id: first.kickoff_number, second.id: second.kickoff_number},
            kickoff_numbers,
        )
        self.assertIn("normalizzate: 2", first_output.getvalue())

        second_output = io.StringIO()
        with redirect_stdout(second_output):
            migration.normalize_project_identity(django_apps, None)

        self.assertEqual(
            list(
                Project.objects.order_by("id").values_list(
                    "id", "client_name", "part_number", "kickoff_number"
                )
            ),
            state_after_first_run,
        )
        self.assertIn("normalizzate: 0", second_output.getvalue())

    def test_data_migration_reports_identity_collisions_without_merging(self):
        first = Project.objects.create(
            name="",
            client_name="Cliente Uno",
            part_number="PN-COLLISION",
            revisione="A",
            versione="1",
            created_by=self.user,
        )
        second = Project.objects.create(
            name="",
            client_name="Cliente Due",
            part_number="PN-OTHER",
            revisione="A",
            versione="1",
            created_by=self.user,
        )
        Project.objects.filter(pk=first.pk).update(part_number=" pn-collision ")
        Project.objects.filter(pk=second.pk).update(part_number=" PN-COLLISION ")

        migration = importlib.import_module("tasks.migrations.0035_normalize_project_identity")
        output = io.StringIO()
        with redirect_stdout(output):
            migration.normalize_project_identity(django_apps, None)

        self.assertEqual(Project.objects.filter(pk__in=[first.pk, second.pk]).count(), 2)
        self.assertIn("Collisione identita'", output.getvalue())
        self.assertIn(f"project_ids=[{first.pk}, {second.pk}]", output.getvalue())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ProjectIdentitySuggestTests(TasksBaseTestCase):
    def setUp(self):
        super().setUp()
        _ensure_role(2, "utente")
        _ensure_role(3, "bloccato")
        _grant_role_actions(2, ["tasks_view", "tasks_create"])
        self._refresh_acl_cache()
        self.user = _create_user_with_legacy(
            username="identity-visible",
            legacy_user_id=9101,
            role_id=2,
            role_name="utente",
        )
        self.other = _create_user_with_legacy(
            username="identity-hidden",
            legacy_user_id=9102,
            role_id=2,
            role_name="utente",
        )
        self.blocked = _create_user_with_legacy(
            username="identity-blocked",
            legacy_user_id=9103,
            role_id=3,
            role_name="bloccato",
        )
        Project.objects.create(
            name="",
            client_name="Cliente Visibile",
            part_number="PN-VIS-01",
            created_by=self.user,
        )
        Project.objects.create(
            name="",
            client_name="Cliente Riservato",
            part_number="PN-HIDDEN-01",
            created_by=self.other,
        )

    def _json_headers(self):
        return {
            "HTTP_ACCEPT": "application/json",
            "HTTP_X_REQUESTED_WITH": "XMLHttpRequest",
        }

    def test_identity_suggest_respects_project_scope(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("tasks:identity_suggest"),
            {"field": "client", "q": "Cliente"},
            **self._json_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"values": ["Cliente Visibile"]})

    def test_identity_suggest_limits_results_to_twenty(self):
        for index in range(25):
            Project.objects.create(
                name="",
                client_name=f"Suggerimento {index:02d}",
                part_number=f"PN-SUG-{index:02d}",
                created_by=self.user,
            )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("tasks:identity_suggest"),
            {"field": "part_number", "q": "pn-sug"},
            **self._json_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["values"]), 20)
        self.assertEqual(response.json()["values"], sorted(response.json()["values"]))

    def test_identity_suggest_returns_json_403_for_forbidden_user(self):
        self.client.force_login(self.blocked)

        response = self.client.get(
            reverse("tasks:identity_suggest"),
            {"field": "client", "q": "C"},
            **self._json_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["reason"], "forbidden")

    def test_identity_suggest_returns_json_401_when_unauthenticated(self):
        response = self.client.get(
            reverse("tasks:identity_suggest"),
            {"field": "client", "q": "C"},
            **self._json_headers(),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json()["reason"], "unauthenticated")

    def test_project_create_wires_remote_identity_datalists(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("tasks:project_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="project-client-datalist"')
        self.assertContains(response, 'id="project-part-number-datalist"')
        self.assertContains(response, reverse("tasks:identity_suggest"))
        self.assertContains(response, "window.portalReadJsonResponse")
