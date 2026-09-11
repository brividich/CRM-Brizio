"""Il pannello Accessi scrive un solo layer: quello canonico.

Il difetto che ha originato la pagina: "Gestione Accessi" salvava nella tabella
legacy ``permessi``, che viene ignorata appena esiste un grant canonico. Qui si
fissa il patto opposto - si scrivono grant canonici e la tabella legacy non
viene mai toccata - e la semantica dei gruppi: un gruppo concede, non nega.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Permesso, Ruolo, UtenteLegacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    GroupPermissionGrant,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
)
from core.test_acl_v2 import _clear_legacy_acl_tables, _ensure_legacy_acl_tables

RUOLO_ADMIN_ID = 1
PERM_A = "assets.gestione_admin.view"
PERM_B = "assets.asset.view"


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class AccessiUnificatiTest(TestCase):
    def setUp(self):
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        cache.clear()

        Ruolo.objects.create(id=RUOLO_ADMIN_ID, nome="admin")
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Amministratore",
            email="admin@example.local",
            password="x",
            ruolo="admin",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=RUOLO_ADMIN_ID,
        )
        self.admin = get_user_model().objects.create_user(
            username="admin-panel", password="pass12345", is_superuser=True, is_staff=True
        )
        Profile.objects.update_or_create(
            user=self.admin, defaults={"legacy_user_id": self.admin_legacy.id}
        )
        PermissionDefinition.objects.create(code=PERM_A, label="Impostazioni assets", module="assets")
        PermissionDefinition.objects.create(code=PERM_B, label="Inventario", module="assets")
        bump_legacy_cache_version()
        self.client.force_login(self.admin)
        self.url = reverse("admin_portale:accessi")

    def _group(self, code="manutenzione", priority=100) -> AccessGroup:
        return AccessGroup.objects.create(code=code, label=code.title(), priority=priority)

    def test_la_pagina_si_apre(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crea un gruppo")

    def test_crea_gruppo(self):
        response = self.client.post(
            self.url,
            {"action": "group_create", "code": "manutenzione", "label": "Manutenzione", "priority": "500"},
        )
        self.assertEqual(response.status_code, 302)
        group = AccessGroup.objects.get(code="manutenzione")
        self.assertEqual(group.priority, 500)
        self.assertIn(f"group:{group.id}", response["Location"])

    def test_codice_gruppo_non_valido_non_crea_nulla(self):
        self.client.post(
            self.url,
            {"action": "group_create", "code": "Manu Tenzione!", "label": "X", "priority": "10"},
        )
        self.assertEqual(AccessGroup.objects.count(), 0)

    def test_aggiunge_e_rimuove_un_membro(self):
        group = self._group()
        self.client.post(
            self.url,
            {"action": "member_add", "group_id": group.id, "member": self.admin_legacy.email},
        )
        membership = AccessGroupMembership.objects.get(group=group)
        self.assertEqual(membership.legacy_user_id, self.admin_legacy.id)

        self.client.post(self.url, {"action": "member_remove", "membership_id": membership.id})
        self.assertFalse(AccessGroupMembership.objects.filter(pk=membership.pk).exists())

    def test_salva_i_grant_del_gruppo(self):
        group = self._group()
        self.client.post(
            self.url,
            {
                "action": "save_grants",
                "subject": f"group:{group.id}",
                "all_codes": [PERM_A, PERM_B],
                "granted": [PERM_A],
            },
        )
        self.assertTrue(
            GroupPermissionGrant.objects.filter(group=group, permission_id=PERM_A, enabled=True).exists()
        )
        # Non spuntato: nessuna riga, non un diniego esplicito.
        self.assertFalse(GroupPermissionGrant.objects.filter(group=group, permission_id=PERM_B).exists())

    def test_togliere_la_spunta_a_un_gruppo_cancella_la_riga(self):
        group = self._group()
        GroupPermissionGrant.objects.create(group=group, permission_id=PERM_A, enabled=True)
        self.client.post(
            self.url,
            {"action": "save_grants", "subject": f"group:{group.id}", "all_codes": [PERM_A], "granted": []},
        )
        self.assertFalse(GroupPermissionGrant.objects.filter(group=group).exists())

    def test_salva_i_grant_del_ruolo_e_non_tocca_il_legacy(self):
        Permesso.objects.create(
            ruolo_id=RUOLO_ADMIN_ID, modulo="assets", azione="gestione_admin", consentito=0, can_view=0
        )
        self.client.post(
            self.url,
            {
                "action": "save_grants",
                "subject": f"role:{RUOLO_ADMIN_ID}",
                "all_codes": [PERM_A, PERM_B],
                "granted": [PERM_A],
            },
        )
        self.assertTrue(
            RolePermissionGrant.objects.filter(
                legacy_role_id=RUOLO_ADMIN_ID, permission_id=PERM_A, enabled=True
            ).exists()
        )
        legacy = Permesso.objects.get(ruolo_id=RUOLO_ADMIN_ID, modulo="assets", azione="gestione_admin")
        self.assertEqual(int(legacy.can_view or 0), 0)

    def test_i_vecchi_pannelli_non_salvano_piu(self):
        for name in ("admin_portale:gestione_accessi", "admin_portale:accessi_semplice"):
            response = self.client.post(reverse(name), {"ruolo_id": RUOLO_ADMIN_ID})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], self.url)

    def test_salva_con_un_solo_campo_json(self):
        """Oltre mille permessi: un campo per riga farebbe 400 prima della view.

        Regressione vista in produzione (1027 permessi in catalogo): il form
        mandava un hidden per permesso e superava
        ``DATA_UPLOAD_MAX_NUMBER_FIELDS``, che Django tratta come richiesta
        sospetta. Ora i selezionati viaggiano in un campo solo.
        """
        import json

        group = self._group()
        response = self.client.post(
            self.url,
            {
                "action": "save_grants",
                "subject": f"group:{group.id}",
                "granted_json": json.dumps([PERM_A]),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            GroupPermissionGrant.objects.filter(group=group, permission_id=PERM_A, enabled=True).exists()
        )
        self.assertFalse(GroupPermissionGrant.objects.filter(group=group, permission_id=PERM_B).exists())

    def test_il_form_non_manda_un_campo_per_permesso(self):
        """Il difetto stava nel markup: niente hidden per riga."""
        response = self.client.get(self.url)
        body = response.content.decode("utf-8")
        self.assertNotIn('name="all_codes"', body)
        self.assertIn('name="granted_json"', body)

    def test_selezione_json_illeggibile_non_scrive_nulla(self):
        group = self._group()
        GroupPermissionGrant.objects.create(group=group, permission_id=PERM_A, enabled=True)
        self.client.post(
            self.url,
            {"action": "save_grants", "subject": f"group:{group.id}", "granted_json": "{non-json"},
        )
        self.assertTrue(GroupPermissionGrant.objects.filter(group=group, permission_id=PERM_A).exists())
