"""Le impostazioni di Rilevazione Incidenti devono essere concedibili via ACL v2.

`_can_manage_settings` decideva con `is_superuser or is_legacy_admin(...)`, vero
solo per il ruolo "admin": nessun altro ruolo poteva essere abilitato dal modulo
permessi a gestire la configurazione del modulo.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import UtenteLegacy
from core.models import PermissionDefinition, Profile, RolePermissionGrant
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

from .acl_bootstrap import PERM_IMPOSTAZIONI_MANAGE, bootstrap_rilevazione_incidenti_acl_endpoints
from .views import _can_manage_settings

User = get_user_model()

RUOLO_DIREZIONE_ID = 7
RUOLO_ADMIN_ID = 1


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RilevazioneImpostazioniAclTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, 'direzione')", [RUOLO_DIREZIONE_ID])
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, 'admin')", [RUOLO_ADMIN_ID])
        bootstrap_rilevazione_incidenti_acl_endpoints(force=True)
        self.user = self._make_user("rilev-direzione", "direzione", RUOLO_DIREZIONE_ID)
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
        request = self.factory.get("/rilevazione-incidenti/impostazioni/")
        request.user = user or self.user
        return request

    def _grant(self, enabled=True):
        RolePermissionGrant.objects.update_or_create(
            legacy_role_id=RUOLO_DIREZIONE_ID, permission_id=PERM_IMPOSTAZIONI_MANAGE,
            defaults={"enabled": enabled},
        )
        cache.clear()
        bump_legacy_cache_version()

    def test_bootstrap_registra_il_permesso(self):
        self.assertTrue(
            PermissionDefinition.objects.filter(code=PERM_IMPOSTAZIONI_MANAGE, is_active=True).exists()
        )

    def test_grant_canonico_abilita_le_impostazioni(self):
        self._grant()

        self.assertTrue(_can_manage_settings(self._request()))

    def test_senza_grant_impostazioni_negate(self):
        self.assertFalse(_can_manage_settings(self._request()))

    def test_admin_legacy_resta_ammesso(self):
        admin_user = self._make_user("rilev-admin", "admin", RUOLO_ADMIN_ID)
        cache.clear()
        bump_legacy_cache_version()

        self.assertTrue(_can_manage_settings(self._request(admin_user)))

    def test_superuser_resta_ammesso(self):
        su = User.objects.create_superuser("rilev-su", "rilev-su@example.local", "pass12345")

        self.assertTrue(_can_manage_settings(self._request(su)))
