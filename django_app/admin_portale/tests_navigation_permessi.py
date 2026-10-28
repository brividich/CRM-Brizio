"""Menu e Navigation Builder con «Ruoli e permessi» attivo: decide il permesso della pagina."""
from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from admin_portale.tests import _ensure_utenti_table
from admin_portale.views.navigazione import _explicit_code_to_store
from core.legacy_models import Ruolo, UtenteLegacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    GroupPermissionGrant,
    NavigationItem,
    NavigationRoleAccess,
    PermissionDefinition,
    RoutePermissionBinding,
    SiteConfig,
)
from core.navigation_registry import (
    PERMESSO_ESPLICITO_E_PAGINA,
    PERMESSO_ESPLICITO_IGNORATO,
    describe_navigation_items_permission,
    get_topbar_nodes,
    resolve_navigation_item_permission_code,
)
from core.permessi.cache import invalida_permessi
from core.permessi.motore import SITECONFIG_SISTEMA_ATTIVO

PAGINA = "dashboard.home.view"
VECCHIO = "legacy.dashboard.dashboard_home"
STRETTO = "dashboard.stretto.view"


class _Base(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.role = Ruolo.objects.create(id=303, nome="Ruolo storico menu")
        self.legacy_user = UtenteLegacy.objects.create(
            id=903,
            nome="Utente Menu",
            email="menu@example.local",
            password="hash",
            ruolo=self.role.nome,
            ruolo_id=self.role.id,
            attivo=True,
        )
        for code in (PAGINA, VECCHIO, STRETTO):
            PermissionDefinition.objects.create(code=code, label=code, module="dashboard", is_active=True)
        RoutePermissionBinding.objects.create(
            permission_id=PAGINA, route_name="dashboard_home", path_pattern="/dashboard", is_active=True
        )
        # STRETTO protegge un'altra pagina: e' un permesso vero.
        RoutePermissionBinding.objects.create(
            permission_id=STRETTO, route_name="profilo", path_pattern="/profilo", is_active=True
        )
        self.gruppo = AccessGroup.objects.create(code="menu-test", label="Ruolo menu", priority=40)
        AccessGroupMembership.objects.create(group=self.gruppo, legacy_user_id=self.legacy_user.id)

    def _accendi(self):
        SiteConfig.set(SITECONFIG_SISTEMA_ATTIVO, "1")
        invalida_permessi()

    def _concedi(self, code):
        GroupPermissionGrant.objects.create(group=self.gruppo, permission_id=code, enabled=True)
        invalida_permessi()

    def _voce(self, code="voce-menu", **extra):
        return NavigationItem.objects.create(
            code=code, label="Voce", section="topbar", route_name="dashboard_home",
            order=10, is_visible=True, is_enabled=True, **extra,
        )

    def _codici_menu(self):
        nodes = get_topbar_nodes(
            current_path="/", role_id=self.role.id, is_admin=False, legacy_user_id=self.legacy_user.id
        )
        return {n.codice for n in nodes}


class MenuSistemaRuoliTests(_Base):
    def test_permesso_vecchio_ignorato_decide_la_pagina(self):
        item = self._voce(required_permission_code=VECCHIO)
        self._accendi()
        self._concedi(PAGINA)

        self.assertEqual(describe_navigation_items_permission([item])[item.id]["stato"], PERMESSO_ESPLICITO_IGNORATO)
        self.assertEqual(resolve_navigation_item_permission_code(item), PAGINA)
        self.assertIn("voce-menu", self._codici_menu())

    def test_permesso_vero_diverso_servono_entrambi(self):
        item = self._voce(required_permission_code=STRETTO)
        self._accendi()
        self._concedi(STRETTO)

        self.assertEqual(describe_navigation_items_permission([item])[item.id]["stato"], PERMESSO_ESPLICITO_E_PAGINA)
        # Solo il permesso della voce: la pagina darebbe 403, la voce non compare.
        self.assertNotIn("voce-menu", self._codici_menu())
        self._concedi(PAGINA)
        self.assertIn("voce-menu", self._codici_menu())

    def test_voce_senza_permesso_non_la_apre_il_ruolo_storico(self):
        item = NavigationItem.objects.create(
            code="senza-perm", label="Senza pagina", section="topbar", url_path="/pagina-senza-protezione/",
            order=10, is_visible=True, is_enabled=True,
        )
        NavigationRoleAccess.objects.create(item=item, legacy_role_id=self.role.id, can_view=True)
        self.assertIn("senza-perm", self._codici_menu())
        self._accendi()
        self.assertNotIn("senza-perm", self._codici_menu())

    def test_link_esterno_lo_vedono_tutti(self):
        NavigationItem.objects.create(
            code="sito-esterno", label="Sito", section="topbar", url_path="https://example.com/",
            order=10, is_visible=True, is_enabled=True,
        )
        self._accendi()
        self.assertIn("sito-esterno", self._codici_menu())

    def test_sistema_spento_resta_alle_regole_storiche(self):
        item = self._voce(required_permission_code=VECCHIO)
        self._concedi(PAGINA)

        self.assertEqual(resolve_navigation_item_permission_code(item), VECCHIO)
        self.assertNotIn("voce-menu", self._codici_menu())


class RiallineaPermessiMenuTests(_Base):
    def test_dry_run_non_scrive_apply_toglie_solo_i_vecchi(self):
        vecchia = self._voce(code="vecchia", required_permission_code=VECCHIO)
        vera = self._voce(code="vera", required_permission_code=STRETTO)

        out = StringIO()
        call_command("riallinea_permessi_menu", stdout=out)
        # Le migrazioni seminano altre voci: si guardano solo le due del test.
        self.assertRegex(out.getvalue(), rf"vecchia\s+{VECCHIO} -> pagina {PAGINA}")
        self.assertNotIn(STRETTO, out.getvalue())
        vecchia.refresh_from_db()
        self.assertEqual(vecchia.required_permission_code, VECCHIO)

        call_command("riallinea_permessi_menu", "--apply", stdout=StringIO())
        vecchia.refresh_from_db()
        vera.refresh_from_db()
        self.assertEqual(vecchia.required_permission_code, "")
        self.assertEqual(vera.required_permission_code, STRETTO)


class SalvataggioVoceTests(_Base):
    def test_code_uguale_alla_pagina_si_salva_vuoto(self):
        self.assertEqual(_explicit_code_to_store(PAGINA, route_name="dashboard_home", url_path=""), "")
        self.assertEqual(_explicit_code_to_store("", route_name="dashboard_home", url_path=""), "")
        self.assertEqual(_explicit_code_to_store(STRETTO, route_name="dashboard_home", url_path=""), STRETTO)


class AnteprimaBuilderTests(_Base):
    def setUp(self):
        super().setUp()
        _ensure_utenti_table()
        self.admin_user = get_user_model().objects.create_superuser(
            username="admin-nav-permessi", email="admin.nav.permessi@test.local", password="pass12345"
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Nav", email="admin.nav.permessi@test.local", password="*AD_MANAGED*",
            ruolo="admin", ruolo_id=1, attivo=True, deve_cambiare_password=False,
        )

    def _get(self, params):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin", return_value=True
        ):
            return self.client.get(reverse("admin_portale:navigation_builder_avanzato"), params)

    def test_anteprima_usa_i_ruoli_del_portale(self):
        item = self._voce(required_permission_code=VECCHIO)
        self._accendi()
        self._concedi(PAGINA)

        response = self._get({"nav_override_user_id": self.legacy_user.id})

        self.assertEqual(response.status_code, 200)
        row = next(r for r in response.context["nav_override_rows"] if r["item_id"] == item.id)
        self.assertTrue(row["role_allowed"])
        self.assertEqual(row["state"], "role-show")
        self.assertGreaterEqual(response.context["perm_ignorati"], 1)
        self.assertContains(response, "Permesso vecchio")
        self.assertContains(response, "Ruoli e permessi attivo.")

    def test_sistema_spento_mostra_cosa_cambiera(self):
        self._voce(required_permission_code=VECCHIO)
        response = self._get({})
        self.assertContains(response, "Ruoli e permessi spento:")
        self.assertContains(response, "con i ruoli attivi varrà")
