"""Test permessi anagrafica:
  - Feature B: allow-list per-utente additiva sui gate interni.
  - Feature A: helper write-through ACL v2 (ruoli + override utente) e coerenza
    con ``evaluate_permission_code_access`` (stesse tabelle di ACL v2 canonico).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from core.acl_v2 import (
    apply_role_grants,
    apply_user_overrides,
    evaluate_permission_code_access,
)
from core.models import (
    PermissionDefinition,
    RolePermissionGrant,
    UserPermissionGrant,
)

from anagrafica import views as av
from anagrafica.models import (
    AnagraficaHRPermission,
    AnagraficaStatPermission,
    AnagraficaVisiteMedichePermission,
)


class UtenteAllowlistHelperTests(TestCase):
    """`_user_in_utente_allowlist`: concessione additiva per singolo utente."""

    def test_utente_in_lista(self):
        perm = SimpleNamespace(utente_ids=[7, 42])
        self.assertTrue(av._user_in_utente_allowlist(SimpleNamespace(id=42), perm))

    def test_utente_non_in_lista(self):
        perm = SimpleNamespace(utente_ids=[7, 42])
        self.assertFalse(av._user_in_utente_allowlist(SimpleNamespace(id=99), perm))

    def test_lista_vuota_o_none(self):
        self.assertFalse(av._user_in_utente_allowlist(SimpleNamespace(id=1), SimpleNamespace(utente_ids=[])))
        self.assertFalse(av._user_in_utente_allowlist(SimpleNamespace(id=1), SimpleNamespace(utente_ids=None)))

    def test_utente_none(self):
        self.assertFalse(av._user_in_utente_allowlist(None, SimpleNamespace(utente_ids=[1])))

    def test_id_come_stringa_nella_lista(self):
        # utente_ids può arrivare da JSON con id "misti": la coercion a int deve reggere
        perm = SimpleNamespace(utente_ids=["42"])
        self.assertTrue(av._user_in_utente_allowlist(SimpleNamespace(id=42), perm))


class GateAdditivoTests(TestCase):
    """I tre gate concedono accesso all'utente in allow-list anche con accesso=ADMIN."""

    def _request(self):
        return SimpleNamespace(user=SimpleNamespace(is_superuser=False, is_authenticated=True))

    def _run_gate(self, gate_fn, perm_model, singleton):
        singleton.accesso = perm_model.ACCESSO_ADMIN  # ramo più restrittivo
        singleton.utente_ids = [42]
        singleton.save()
        legacy_user = SimpleNamespace(id=42, ruolo_id=None)
        with mock.patch.object(av, "get_legacy_user", return_value=legacy_user), \
             mock.patch.object(av, "is_legacy_admin", return_value=False):
            allowed_in = gate_fn(self._request())
        # utente fuori lista → resta negato (accesso=ADMIN, non admin)
        other = SimpleNamespace(id=7, ruolo_id=None)
        with mock.patch.object(av, "get_legacy_user", return_value=other), \
             mock.patch.object(av, "is_legacy_admin", return_value=False):
            allowed_out = gate_fn(self._request())
        return allowed_in, allowed_out

    def test_gate_statistiche(self):
        ain, aout = self._run_gate(
            av._can_view_stats, AnagraficaStatPermission, AnagraficaStatPermission.get_instance()
        )
        self.assertTrue(ain)
        self.assertFalse(aout)

    def test_gate_hr(self):
        ain, aout = self._run_gate(
            av._check_hr_permission, AnagraficaHRPermission, AnagraficaHRPermission.get_instance()
        )
        self.assertTrue(ain)
        self.assertFalse(aout)

    def test_gate_visite_mediche(self):
        ain, aout = self._run_gate(
            av._can_view_visite_mediche,
            AnagraficaVisiteMedichePermission,
            AnagraficaVisiteMedichePermission.get_instance(),
        )
        self.assertTrue(ain)
        self.assertFalse(aout)

    def test_superuser_sempre_ok(self):
        AnagraficaStatPermission.get_instance()  # accesso di default = ADMIN
        req = SimpleNamespace(user=SimpleNamespace(is_superuser=True, is_authenticated=True))
        self.assertTrue(av._can_view_stats(req))


class ApplyRoleGrantsTests(TestCase):
    """`apply_role_grants`: write-through su RolePermissionGrant (scope = permessi dati)."""

    def setUp(self):
        self.p_view = PermissionDefinition.objects.create(
            code="anagrafica.testperm.view", module="anagrafica", label="Test view")
        self.p_manage = PermissionDefinition.objects.create(
            code="anagrafica.testperm.manage", module="anagrafica", label="Test manage")
        self.perms = [self.p_view, self.p_manage]
        self.role_id = 501

    def test_crea_grant_selezionati_e_non(self):
        created, updated = apply_role_grants(self.role_id, self.perms, {self.p_view.code})
        self.assertEqual((created, updated), (2, 0))
        self.assertTrue(RolePermissionGrant.objects.get(
            legacy_role_id=self.role_id, permission_id=self.p_view.code).enabled)
        self.assertFalse(RolePermissionGrant.objects.get(
            legacy_role_id=self.role_id, permission_id=self.p_manage.code).enabled)

    def test_update_idempotente(self):
        apply_role_grants(self.role_id, self.perms, {self.p_view.code})
        # nessuna modifica → 0 created, 0 updated
        created, updated = apply_role_grants(self.role_id, self.perms, {self.p_view.code})
        self.assertEqual((created, updated), (0, 0))
        # cambio selezione → 1 updated (manage acceso, view spento = 2 updated)
        created, updated = apply_role_grants(self.role_id, self.perms, {self.p_manage.code})
        self.assertEqual(created, 0)
        self.assertEqual(updated, 2)

    def test_evaluate_riflette_il_grant(self):
        apply_role_grants(self.role_id, self.perms, set())
        res = evaluate_permission_code_access(
            permission_code=self.p_view.code, legacy_role_id=self.role_id)
        self.assertFalse(res["allowed"])
        apply_role_grants(self.role_id, self.perms, {self.p_view.code})
        res = evaluate_permission_code_access(
            permission_code=self.p_view.code, legacy_role_id=self.role_id)
        self.assertTrue(res["allowed"])


class ApplyUserOverridesTests(TestCase):
    """`apply_user_overrides`: write-through su UserPermissionGrant (precede il ruolo)."""

    def setUp(self):
        self.p_view = PermissionDefinition.objects.create(
            code="anagrafica.testperm.view", module="anagrafica", label="Test view")
        self.p_manage = PermissionDefinition.objects.create(
            code="anagrafica.testperm.manage", module="anagrafica", label="Test manage")
        self.perms = [self.p_view, self.p_manage]
        self.role_id = 501
        self.user_id = 9001

    def test_allow_deny_e_rimozione(self):
        changed = apply_user_overrides(
            self.user_id, self.perms, [self.p_view.code], [self.p_manage.code])
        self.assertEqual(changed, 2)
        self.assertTrue(UserPermissionGrant.objects.get(
            legacy_user_id=self.user_id, permission_id=self.p_view.code).enabled)
        self.assertFalse(UserPermissionGrant.objects.get(
            legacy_user_id=self.user_id, permission_id=self.p_manage.code).enabled)
        # ora "eredita" su entrambi → gli override vengono rimossi
        changed = apply_user_overrides(self.user_id, self.perms, [], [])
        self.assertEqual(changed, 2)
        self.assertEqual(UserPermissionGrant.objects.filter(legacy_user_id=self.user_id).count(), 0)

    def test_override_precede_il_ruolo(self):
        # ruolo consente view; override utente nega → deve vincere il deny utente
        apply_role_grants(self.role_id, self.perms, {self.p_view.code})
        apply_user_overrides(self.user_id, self.perms, [], [self.p_view.code])
        res = evaluate_permission_code_access(
            permission_code=self.p_view.code,
            legacy_role_id=self.role_id, legacy_user_id=self.user_id)
        self.assertFalse(res["allowed"])
        self.assertEqual(res["effective_level"], "user_override")
        # override allow su un permesso che il ruolo nega → vince l'allow utente
        apply_user_overrides(self.user_id, self.perms, [self.p_manage.code], [])
        res = evaluate_permission_code_access(
            permission_code=self.p_manage.code,
            legacy_role_id=self.role_id, legacy_user_id=self.user_id)
        self.assertTrue(res["allowed"])
        self.assertEqual(res["effective_level"], "user_override")
