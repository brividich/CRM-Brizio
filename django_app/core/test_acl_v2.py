from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings

from core.acl_v2 import resolve_acl_access, validate_permission_code
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Pulsante, UtenteLegacy
from core.middleware import ACLMiddleware
from core.models import (
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserOnboarding,
    UserPermissionGrant,
)

User = get_user_model()


def _ensure_legacy_acl_tables() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ruoli (
                    id INTEGER PRIMARY KEY,
                    nome VARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS utenti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome VARCHAR(200) NOT NULL,
                    email VARCHAR(200) NULL,
                    password VARCHAR(500) NOT NULL,
                    ruolo VARCHAR(100) NULL,
                    attivo INTEGER NOT NULL DEFAULT 1,
                    deve_cambiare_password INTEGER NOT NULL DEFAULT 0,
                    ruolo_id INTEGER NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pulsanti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codice VARCHAR(100) NOT NULL,
                    nome_visibile VARCHAR(200) NULL,
                    icona VARCHAR(20) NULL,
                    modulo VARCHAR(100) NOT NULL,
                    url VARCHAR(500) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS permessi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    modulo VARCHAR(100) NOT NULL,
                    azione VARCHAR(100) NOT NULL,
                    ruolo_id INTEGER NOT NULL,
                    consentito INTEGER NULL,
                    can_view INTEGER NULL,
                    can_edit INTEGER NULL,
                    can_delete INTEGER NULL,
                    can_approve INTEGER NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('ruoli', 'U') IS NULL
                CREATE TABLE ruoli (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('utenti', 'U') IS NULL
                CREATE TABLE utenti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    nome NVARCHAR(200) NOT NULL,
                    email NVARCHAR(200) NULL,
                    password NVARCHAR(500) NOT NULL,
                    ruolo NVARCHAR(100) NULL,
                    attivo BIT NOT NULL DEFAULT 1,
                    deve_cambiare_password BIT NOT NULL DEFAULT 0,
                    ruolo_id INT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('pulsanti', 'U') IS NULL
                CREATE TABLE pulsanti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    codice NVARCHAR(100) NOT NULL,
                    nome_visibile NVARCHAR(200) NULL,
                    icona NVARCHAR(20) NULL,
                    modulo NVARCHAR(100) NOT NULL,
                    url NVARCHAR(500) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('permessi', 'U') IS NULL
                CREATE TABLE permessi (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    modulo NVARCHAR(100) NOT NULL,
                    azione NVARCHAR(100) NOT NULL,
                    ruolo_id INT NOT NULL,
                    consentito INT NULL,
                    can_view INT NULL,
                    can_edit INT NULL,
                    can_delete INT NULL,
                    can_approve INT NULL
                )
                """
            )


def _clear_legacy_acl_tables() -> None:
    with connection.cursor() as cursor:
        for table_name in ("permessi", "pulsanti", "utenti", "ruoli"):
            cursor.execute(f"DELETE FROM {table_name}")


def _attach_session(request) -> None:
    middleware = SessionMiddleware(lambda req: HttpResponse("ok"))
    middleware.process_request(request)
    request.session.save()


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class ACLV2ResolverTests(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (1, 'admin')")
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")

        self.user = User.objects.create_user(username="acl-v2-user", password="pass12345")
        self.legacy_user = UtenteLegacy.objects.create(
            nome="Mario Rossi",
            email="mario.rossi@example.local",
            password="x",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )
        Profile.objects.create(
            user=self.user,
            legacy_user_id=self.legacy_user.id,
            legacy_ruolo_id=self.legacy_user.ruolo_id,
            legacy_ruolo=self.legacy_user.ruolo,
        )

    def _refresh_legacy_cache(self):
        cache.clear()
        bump_legacy_cache_version()

    def _create_canonical_binding(self, *, permission_code: str = "core.profilo.view", enabled: bool = True):
        PermissionDefinition.objects.create(
            code=permission_code,
            label="Profilo utente",
            module="core",
            description="Permesso test profilo",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="profilo",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id=permission_code,
            source_app="core",
            note="test",
            priority=100,
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=6,
            permission_id=permission_code,
            enabled=enabled,
        )
        return permission_code

    def test_route_with_canonical_binding_and_role_grant_is_allowed(self):
        self._create_canonical_binding(enabled=True)

        decision = resolve_acl_access(path="/profilo/", legacy_user=self.legacy_user, django_user=self.user)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertTrue(decision["canonical"]["binding_found"])
        self.assertEqual(decision["canonical"]["effective_level"], "role_grant")

    def test_route_with_canonical_binding_but_role_denied_is_blocked(self):
        self._create_canonical_binding(enabled=False)

        decision = resolve_acl_access(path="/profilo/", legacy_user=self.legacy_user, django_user=self.user)

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertEqual(decision["canonical"]["effective_level"], "role_grant")
        self.assertIsNone(decision["legacy_fallback"])

    def test_route_with_canonical_binding_and_missing_role_grant_is_blocked(self):
        PermissionDefinition.objects.create(
            code="core.profilo.view",
            label="Profilo utente",
            module="core",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="profilo",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="core.profilo.view",
            source_app="core",
            is_active=True,
        )

        decision = resolve_acl_access(path="/profilo/", legacy_user=self.legacy_user, django_user=self.user)

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertFalse(decision["canonical"]["role_grant"]["exists"])

    def test_imported_legacy_permission_binding_uses_legacy_permesso_when_role_grant_missing(self):
        PermissionDefinition.objects.create(
            code="legacy.dashboard.view_dashboard",
            label="Dashboard legacy",
            module="dashboard",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="dashboard_home",
            path_pattern="/dashboard",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="legacy.dashboard.view_dashboard",
            source_app="dashboard",
            is_active=True,
        )
        Permesso.objects.create(
            ruolo_id=6,
            modulo="dashboard",
            azione="view_dashboard",
            consentito=1,
            can_view=1,
        )

        decision = resolve_acl_access(path="/dashboard", legacy_user=self.legacy_user, django_user=self.user)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertEqual(decision["canonical"]["effective_level"], "legacy_permesso")
        self.assertTrue(decision["canonical"]["legacy_compat"]["enabled"])

    def test_imported_legacy_permission_explicit_canonical_deny_wins_over_legacy_permesso(self):
        PermissionDefinition.objects.create(
            code="legacy.dashboard.view_dashboard",
            label="Dashboard legacy",
            module="dashboard",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="dashboard_home",
            path_pattern="/dashboard",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="legacy.dashboard.view_dashboard",
            source_app="dashboard",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=6,
            permission_id="legacy.dashboard.view_dashboard",
            enabled=False,
        )
        Permesso.objects.create(
            ruolo_id=6,
            modulo="dashboard",
            azione="view_dashboard",
            consentito=1,
            can_view=1,
        )

        decision = resolve_acl_access(path="/dashboard", legacy_user=self.legacy_user, django_user=self.user)

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["canonical"]["effective_level"], "role_grant")
        self.assertIsNone(decision["canonical"]["legacy_compat"])

    def test_anomalie_menu_allows_operational_roles_even_without_container_grant(self):
        PermissionDefinition.objects.create(
            code="legacy.dashboard.dashboard_anomalie_menu",
            label="Menu anomalie",
            module="dashboard",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="anomalie_menu",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="legacy.dashboard.dashboard_anomalie_menu",
            source_app="dashboard",
            is_active=True,
        )
        Permesso.objects.create(
            modulo="anomalie",
            azione="anomalie_aperte",
            ruolo_id=6,
            can_view=1,
            consentito=1,
        )
        self._refresh_legacy_cache()

        decision = resolve_acl_access(path="/anomalie-menu", legacy_user=self.legacy_user, django_user=self.user)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["decision_source"], "compat_anomalie_menu")
        self.assertTrue(decision["canonical"]["binding_found"])
        self.assertIn("anomalie_aperte", decision["reason"])

    def test_anomalie_menu_still_denies_when_no_operational_permission_exists(self):
        PermissionDefinition.objects.create(
            code="legacy.dashboard.dashboard_anomalie_menu",
            label="Menu anomalie",
            module="dashboard",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="anomalie_menu",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="legacy.dashboard.dashboard_anomalie_menu",
            source_app="dashboard",
            is_active=True,
        )
        self._refresh_legacy_cache()

        decision = resolve_acl_access(path="/anomalie-menu", legacy_user=self.legacy_user, django_user=self.user)

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertFalse(decision["canonical"]["role_grant"]["exists"])

    def test_user_override_canonical_has_precedence_over_role_grant(self):
        permission_code = self._create_canonical_binding(enabled=False)
        UserPermissionGrant.objects.create(
            legacy_user_id=self.legacy_user.id,
            permission_id=permission_code,
            enabled=True,
        )

        decision = resolve_acl_access(path="/profilo/", legacy_user=self.legacy_user, django_user=self.user)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertEqual(decision["canonical"]["effective_level"], "user_override")

    def test_user_override_deny_has_precedence_over_role_allow(self):
        permission_code = self._create_canonical_binding(enabled=True)
        UserPermissionGrant.objects.create(
            legacy_user_id=self.legacy_user.id,
            permission_id=permission_code,
            enabled=False,
        )

        decision = resolve_acl_access(path="/profilo/", legacy_user=self.legacy_user, django_user=self.user)

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertEqual(decision["canonical"]["effective_level"], "user_override")

    def test_fallback_legacy_is_used_when_no_canonical_binding_exists(self):
        Pulsante.objects.create(
            codice="view_profile_legacy",
            nome_visibile="Profilo Legacy",
            icona="user",
            modulo="core",
            url="/profilo/",
        )
        Permesso.objects.create(
            modulo="core",
            azione="view_profile_legacy",
            ruolo_id=6,
            can_view=1,
            consentito=1,
        )
        self._refresh_legacy_cache()

        decision = resolve_acl_access(path="/profilo/", legacy_user=self.legacy_user, django_user=self.user)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["decision_source"], "legacy_fallback")
        self.assertIsNotNone(decision["legacy_fallback"])

    def test_canonical_binding_takes_precedence_over_legacy_allow(self):
        self._create_canonical_binding(enabled=False)
        Pulsante.objects.create(
            codice="view_profile_legacy",
            nome_visibile="Profilo Legacy",
            icona="user",
            modulo="core",
            url="/profilo/",
        )
        Permesso.objects.create(
            modulo="core",
            azione="view_profile_legacy",
            ruolo_id=6,
            can_view=1,
            consentito=1,
        )
        self._refresh_legacy_cache()

        decision = resolve_acl_access(path="/profilo/", legacy_user=self.legacy_user, django_user=self.user)

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertIsNone(decision["legacy_fallback"])

    def test_legacy_admin_bypass_is_always_allowed(self):
        legacy_admin = UtenteLegacy.objects.create(
            nome="Admin Legacy",
            email="admin.legacy@example.local",
            password="x",
            ruolo="admin",
            ruolo_id=1,
            attivo=True,
            deve_cambiare_password=False,
        )

        decision = resolve_acl_access(path="/profilo/", legacy_user=legacy_admin, django_user=self.user)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["decision_source"], "legacy_admin_bypass")

    def test_django_superuser_bypass_is_always_allowed(self):
        superuser = User.objects.create_superuser(
            username="acl-v2-super",
            email="acl-v2-super@example.local",
            password="pass12345",
        )
        decision = resolve_acl_access(path="/profilo/", legacy_user=self.legacy_user, django_user=superuser)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["decision_source"], "superuser_bypass")

    def test_route_without_binding_and_without_legacy_coverage_is_denied(self):
        decision = resolve_acl_access(path="/route-senza-copertura/", legacy_user=self.legacy_user, django_user=self.user)

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["decision_source"], "legacy_fallback")
        self.assertEqual(
            (decision["legacy_fallback"] or {}).get("reason_code"),
            "no_pulsante_match",
        )

    def test_prefix_path_binding_supports_dynamic_path(self):
        PermissionDefinition.objects.create(
            code="core.profilo.view",
            label="Profilo utente",
            module="core",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="",
            path_pattern="/profilo",
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission_id="core.profilo.view",
            source_app="core",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=6,
            permission_id="core.profilo.view",
            enabled=True,
        )

        decision = resolve_acl_access(path="/profilo/123", legacy_user=self.legacy_user, django_user=self.user)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["decision_source"], "canonical")
        self.assertEqual(decision["canonical"]["binding"]["matched_by"], "path_pattern")

    def test_permission_code_validation_rejects_non_canonical_format(self):
        ok, _ = validate_permission_code("Profilo.Legacy")
        self.assertFalse(ok)


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class ACLV2MiddlewareIntegrationTests(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (1, 'admin')")
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")

        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="acl-v2-middleware", password="pass12345")
        self.legacy_user = UtenteLegacy.objects.create(
            nome="Middleware User",
            email="middleware.user@example.local",
            password="x",
            ruolo="utente",
            ruolo_id=6,
            attivo=True,
            deve_cambiare_password=False,
        )
        Profile.objects.create(
            user=self.user,
            legacy_user_id=self.legacy_user.id,
            legacy_ruolo_id=self.legacy_user.ruolo_id,
            legacy_ruolo=self.legacy_user.ruolo,
        )
        UserOnboarding.objects.create(user=self.user, completed=True)

    def test_exempt_path_bypasses_acl_even_without_authentication(self):
        middleware = ACLMiddleware(lambda request: HttpResponse("ok", status=200))
        request = self.factory.get("/health")
        _attach_session(request)
        request.user = AnonymousUser()

        response = middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_canonical_deny_returns_forbidden_response(self):
        PermissionDefinition.objects.create(
            code="admin_portale.users.view",
            label="Utenti portale",
            module="admin_portale",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="admin_portale:utenti_list",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id="admin_portale.users.view",
            source_app="admin_portale",
            is_active=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=6,
            permission_id="admin_portale.users.view",
            enabled=False,
        )
        middleware = ACLMiddleware(lambda request: HttpResponse("ok", status=200))
        request = self.factory.get("/admin-portale/utenti/")
        _attach_session(request)
        request.user = self.user

        response = middleware(request)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(request.acl_decision["decision_source"], "canonical")
        self.assertFalse(request.acl_decision["allowed"])
