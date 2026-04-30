from __future__ import annotations

import io
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import clear_url_caches, path

from core.management.commands.acl_coverage_report import build_acl_coverage
from core.models import PermissionDefinition, RoutePermissionBinding


def _view(_request):
    return HttpResponse("ok")


urlpatterns = [
    path("health/", _view, name="health"),
    path("login/", _view, name="login"),
    path("logout/", _view, name="logout"),
    path("bound/", _view, name="bound_route"),
    path("private/", _view, name="private_route"),
    path("items/<int:pk>/", _view, name="dynamic_route"),
]


@override_settings(
    ROOT_URLCONF=__name__,
    MIDDLEWARE_EXEMPT_PREFIXES=("/health", "/login", "/logout"),
)
class AclCoverageReportCommandTests(TestCase):
    def setUp(self):
        clear_url_caches()
        self.permission = PermissionDefinition.objects.create(
            code="core.bound.view",
            label="Bound route",
            module="core",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="bound_route",
            permission=self.permission,
            source_app="core",
            is_active=True,
        )

    def tearDown(self):
        clear_url_caches()

    def test_public_routes_are_excluded(self):
        report = build_acl_coverage()
        by_name = {route["name"]: route for route in report["routes"]}

        self.assertEqual(by_name["health"]["status"], "excluded")
        self.assertEqual(by_name["login"]["status"], "excluded")
        self.assertEqual(by_name["logout"]["status"], "excluded")

    def test_bound_route_uses_real_acl_binding_model(self):
        report = build_acl_coverage()
        by_name = {route["name"]: route for route in report["routes"]}

        bound = by_name["bound_route"]
        self.assertEqual(bound["status"], "bound")
        self.assertEqual(bound["permission_code"], "core.bound.view")
        self.assertEqual(bound["matched_by"], "route_name")
        self.assertTrue(bound["permission_active"])

    def test_fail_on_missing_raises_command_error(self):
        out = io.StringIO()

        with self.assertRaises(CommandError):
            call_command("acl_coverage_report", "--fail-on-missing", stdout=out)

        self.assertIn("private_route", out.getvalue())

    def test_max_missing_passes_when_missing_is_within_threshold(self):
        out = io.StringIO()

        call_command("acl_coverage_report", "--max-missing", "2", stdout=out)

        self.assertIn("Senza binding", out.getvalue())

    def test_max_missing_fails_when_missing_exceeds_threshold(self):
        out = io.StringIO()

        with self.assertRaises(CommandError):
            call_command("acl_coverage_report", "--max-missing", "1", stdout=out)

        self.assertIn("private_route", out.getvalue())

    def test_fail_on_missing_is_stricter_than_max_missing(self):
        out = io.StringIO()

        with self.assertRaises(CommandError):
            call_command("acl_coverage_report", "--fail-on-missing", "--max-missing", "99", stdout=out)

        self.assertIn("private_route", out.getvalue())

    def test_json_output_is_valid(self):
        out = io.StringIO()

        call_command("acl_coverage_report", "--format", "json", "--max-missing", "2", stdout=out)
        payload = json.loads(out.getvalue())

        self.assertIn("summary", payload)
        self.assertIn("routes", payload)
        self.assertGreaterEqual(payload["summary"]["missing"], 1)

    def test_dynamic_route_is_flagged_when_not_reversible_without_args(self):
        report = build_acl_coverage()
        by_name = {route["name"]: route for route in report["routes"]}

        dynamic = by_name["dynamic_route"]
        self.assertEqual(dynamic["status"], "missing")
        self.assertTrue(dynamic["is_dynamic"])
        self.assertFalse(dynamic["is_reversible"])
