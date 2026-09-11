"""Precedenza del risolutore unico: override utente, gruppi, ruolo, legacy.

Il caso che ha aperto il lavoro: in produzione il pannello concedeva il permesso
legacy sulla pagina, ma la riga ``RolePermissionGrant`` esisteva a ``False`` e
spegneva il fallback legacy, quindi la concessione non aveva effetto. Qui quella
condizione e' riprodotta esplicitamente, perche' e' quella di produzione e non
quella (catalogo canonico vuoto) su cui i test passavano prima.
"""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase, override_settings

from core.acl_resolver import (
    LEVEL_GROUP_GRANT,
    LEVEL_ROLE_GRANT,
    LEVEL_USER_OVERRIDE,
    group_grants_map,
    resolve_permission_decision,
)
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Ruolo, UtenteLegacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    GroupPermissionGrant,
    PermissionDefinition,
    RolePermissionGrant,
    UserPermissionGrant,
)
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

PERM = "assets.gestione_admin.view"
RUOLO_ID = 77


@override_settings(LEGACY_AUTH_ENABLED=True)
class AclResolverPrecedenceTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()

        Ruolo.objects.create(id=RUOLO_ID, nome="manutenzione")
        self.legacy_user = UtenteLegacy.objects.create(
            nome="Mario Manutentore",
            email="manutentore@example.local",
            password="x",
            ruolo="manutenzione",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=RUOLO_ID,
        )
        self.permission = PermissionDefinition.objects.create(
            code=PERM, label="Assets - Impostazioni", module="assets"
        )
        bump_legacy_cache_version()

    # -- helper ---------------------------------------------------------
    def _group(self, code: str, priority: int, *, member: bool = True) -> AccessGroup:
        group = AccessGroup.objects.create(code=code, label=code.title(), priority=priority)
        if member:
            AccessGroupMembership.objects.create(group=group, legacy_user_id=self.legacy_user.id)
        return group

    def _grant_group(self, group: AccessGroup, enabled: bool) -> None:
        GroupPermissionGrant.objects.create(group=group, permission=self.permission, enabled=enabled)

    def _decide(self):
        return resolve_permission_decision(permission_code=PERM, legacy_user=self.legacy_user)

    # -- test -----------------------------------------------------------
    def test_senza_nulla_nega(self):
        decision = self._decide()
        self.assertFalse(decision.allowed)

    def test_gruppo_concede(self):
        self._grant_group(self._group("manutenzione", 100), True)
        decision = self._decide()
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.level, LEVEL_GROUP_GRANT)
        self.assertEqual(decision.group_grant["group_code"], "manutenzione")

    def test_gruppo_piu_pesante_vince(self):
        self._grant_group(self._group("base", 10), False)
        self._grant_group(self._group("responsabili", 900), True)
        decision = self._decide()
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.group_grant["group_code"], "responsabili")

    def test_a_parita_di_priorita_vince_il_diniego(self):
        self._grant_group(self._group("uno", 100), True)
        self._grant_group(self._group("due", 100), False)
        decision = self._decide()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.group_grant["group_code"], "due")

    def test_override_utente_batte_il_gruppo(self):
        self._grant_group(self._group("manutenzione", 900), True)
        UserPermissionGrant.objects.create(
            legacy_user_id=self.legacy_user.id, permission=self.permission, enabled=False
        )
        decision = self._decide()
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.level, LEVEL_USER_OVERRIDE)

    def test_gruppo_batte_il_ruolo(self):
        RolePermissionGrant.objects.create(
            legacy_role_id=RUOLO_ID, permission=self.permission, enabled=False
        )
        self._grant_group(self._group("manutenzione", 100), True)
        decision = self._decide()
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.level, LEVEL_GROUP_GRANT)

    def test_gruppo_senza_appartenenza_non_conta(self):
        self._grant_group(self._group("altri", 900, member=False), True)
        self.assertFalse(self._decide().allowed)

    def test_gruppo_disattivato_non_conta(self):
        group = self._group("manutenzione", 900)
        self._grant_group(group, True)
        AccessGroup.objects.filter(pk=group.pk).update(is_active=False)
        self.assertFalse(self._decide().allowed)

    def test_ruolo_decide_quando_i_gruppi_tacciono(self):
        self._group("manutenzione", 100)  # membro, ma nessun grant su questo permesso
        RolePermissionGrant.objects.create(
            legacy_role_id=RUOLO_ID, permission=self.permission, enabled=True
        )
        decision = self._decide()
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.level, LEVEL_ROLE_GRANT)

    def test_grant_ruolo_a_false_spegne_il_fallback_legacy(self):
        """La condizione di produzione che rendeva inutile il pannello legacy."""
        Permesso.objects.create(
            ruolo_id=RUOLO_ID, modulo="assets", azione="gestione_admin", consentito=1, can_view=1
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=RUOLO_ID, permission=self.permission, enabled=False
        )
        bump_legacy_cache_version()
        self.assertFalse(self._decide().allowed)

    def test_il_gruppo_riapre_cio_che_il_ruolo_aveva_chiuso(self):
        """Rimedio previsto per quel caso: il gruppo sta sopra al ruolo."""
        RolePermissionGrant.objects.create(
            legacy_role_id=RUOLO_ID, permission=self.permission, enabled=False
        )
        self._grant_group(self._group("manutenzione", 500), True)
        self.assertTrue(self._decide().allowed)

    def test_group_grants_map_risolve_le_priorita(self):
        self._grant_group(self._group("base", 10), True)
        self._grant_group(self._group("capi", 800), False)
        self.assertEqual(group_grants_map(self.legacy_user.id), {PERM: False})

    def test_permesso_disattivo_nega_anche_col_gruppo(self):
        self._grant_group(self._group("manutenzione", 900), True)
        PermissionDefinition.objects.filter(pk=self.permission.pk).update(is_active=False)
        decision = self._decide()
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.permission_inactive)
