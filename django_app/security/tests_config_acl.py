"""Il gate della configurazione SOC deve riconoscere l'ACL v2, non solo `is_staff`.

Le viste di `/soc/admin/config/` sono gia' dietro `ACLMiddleware` con il binding
canonico `security.config.view`. Dentro, pero', chiamavano un secondo cancello
ereditato dal progetto standalone Security-Center-AI (`is_staff` o il permesso
Django `security.manage_security_configuration`), che l'ACL v2 non sa concedere:
un amministratore del portale — che il middleware fa passare — si vedeva negare
la pagina, e il permesso Django non era assegnato a nessun utente ne' gruppo.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.db import connection
from django.test import TestCase

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import UtenteLegacy
from core.models import PermissionDefinition, Profile, RolePermissionGrant
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables
from security.services.configuration import can_manage_security_config

SECURITY_CONFIG_PERMISSION_CODE = "security.config.view"

User = get_user_model()


class SecurityConfigGateAclV2Test(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")

        self.user = User.objects.create_user(username="soc-config-user", password="pass12345")
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
        PermissionDefinition.objects.create(
            code=SECURITY_CONFIG_PERMISSION_CODE,
            label="Configurazione Security Center",
            module="security",
            is_active=True,
        )
        bump_legacy_cache_version()

    def _grant_acl(self, enabled=True):
        RolePermissionGrant.objects.create(
            legacy_role_id=6,
            permission_id=SECURITY_CONFIG_PERMISSION_CODE,
            enabled=enabled,
        )
        cache.clear()
        bump_legacy_cache_version()

    def test_utente_con_grant_acl_v2_puo_gestire_la_configurazione(self):
        self._grant_acl(enabled=True)

        self.assertTrue(can_manage_security_config(self.user))

    def test_utente_senza_grant_acl_v2_resta_fuori(self):
        self.assertFalse(can_manage_security_config(self.user))

    def test_grant_acl_v2_disabilitato_non_apre_la_configurazione(self):
        self._grant_acl(enabled=False)

        self.assertFalse(can_manage_security_config(self.user))

    def test_permesso_django_storico_continua_a_valere(self):
        # Il cancello preesistente non viene sostituito, solo affiancato.
        perm = Permission.objects.get(codename="manage_security_configuration")
        self.user.user_permissions.add(perm)

        self.assertTrue(can_manage_security_config(User.objects.get(pk=self.user.pk)))

    def test_staff_continua_a_valere(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        self.assertTrue(can_manage_security_config(User.objects.get(pk=self.user.pk)))

    def test_utente_anonimo_negato(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(can_manage_security_config(AnonymousUser()))
