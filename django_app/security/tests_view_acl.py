"""Il cancello di lettura del SOC deve riconoscere l'ACL v2 del portale.

In produzione un amministratore del portale (non `is_staff`) superava l'ACLMiddleware
su /soc/ e poi riceveva «Accesso negato» dalle view (Caselle mail, Inbox, guida):
`can_view_security_center` riconosceva solo i titoli del progetto standalone.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import UtenteLegacy
from core.models import PermissionDefinition, Profile, RolePermissionGrant
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables
from security.permissions import SECURITY_VIEW_PERMISSION_CODE, can_view_security_center

User = get_user_model()


class SecurityViewGateAclV2Test(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (1, 'admin')")
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (6, 'utente')")
        PermissionDefinition.objects.create(
            code=SECURITY_VIEW_PERMISSION_CODE, label="Security Center", module="security", is_active=True,
        )
        bump_legacy_cache_version()

    def _user(self, username, ruolo, ruolo_id):
        user = User.objects.create_user(username=username, password="pass12345")
        legacy = UtenteLegacy.objects.create(
            nome=username, email=f"{username}@example.local", password="x",
            ruolo=ruolo, ruolo_id=ruolo_id, attivo=True, deve_cambiare_password=False,
        )
        Profile.objects.create(user=user, legacy_user_id=legacy.id, legacy_ruolo_id=ruolo_id, legacy_ruolo=ruolo)
        cache.clear()
        bump_legacy_cache_version()
        return user

    def test_admin_del_portale_non_staff_entra(self):
        admin = self._user("admin.portale", "admin", 1)
        self.assertFalse(admin.is_staff)
        self.assertTrue(can_view_security_center(admin))

    def test_utente_con_grant_dashboard_entra(self):
        user = self._user("tecnico.it", "utente", 6)
        RolePermissionGrant.objects.create(legacy_role_id=6, permission_id=SECURITY_VIEW_PERMISSION_CODE, enabled=True)
        cache.clear()
        bump_legacy_cache_version()
        self.assertTrue(can_view_security_center(user))

    def test_utente_senza_grant_resta_fuori(self):
        user = self._user("operaio", "utente", 6)
        self.assertFalse(can_view_security_center(user))

    def test_anonimo_negato(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(can_view_security_center(AnonymousUser()))

    def test_view_caselle_mail_non_risponde_accesso_negato_all_admin(self):
        """La view stessa (il middleware e' coperto dai test ACL del core)."""
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        from security.views import admin_mailbox_sources_list

        admin = self._user("admin.pagina", "admin", 1)
        request = RequestFactory().get("/soc/admin/mailbox/")
        request.user = admin
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        response = admin_mailbox_sources_list(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Accesso negato", response.content)
