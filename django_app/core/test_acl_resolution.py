"""Accessi negati: dal 403 alla decisione dell'amministratore, senza giri.

Si fissano quattro patti:

* un 403 viene registrato una volta per persona e permesso, e i tentativi si contano;
* la spiegazione dice chi blocca davvero, secondo la precedenza del resolver;
* "Consenti" / "Non consentire" scrivono solo il layer canonico, lasciano l'audit
  e **verificano l'esito** (consentire al ruolo non basta se un'eccezione nega);
* l'azione e' dell'amministratore reale, anche mentre impersona, e di nessun altro.
"""
from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.acl_resolution import describe_access, record_denial
from core.impersonation import IMPERSONATION_SESSION_KEY
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Ruolo, UtenteLegacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    AclDenialEvent,
    AuditLog,
    GroupPermissionGrant,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    UserOnboarding,
    UserPermissionGrant,
)
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

PERM = "admin_portale.users.view"
ROLE_ADMIN = 1
ROLE_USER = 6
PAGE = "/admin-portale/utenti/"


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False, ACL_STRICT_CANONICAL=True)
class AccessiNegatiTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()
        User = get_user_model()

        Ruolo.objects.create(id=ROLE_ADMIN, nome="admin")
        Ruolo.objects.create(id=ROLE_USER, nome="utente")

        self.admin_legacy = self._legacy("Amministratore", "admin@example.local", "admin", ROLE_ADMIN)
        self.admin = User.objects.create_user(
            username="acl-admin", password="pass12345", is_superuser=True, is_staff=True
        )
        Profile.objects.update_or_create(user=self.admin, defaults={"legacy_user_id": self.admin_legacy.id})

        self.target_legacy = self._legacy("Mario Rossi", "mario.rossi@example.local", "utente", ROLE_USER)
        self.other_legacy = self._legacy("Anna Bianchi", "anna.bianchi@example.local", "utente", ROLE_USER)
        self.target = User.objects.create_user(username="mario.rossi", password="pass12345")
        Profile.objects.update_or_create(
            user=self.target,
            defaults={"legacy_user_id": self.target_legacy.id, "legacy_ruolo_id": ROLE_USER, "legacy_ruolo": "utente"},
        )
        UserOnboarding.objects.create(user=self.target, completed=True)

        PermissionDefinition.objects.create(code=PERM, label="Admin Portale - Utenti", module="admin_portale")
        RoutePermissionBinding.objects.create(
            route_name="admin_portale:utenti_list",
            path_pattern="",
            match_strategy=RoutePermissionBinding.MATCH_EXACT,
            permission_id=PERM,
            source_app="admin_portale",
            is_active=True,
        )
        RolePermissionGrant.objects.create(legacy_role_id=ROLE_USER, permission_id=PERM, enabled=False)
        bump_legacy_cache_version()
        self.action_url = reverse("admin_portale:accessi_negati_azione")
        self.panel_url = reverse("admin_portale:accessi_negati")

    # ── helper ──────────────────────────────────────────────────────────

    @staticmethod
    def _legacy(nome, email, ruolo, ruolo_id):
        return UtenteLegacy.objects.create(
            nome=nome,
            email=email,
            password="x",
            ruolo=ruolo,
            ruolo_id=ruolo_id,
            attivo=True,
            deve_cambiare_password=False,
        )

    def _impersonate(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session[IMPERSONATION_SESSION_KEY] = {
            "original_user_id": self.admin.id,
            "original_legacy_user_id": self.admin_legacy.id,
            "target_user_id": self.target.id,
            "target_legacy_user_id": self.target_legacy.id,
            "started_at": "2026-09-15T10:00:00+00:00",
        }
        session.save()

    def _event(self, legacy_user, **extra):
        from django.utils import timezone

        return AclDenialEvent.objects.create(
            legacy_user_id=legacy_user.id,
            legacy_role_id=legacy_user.ruolo_id,
            dedup_key=f"perm:{PERM}",
            permission_code=PERM,
            path=PAGE,
            decision_source="canonical",
            last_seen_at=timezone.now(),
            **extra,
        )

    def _post(self, **data):
        payload = {
            "legacy_user_id": self.target_legacy.id,
            "permission_code": PERM,
            "next": self.panel_url,
        }
        payload.update(data)
        return self.client.post(self.action_url, payload)

    def _allowed(self, legacy_user) -> bool:
        return describe_access(legacy_user=legacy_user, permission_code=PERM)["allowed_now"]

    # ── pagina 403 ──────────────────────────────────────────────────────

    def test_il_403_registra_il_tentativo_e_mostra_il_nome_leggibile(self):
        self._impersonate()
        response = self.client.get(PAGE)

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Non hai accesso a «Admin Portale › Utenti»", status_code=403)
        self.assertContains(response, "Risolvi come amministratore", status_code=403)
        self.assertContains(response, "impostata su «negato»", status_code=403)
        event = AclDenialEvent.objects.get(legacy_user_id=self.target_legacy.id)
        self.assertEqual(event.permission_code, PERM)
        self.assertEqual(event.status, AclDenialEvent.STATUS_OPEN)
        self.assertEqual(event.hits, 1)

    def test_i_tentativi_ravvicinati_non_scrivono_a_ogni_richiesta(self):
        self._impersonate()
        self.client.get(PAGE)
        self.client.get(PAGE)
        self.assertEqual(AclDenialEvent.objects.get(legacy_user_id=self.target_legacy.id).hits, 1)

        cache.clear()  # finestra di throttle scaduta
        self.client.get(PAGE)
        self.assertEqual(AclDenialEvent.objects.get(legacy_user_id=self.target_legacy.id).hits, 2)

    def test_senza_impersonazione_il_pannello_di_risoluzione_non_compare(self):
        self.client.force_login(self.target)
        response = self.client.get(PAGE)
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, "Risolvi come amministratore", status_code=403)
        self.assertContains(response, "il tentativo è stato registrato", status_code=403)

    def test_consenti_al_ruolo_dal_403(self):
        self._impersonate()
        self.client.get(PAGE)
        response = self._post(origin="forbidden", next=PAGE, scope="role", action="allow")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], PAGE)
        self.assertTrue(RolePermissionGrant.objects.get(legacy_role_id=ROLE_USER, permission_id=PERM).enabled)
        self.assertTrue(self._allowed(self.target_legacy))
        self.assertEqual(
            AclDenialEvent.objects.get(legacy_user_id=self.target_legacy.id).status,
            AclDenialEvent.STATUS_ALLOWED,
        )
        audit = AuditLog.objects.filter(azione="acl_risolvi_accesso", modulo="admin_portale")
        self.assertEqual(audit.count(), 1)
        self.assertEqual(audit.first().legacy_user_id, self.admin_legacy.id)

    def test_non_consentire_dal_403_mostra_l_esito_sulla_pagina(self):
        self._impersonate()
        self._post(origin="forbidden", next=PAGE, scope="user", action="deny")

        self.assertFalse(UserPermissionGrant.objects.get(legacy_user_id=self.target_legacy.id, permission_id=PERM).enabled)
        response = self.client.get(PAGE)
        self.assertContains(response, "negato a Mario Rossi", status_code=403)

    # ── esito verificato ────────────────────────────────────────────────

    def test_consentire_al_ruolo_non_basta_se_un_eccezione_personale_nega(self):
        UserPermissionGrant.objects.create(legacy_user_id=self.target_legacy.id, permission_id=PERM, enabled=False)
        self.assertIn("eccezione personale", describe_access(legacy_user=self.target_legacy, permission_code=PERM)["role_allow_blocked_by"])
        self._event(self.target_legacy)
        self.client.force_login(self.admin)

        response = self._post(scope="role", action="allow")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(RolePermissionGrant.objects.get(legacy_role_id=ROLE_USER, permission_id=PERM).enabled)
        self.assertFalse(self._allowed(self.target_legacy))
        self.assertEqual(
            AclDenialEvent.objects.get(legacy_user_id=self.target_legacy.id).status,
            AclDenialEvent.STATUS_DENIED,
        )

    def test_togliere_l_eccezione_personale_lascia_decidere_il_ruolo(self):
        RolePermissionGrant.objects.filter(legacy_role_id=ROLE_USER, permission_id=PERM).update(enabled=True)
        UserPermissionGrant.objects.create(legacy_user_id=self.target_legacy.id, permission_id=PERM, enabled=False)
        self.client.force_login(self.admin)

        self._post(scope="role", action="reset")  # reset vale sempre sulla persona

        self.assertFalse(UserPermissionGrant.objects.filter(legacy_user_id=self.target_legacy.id).exists())
        self.assertTrue(self._allowed(self.target_legacy))

    def test_un_gruppo_che_nega_prevale_sul_ruolo(self):
        group = AccessGroup.objects.create(code="esterni", label="Esterni", priority=100)
        AccessGroupMembership.objects.create(group=group, legacy_user_id=self.target_legacy.id)
        GroupPermissionGrant.objects.create(group=group, permission_id=PERM, enabled=False)

        info = describe_access(legacy_user=self.target_legacy, permission_code=PERM)

        self.assertIn("Esterni", info["explanation"])
        self.assertIn("Esterni", info["role_allow_blocked_by"])
        self.assertEqual(info["group"]["state"], "deny")

    def test_consentire_al_ruolo_chiude_anche_i_403_degli_altri_del_ruolo(self):
        self._event(self.target_legacy)
        other = self._event(self.other_legacy)
        self.client.force_login(self.admin)

        self._post(scope="role", action="allow")

        other.refresh_from_db()
        self.assertEqual(other.status, AclDenialEvent.STATUS_ALLOWED)

    def test_un_no_dato_a_una_persona_non_decide_per_gli_altri_del_ruolo(self):
        self._event(self.target_legacy)
        other = self._event(self.other_legacy)
        self.client.force_login(self.admin)

        self._post(scope="role", action="deny")

        other.refresh_from_db()
        self.assertEqual(other.status, AclDenialEvent.STATUS_OPEN)
        self.assertEqual(
            AclDenialEvent.objects.get(legacy_user_id=self.target_legacy.id).status,
            AclDenialEvent.STATUS_DENIED,
        )

    # ── pannello e sicurezza ────────────────────────────────────────────

    def test_il_pannello_elenca_gli_accessi_da_decidere(self):
        self._event(self.target_legacy)
        self.client.force_login(self.admin)

        response = self.client.get(self.panel_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mario Rossi")
        self.assertContains(response, "Admin Portale › Utenti")
        self.assertContains(response, "Negato esplicitamente")
        self.assertContains(response, "Da decidere (1)")

    def test_pagina_senza_permesso_canonico_rimanda_alla_coverage(self):
        request = SimpleNamespace(legacy_user=self.target_legacy, path="/pagina-legacy/")
        record_denial(
            request,
            {"allowed": False, "path_normalized": "/pagina-legacy/", "decision_source": "legacy_fallback", "canonical": {}},
        )
        self.client.force_login(self.admin)

        response = self.client.get(self.panel_url)

        self.assertEqual(AclDenialEvent.objects.get(legacy_user_id=self.target_legacy.id).dedup_key, "path:/pagina-legacy/")
        self.assertContains(response, "ACL Route Coverage")

    def test_le_richieste_automatiche_del_browser_non_si_registrano(self):
        request = SimpleNamespace(legacy_user=self.target_legacy, path="/favicon.ico")
        record_denial(
            request,
            {"allowed": False, "path_normalized": "/favicon.ico", "decision_source": "legacy_fallback", "canonical": {}},
        )
        self.assertFalse(AclDenialEvent.objects.exists())

    def test_ignora_chiude_la_segnalazione_senza_toccare_i_permessi(self):
        event = self._event(self.target_legacy)
        self.client.force_login(self.admin)

        self.client.post(self.action_url, {"action": "ignore", "event_id": event.pk, "next": self.panel_url})

        event.refresh_from_db()
        self.assertEqual(event.status, AclDenialEvent.STATUS_IGNORED)
        self.assertFalse(RolePermissionGrant.objects.get(legacy_role_id=ROLE_USER, permission_id=PERM).enabled)

    def test_chi_non_e_admin_non_puo_concedersi_nulla(self):
        self.client.force_login(self.target)

        response = self._post(scope="user", action="allow")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserPermissionGrant.objects.exists())
        self.assertFalse(RolePermissionGrant.objects.get(legacy_role_id=ROLE_USER, permission_id=PERM).enabled)

    def test_next_verso_un_altro_sito_viene_ignorato(self):
        self.client.force_login(self.admin)

        response = self._post(scope="user", action="allow", next="https://example.com/altrove")

        self.assertEqual(response["Location"], self.panel_url)
