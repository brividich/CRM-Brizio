"""«Menu del portale»: pagina pratica del Navigation Builder."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from admin_portale.tests import _ensure_utenti_table
from admin_portale.views.menu_portale import dati_menu
from core.legacy_models import UtenteLegacy
from core.models import (
    AccessGroup,
    AccessGroupMembership,
    GroupPermissionGrant,
    ModuleCategory,
    NavigationItem,
    PermissionDefinition,
    RoutePermissionBinding,
    SiteConfig,
    UserNavigationOverride,
)
from core.permessi.cache import invalida_permessi
from core.permessi.motore import PRESET_BASE, SITECONFIG_SISTEMA_ATTIVO

PAGINA = "dashboard.home.view"
VECCHIO = "legacy.dashboard.dashboard_home"


class MenuPortaleTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        _ensure_utenti_table()
        self.admin_user = get_user_model().objects.create_superuser(
            username="admin-menu-portale", email="admin.menu@test.local", password="pass12345"
        )
        self.admin_legacy = UtenteLegacy.objects.create(
            nome="Admin Menu", email="admin.menu@test.local", password="*AD_MANAGED*",
            ruolo="admin", ruolo_id=1, attivo=True, deve_cambiare_password=False,
        )
        self.persona = UtenteLegacy.objects.create(
            nome="Persona Menu", email="persona.menu@test.local", password="*AD_MANAGED*",
            ruolo="operatore", ruolo_id=77, attivo=True, deve_cambiare_password=False,
        )
        for code in (PAGINA, VECCHIO):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": "dashboard", "is_active": True})
        RoutePermissionBinding.objects.create(permission_id=PAGINA, route_name="dashboard_home", path_pattern="/dashboard", is_active=True)
        self.area = ModuleCategory.objects.create(key="area-test", label="Area di prova", order=1)
        self.altra_area = ModuleCategory.objects.create(key="area-due", label="Seconda area", order=2)
        self.base = AccessGroup.objects.filter(preset=PRESET_BASE).first()
        self.capo = AccessGroup.objects.create(code="capo-menu", label="Capo di prova", priority=60)
        self.voce = NavigationItem.objects.create(
            code="voce-prova", label="Voce di prova", section="topbar", route_name="dashboard_home",
            required_permission_code=VECCHIO, category=self.area, order=10, is_visible=True, is_enabled=True,
        )
        self.sotto = NavigationItem.objects.create(
            code="sotto-prova", label="Sottovoce", section="subnav", parent_code="voce-prova",
            route_name="dashboard_home", order=10, is_visible=True, is_enabled=True,
        )

    def _accendi(self):
        SiteConfig.set(SITECONFIG_SISTEMA_ATTIVO, "1")
        invalida_permessi()

    def _come_admin(self, metodo, nome, dati=None, **kwargs):
        self.client.force_login(self.admin_user)
        with patch("admin_portale.decorators.get_legacy_user", return_value=self.admin_legacy), patch(
            "admin_portale.decorators.is_legacy_admin", return_value=True
        ):
            if metodo == "get":
                return self.client.get(reverse(nome), dati or {})
            return self.client.post(reverse(nome), json.dumps(dati or {}), content_type="application/json", **kwargs)

    def _voce(self, dati, item_id):
        for area in dati["aree"]:
            for v in area["voci"]:
                if v["id"] == item_id:
                    return area, v
                for f in v.get("figli", []):
                    if f["id"] == item_id:
                        return area, f
        raise AssertionError(f"voce {item_id} non trovata")

    def test_albero_per_area_con_sottovoci_e_chi_la_vede(self):
        self._accendi()
        GroupPermissionGrant.objects.create(group=self.capo, permission_id=PAGINA, enabled=True)
        dati = dati_menu()

        area, voce = self._voce(dati, self.voce.id)
        self.assertEqual(area["nome"], "Area di prova")
        self.assertEqual([f["id"] for f in voce["figli"]], [self.sotto.id])
        self.assertIn(self.capo.id, voce["ruoli"])
        self.assertEqual(voce["problema"]["tipo"], "vecchio")

    def test_ruolo_base_vuol_dire_tutti(self):
        if self.base is None:
            self.skipTest("ruolo base non presente nel DB di test")
        GroupPermissionGrant.objects.create(group=self.base, permission_id=PAGINA, enabled=True)
        self._accendi()
        _area, voce = self._voce(dati_menu(), self.sotto.id)
        self.assertTrue(voce["tutti"])
        self.assertIn(self.capo.id, voce["ruoli"])

    def test_pagina_mostra_albero_e_strumenti_avanzati(self):
        response = self._come_admin("get", "admin_portale:navigation_builder")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin_portale/pages/menu_portale.html")
        self.assertContains(response, "Guarda il menu come")
        self.assertContains(response, reverse("admin_portale:navigation_builder_avanzato"))
        self.assertContains(response, 'id="mp-dati"')
        self.assertContains(response, "Voce di prova")

    def test_strumenti_avanzati_restano_raggiungibili(self):
        response = self._come_admin("get", "admin_portale:navigation_builder_avanzato")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Strumenti avanzati")

    def test_salva_nome_area_icona_e_visibilita(self):
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {
            "id": self.voce.id, "nome": "Nuovo nome", "categoria": self.altra_area.id, "icona": "ticket", "visibile": False,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.voce.refresh_from_db()
        self.assertEqual(self.voce.label, "Nuovo nome")
        self.assertEqual(self.voce.category_id, self.altra_area.id)
        self.assertEqual(self.voce.icon, "ticket")
        self.assertFalse(self.voce.is_visible)
        # Il resto della voce non si tocca.
        self.assertEqual(self.voce.required_permission_code, VECCHIO)
        self.assertEqual(self.voce.route_name, "dashboard_home")

    def test_sposta_sottovoce_sotto_altro_modulo(self):
        NavigationItem.objects.create(code="altro-modulo", label="Altro", section="topbar", route_name="dashboard_home", order=20)
        self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.sotto.id, "padre": "altro-modulo"})
        self.sotto.refresh_from_db()
        self.assertEqual(self.sotto.parent_code, "altro-modulo")

    def test_nome_vuoto_rifiutato(self):
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.voce.id, "nome": "  "})
        self.assertEqual(response.status_code, 400)

    def test_sistema_da_solo_toglie_il_permesso_vecchio(self):
        response = self._come_admin("post", "admin_portale:api_menu_voce_sistema", {"id": self.voce.id})
        self.assertEqual(response.status_code, 200, response.content)
        self.voce.refresh_from_db()
        self.assertEqual(self.voce.required_permission_code, "")
        # Una seconda volta non c'e' piu' niente da sistemare.
        response = self._come_admin("post", "admin_portale:api_menu_voce_sistema", {"id": self.voce.id})
        self.assertEqual(response.status_code, 400)

    def test_vedi_persona_usa_i_ruoli_e_gli_override(self):
        self._accendi()
        GroupPermissionGrant.objects.create(group=self.capo, permission_id=PAGINA, enabled=True)
        AccessGroupMembership.objects.create(group=self.capo, legacy_user_id=self.persona.id)
        UserNavigationOverride.objects.create(legacy_user_id=self.persona.id, item=self.sotto, enabled=False)
        invalida_permessi()

        response = self._come_admin("get", "admin_portale:api_menu_vedi_persona", {"user_id": self.persona.id})
        self.assertEqual(response.status_code, 200)
        voci = response.json()["voci"]
        self.assertTrue(voci[str(self.voce.id)]["vede"])
        self.assertFalse(voci[str(self.sotto.id)]["vede"])
        self.assertTrue(voci[str(self.sotto.id)]["nascosta_a_lui"])
