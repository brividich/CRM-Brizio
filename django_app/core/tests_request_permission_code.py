"""Helper condiviso: "questa request ha il permesso canonico X?".

Nasce per togliere di mezzo la duplicazione del cancello ACL nei moduli che
finora decidevano con `is_superuser or is_legacy_admin(...)`. `is_legacy_admin`
è vero solo per i ruoli il cui nome è in PORTAL_ADMIN_ROLE_NAMES (default
`{"admin"}`, mai valorizzato in alcun settings): quei cancelli erano di fatto
non configurabili dal modulo permessi.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase

from core.acl_v2 import request_has_permission_code
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import UtenteLegacy
from core.models import PermissionDefinition, Profile, RolePermissionGrant
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

User = get_user_model()

PERM = "core.test_only.use"
RUOLO_ID = 9


class RequestHasPermissionCodeTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, 'direzione')", [RUOLO_ID])

        PermissionDefinition.objects.create(
            code=PERM, label="Test", module="core", is_active=True,
        )
        self.user = User.objects.create_user(username="perm-user", password="pass12345")
        legacy = UtenteLegacy.objects.create(
            nome="Perm User", email="perm@example.local", password="x",
            ruolo="direzione", ruolo_id=RUOLO_ID, attivo=True,
            deve_cambiare_password=False,
        )
        Profile.objects.create(
            user=self.user, legacy_user_id=legacy.id,
            legacy_ruolo_id=legacy.ruolo_id, legacy_ruolo=legacy.ruolo,
        )
        self.factory = RequestFactory()
        bump_legacy_cache_version()

    def _request(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def test_ruolo_con_grant_e_ammesso(self):
        RolePermissionGrant.objects.create(
            legacy_role_id=RUOLO_ID, permission_id=PERM, enabled=True,
        )
        cache.clear()
        bump_legacy_cache_version()

        self.assertTrue(request_has_permission_code(self._request(self.user), PERM))

    def test_ruolo_senza_grant_e_negato(self):
        self.assertFalse(request_has_permission_code(self._request(self.user), PERM))

    def test_superuser_passa_sempre(self):
        su = User.objects.create_superuser("perm-su", "perm-su@example.local", "pass12345")

        self.assertTrue(request_has_permission_code(self._request(su), PERM))

    def test_permesso_inesistente_e_negato_non_esplode(self):
        self.assertFalse(
            request_has_permission_code(self._request(self.user), "core.non.esiste")
        )

    def test_utente_anonimo_negato(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(request_has_permission_code(self._request(AnonymousUser()), PERM))
