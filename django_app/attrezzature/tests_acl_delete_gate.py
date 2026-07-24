"""Il permesso canonico `attrezzature.attrezzature.delete` deve contare davvero.

Il permesso è registrato dal bootstrap del modulo fin dall'inizio ed è
concedibile per ruolo da /admin-portale/acl-canonico/, ma il gate
`_can_delete_attrezzature` lo ignorava: decideva con
`is_superuser or is_legacy_admin(...)`, vero solo per il ruolo "admin".
Concedere il permesso in ACL non aveva alcun effetto.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import UtenteLegacy
from core.models import PermissionDefinition, Profile, RolePermissionGrant
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

from .views import _can_delete_attrezzature

User = get_user_model()

PERM_DELETE = "attrezzature.attrezzature.delete"
RUOLO_DIREZIONE_ID = 7
RUOLO_ADMIN_ID = 1


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AttrezzatureDeleteGateAclTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, 'direzione')", [RUOLO_DIREZIONE_ID])
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, 'admin')", [RUOLO_ADMIN_ID])
        PermissionDefinition.objects.get_or_create(
            code=PERM_DELETE,
            defaults={"label": "Elimina attrezzature", "module": "attrezzature", "is_active": True},
        )
        self.user = self._make_user("attr-direzione", "direzione", RUOLO_DIREZIONE_ID)
        self.factory = RequestFactory()
        bump_legacy_cache_version()

    def _make_user(self, username, ruolo, ruolo_id):
        user = User.objects.create_user(username=username, password="pass12345")
        legacy = UtenteLegacy.objects.create(
            nome=username, email=f"{username}@example.local", password="x",
            ruolo=ruolo, ruolo_id=ruolo_id, attivo=True, deve_cambiare_password=False,
        )
        Profile.objects.create(
            user=user, legacy_user_id=legacy.id,
            legacy_ruolo_id=legacy.ruolo_id, legacy_ruolo=legacy.ruolo,
        )
        return user

    def _request(self, user=None):
        request = self.factory.get("/attrezzature/")
        request.user = user or self.user
        return request

    def _grant(self, enabled=True, role_id=RUOLO_DIREZIONE_ID):
        RolePermissionGrant.objects.update_or_create(
            legacy_role_id=role_id, permission_id=PERM_DELETE,
            defaults={"enabled": enabled},
        )
        cache.clear()
        bump_legacy_cache_version()

    def test_grant_canonico_abilita_eliminazione(self):
        self._grant()

        self.assertTrue(_can_delete_attrezzature(self._request()))

    def test_senza_grant_eliminazione_negata(self):
        self.assertFalse(_can_delete_attrezzature(self._request()))

    def test_grant_disabilitato_non_abilita(self):
        self._grant(enabled=False)

        self.assertFalse(_can_delete_attrezzature(self._request()))

    def test_admin_legacy_resta_ammesso(self):
        admin_user = self._make_user("attr-admin", "admin", RUOLO_ADMIN_ID)
        cache.clear()
        bump_legacy_cache_version()

        self.assertTrue(_can_delete_attrezzature(self._request(admin_user)))

    def test_superuser_resta_ammesso(self):
        su = User.objects.create_superuser("attr-su", "attr-su@example.local", "pass12345")

        self.assertTrue(_can_delete_attrezzature(self._request(su)))
