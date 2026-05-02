from __future__ import annotations

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.acl_v2 import resolve_acl_access
from core.legacy_models import Permesso, Pulsante, Ruolo, UtenteLegacy
from core.management.commands.seed_acl_uat import (
    BINDING_SEEDS,
    PERMISSION_SEEDS,
    ROLE_GRANT_SEEDS,
    ROLE_SEEDS,
    SEED_LEGACY_BUTTON_URL,
    SEED_MARKER,
    USER_OVERRIDE_SEEDS,
    USER_SEEDS,
)
from core.models import (
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserPermissionGrant,
)


User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class SeedAclUatCommandTests(TestCase):
    def _seed(self, *, reset: bool = False, stdout: StringIO | None = None):
        kwargs = {"verbosity": 0}
        if stdout is not None:
            kwargs["stdout"] = stdout
        if reset:
            call_command("seed_acl_uat", "--reset", **kwargs)
            return
        call_command("seed_acl_uat", **kwargs)

    def test_seed_command_is_idempotent(self):
        self._seed(reset=True)

        role_count_first = Ruolo.objects.filter(id__in=[row.id for row in ROLE_SEEDS]).count()
        permission_count_first = PermissionDefinition.objects.filter(
            code__in=[row.code for row in PERMISSION_SEEDS]
        ).count()
        binding_count_first = RoutePermissionBinding.objects.filter(note__icontains=SEED_MARKER).count()
        grant_count_first = RolePermissionGrant.objects.filter(
            legacy_role_id__in=[row.id for row in ROLE_SEEDS],
            permission_id__in=[row.code for row in PERMISSION_SEEDS],
        ).count()

        self._seed()

        role_count_second = Ruolo.objects.filter(id__in=[row.id for row in ROLE_SEEDS]).count()
        permission_count_second = PermissionDefinition.objects.filter(
            code__in=[row.code for row in PERMISSION_SEEDS]
        ).count()
        binding_count_second = RoutePermissionBinding.objects.filter(note__icontains=SEED_MARKER).count()
        grant_count_second = RolePermissionGrant.objects.filter(
            legacy_role_id__in=[row.id for row in ROLE_SEEDS],
            permission_id__in=[row.code for row in PERMISSION_SEEDS],
        ).count()

        self.assertEqual(role_count_first, len(ROLE_SEEDS))
        self.assertEqual(role_count_second, role_count_first)
        self.assertEqual(permission_count_first, len(PERMISSION_SEEDS))
        self.assertEqual(permission_count_second, permission_count_first)
        self.assertEqual(binding_count_second, binding_count_first)
        self.assertEqual(grant_count_first, len(ROLE_GRANT_SEEDS))
        self.assertEqual(grant_count_second, grant_count_first)

    def test_seed_creates_expected_acl_entities(self):
        self._seed(reset=True)

        self.assertEqual(
            PermissionDefinition.objects.filter(code__in=[row.code for row in PERMISSION_SEEDS]).count(),
            len(PERMISSION_SEEDS),
        )
        self.assertEqual(
            RoutePermissionBinding.objects.filter(note__icontains=SEED_MARKER).count(),
            len(BINDING_SEEDS),
        )
        self.assertEqual(
            RolePermissionGrant.objects.filter(
                legacy_role_id__in=[row.id for row in ROLE_SEEDS],
                permission_id__in=[row.code for row in PERMISSION_SEEDS],
            ).count(),
            len(ROLE_GRANT_SEEDS),
        )
        legacy_seed_user_ids = list(
            UtenteLegacy.objects.filter(email__in=[row.email for row in USER_SEEDS]).values_list("id", flat=True)
        )
        self.assertEqual(
            UserPermissionGrant.objects.filter(
                legacy_user_id__in=legacy_seed_user_ids,
                permission_id__in=[row.permission_code for row in USER_OVERRIDE_SEEDS],
            ).count(),
            len(USER_OVERRIDE_SEEDS),
        )
        self.assertEqual(
            Profile.objects.filter(user__username__in=[row.username for row in USER_SEEDS]).count(),
            len(USER_SEEDS),
        )
        self.assertTrue(
            Pulsante.objects.filter(modulo="admin_portale", codice="uat_acl_nav_map").exists()
        )
        self.assertEqual(
            Permesso.objects.filter(modulo="admin_portale", azione="uat_acl_nav_map").count(),
            3,
        )

    def test_seed_runtime_scenarios_key_paths(self):
        self._seed(reset=True)
        by_username = {u.username: u for u in User.objects.filter(username__in=[row.username for row in USER_SEEDS])}
        by_email = {
            u.email: u
            for u in UtenteLegacy.objects.filter(email__in=[row.email for row in USER_SEEDS])
        }

        def decision(username: str, email: str, path: str) -> dict:
            return resolve_acl_access(
                path=path,
                legacy_user=by_email[email],
                django_user=by_username[username],
            )

        allow_profile = decision("uat.base1", "uat.base1@novicrom.local", "/profilo/")
        self.assertTrue(allow_profile["allowed"])
        self.assertEqual(allow_profile["decision_source"], "canonical")

        deny_workorders = decision("uat.base1", "uat.base1@novicrom.local", "/assets/workorders/")
        self.assertFalse(deny_workorders["allowed"])
        self.assertEqual(deny_workorders["decision_source"], "canonical")

        allow_override = decision("uat.override1", "uat.override1@novicrom.local", "/assets/workorders/view/1")
        self.assertTrue(allow_override["allowed"])
        self.assertEqual(allow_override["decision_source"], "canonical")
        self.assertEqual(
            ((allow_override["canonical"]["user_override"] or {}).get("exists")),
            True,
        )

        deny_override = decision("uat.base2", "uat.base2@novicrom.local", "/assets/lista/")
        self.assertFalse(deny_override["allowed"])
        self.assertEqual(deny_override["decision_source"], "canonical")

        legacy_allow = decision(
            "uat.resp1",
            "uat.resp1@novicrom.local",
            SEED_LEGACY_BUTTON_URL,
        )
        self.assertTrue(legacy_allow["allowed"])
        self.assertEqual(legacy_allow["decision_source"], "legacy_fallback")

        legacy_deny = decision(
            "uat.base1",
            "uat.base1@novicrom.local",
            SEED_LEGACY_BUTTON_URL,
        )
        self.assertFalse(legacy_deny["allowed"])
        self.assertEqual(legacy_deny["decision_source"], "legacy_fallback")

        superuser_bypass = decision("uat.admin1", "uat.admin1@novicrom.local", "/admin-portale/acl-canonico/")
        self.assertTrue(superuser_bypass["allowed"])
        self.assertEqual(superuser_bypass["decision_source"], "superuser_bypass")

    def test_seed_command_prints_validation_report(self):
        out = StringIO()
        self._seed(reset=True, stdout=out)
        report = out.getvalue()

        self.assertIn("ACL v2 UAT Seed Report", report)
        self.assertIn("Route sample coverage", report)
        self.assertIn("Scenari UAT runtime", report)
        self.assertIn("S01", report)
        self.assertIn("R01", report)
