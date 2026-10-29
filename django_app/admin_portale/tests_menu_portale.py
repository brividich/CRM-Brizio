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
        # Solo le voci del test: quelle seminate dalle migrazioni portano anche loro alla dashboard.
        NavigationItem.objects.all().delete()
        self.area = ModuleCategory.objects.create(key="area-test", label="Area di prova", order=1)
        self.altra_area = ModuleCategory.objects.create(key="area-due", label="Seconda area", order=2)
        self.base = AccessGroup.objects.filter(preset=PRESET_BASE).first()
        self.capo = AccessGroup.objects.create(code="capo-menu", label="Capo di prova", priority=60)
        self.voce = NavigationItem.objects.create(
            code="voce-prova", label="Voce di prova", section="topbar", route_name="dashboard_home",
            required_permission_code=VECCHIO, category=self.area, order=10, is_visible=True, is_enabled=True,
        )
        self.sotto = NavigationItem.objects.create(
            # Le sottovoci stanno nelle pagine dell'app (``dashboard_home`` = "dashboard").
            code="sotto-prova", label="Sottovoce", section="subnav", parent_code="dashboard",
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
        return dati["voci"][str(item_id)]

    def _nodo(self, dati, tipo, nodo_id):
        for n in dati["barra"]:
            if n["tipo"] == tipo and n["id"] == nodo_id:
                return n
        raise AssertionError(f"{tipo} {nodo_id} non nella barra")

    def test_barra_con_tendine_sottovoci_e_chi_la_vede(self):
        self._accendi()
        GroupPermissionGrant.objects.create(group=self.capo, permission_id=PAGINA, enabled=True)
        dati = dati_menu()

        tendina = self._nodo(dati, "categoria", self.area.id)
        self.assertEqual(tendina["nome"], "Area di prova")
        self.assertIn(self.voce.id, tendina["voci"])
        voce = self._voce(dati, self.voce.id)
        self.assertEqual(voce["app"], "dashboard")
        self.assertIn(self.sotto.id, voce["figli"])
        self.assertIn(self.capo.id, voce["ruoli"])
        self.assertEqual(voce["problema"]["tipo"], "vecchio")
        # Anche la categoria vuota c'e': si vede che esiste e si puo' eliminare.
        self.assertEqual(self._nodo(dati, "categoria", self.altra_area.id)["voci"], [])

    def test_ordine_della_barra_mescola_tendine_e_voci_da_sole(self):
        sola = NavigationItem.objects.create(code="sola", label="Sola", section="topbar", url_path="https://example.local/", order=1)
        self.area.order = 5
        self.area.save()
        ordine = [(n["tipo"], n["id"]) for n in dati_menu()["barra"]]
        self.assertLess(ordine.index(("voce", sola.id)), ordine.index(("categoria", self.area.id)))

    def test_sottogruppi_della_tendina_come_nella_barra(self):
        self.voce.group = "Da fare"
        self.voce.save()
        NavigationItem.objects.create(
            code="v2", label="V2", section="topbar", route_name="dashboard_home", category=self.area, group="Richieste", order=20,
        )
        tendina = self._nodo(dati_menu(), "categoria", self.area.id)
        self.assertEqual([s["nome"] for s in tendina["sezioni"]], ["Da fare", "Richieste"])
        self.assertEqual(tendina["gruppi"], ["Da fare", "Richieste"])

    def test_sottovoce_di_app_senza_voce_resta_orfana(self):
        orfana = NavigationItem.objects.create(
            code="orfana", label="Orfana", section="subnav", parent_code="app_inesistente", route_name="dashboard_home",
        )
        self.assertIn({"app": "app_inesistente", "voci": [orfana.id]}, dati_menu()["orfani"])

    def test_ruolo_base_vuol_dire_tutti(self):
        if self.base is None:
            self.skipTest("ruolo base non presente nel DB di test")
        GroupPermissionGrant.objects.create(group=self.base, permission_id=PAGINA, enabled=True)
        self._accendi()
        voce = self._voce(dati_menu(), self.sotto.id)
        self.assertTrue(voce["tutti"])
        self.assertIn(self.capo.id, voce["ruoli"])

    def test_pagina_mostra_barra_e_strumenti_avanzati(self):
        response = self._come_admin("get", "admin_portale:navigation_builder")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "admin_portale/pages/menu_portale.html")
        self.assertContains(response, "Guarda il menu come")
        self.assertContains(response, "La barra in alto del portale")
        self.assertContains(response, "+ Nuova categoria")
        self.assertContains(response, reverse("admin_portale:navigation_builder_avanzato"))
        self.assertContains(response, 'id="mp-dati"')
        self.assertContains(response, "Voce di prova")

    def test_strumenti_avanzati_restano_raggiungibili(self):
        response = self._come_admin("get", "admin_portale:navigation_builder_avanzato")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Strumenti avanzati")

    def test_salva_nome_categoria_icona_e_visibilita(self):
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

    def test_voce_da_sola_e_sottogruppo(self):
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.voce.id, "categoria": None, "gruppo": ""})
        self.assertEqual(response.status_code, 200, response.content)
        self.voce.refresh_from_db()
        self.assertIsNone(self.voce.category_id)
        self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.voce.id, "categoria": self.area.id, "gruppo": "Richieste"})
        self.voce.refresh_from_db()
        self.assertEqual((self.voce.category_id, self.voce.group), (self.area.id, "Richieste"))

    def test_sposta_sottovoce_sotto_altra_voce(self):
        NavigationItem.objects.create(code="altro-modulo", label="Altro", section="topbar", route_name="admin_portale:index", order=20)
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.sotto.id, "padre": "admin_portale"})
        self.assertEqual(response.status_code, 200, response.content)
        self.sotto.refresh_from_db()
        self.assertEqual(self.sotto.parent_code, "admin_portale")
        # Un'app senza voce nel menu non e' una destinazione valida.
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.sotto.id, "padre": "nessuna_app"})
        self.assertEqual(response.status_code, 400)

    def test_categorie_crea_rinomina_elimina(self):
        response = self._come_admin("post", "admin_portale:api_menu_categoria_salva", {"nome": "Commerciale"})
        self.assertEqual(response.status_code, 200, response.content)
        nuova = ModuleCategory.objects.get(id=response.json()["id"])
        self.assertEqual(nuova.key, "commerciale")
        self.assertGreater(nuova.order, self.altra_area.order)
        self._come_admin("post", "admin_portale:api_menu_categoria_salva", {"id": nuova.id, "nome": "Vendite", "icona": "briefcase"})
        nuova.refresh_from_db()
        self.assertEqual((nuova.label, nuova.icon), ("Vendite", "briefcase"))
        # Con voci dentro non si elimina; vuota si'.
        response = self._come_admin("post", "admin_portale:api_menu_categoria_elimina", {"id": self.area.id})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(ModuleCategory.objects.filter(id=self.area.id).exists())
        response = self._come_admin("post", "admin_portale:api_menu_categoria_elimina", {"id": nuova.id})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ModuleCategory.objects.filter(id=nuova.id).exists())

    def test_riordina_la_barra(self):
        sola = NavigationItem.objects.create(code="sola", label="Sola", section="topbar", url_path="https://example.local/", order=1)
        response = self._come_admin("post", "admin_portale:api_menu_barra_riordina", {"elementi": [
            {"tipo": "categoria", "id": self.altra_area.id},
            {"tipo": "voce", "id": sola.id},
            {"tipo": "categoria", "id": self.area.id},
        ]})
        self.assertEqual(response.status_code, 200, response.content)
        self.altra_area.refresh_from_db()
        self.area.refresh_from_db()
        sola.refresh_from_db()
        self.assertEqual((self.altra_area.order, sola.order, self.area.order), (10, 20, 30))
        # Una voce dentro una tendina non si riordina da qui.
        self._come_admin("post", "admin_portale:api_menu_barra_riordina", {"elementi": [{"tipo": "voce", "id": self.voce.id}]})
        self.voce.refresh_from_db()
        self.assertEqual(self.voce.order, 10)
        response = self._come_admin("post", "admin_portale:api_menu_barra_riordina", {"elementi": [{"tipo": "boh", "id": 1}]})
        self.assertEqual(response.status_code, 400)

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

    def test_modifica_indirizzo_e_nuova_scheda(self):
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {
            "id": self.voce.id, "route_name": "", "url_path": "https://esterno.example/", "nuova_scheda": True,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.voce.refresh_from_db()
        self.assertEqual((self.voce.route_name, self.voce.url_path), ("", "https://esterno.example/"))
        self.assertTrue(self.voce.open_in_new_tab)
        # Tornando a una pagina del portale il permesso lo decide la pagina.
        self.voce.required_permission_code = PAGINA
        self.voce.save()
        self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.voce.id, "route_name": "dashboard_home"})
        self.voce.refresh_from_db()
        self.assertEqual((self.voce.route_name, self.voce.url_path, self.voce.required_permission_code), ("dashboard_home", "", ""))
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.voce.id, "route_name": "rotta_inesistente"})
        self.assertEqual(response.status_code, 400)
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.voce.id, "url_path": ""})
        self.assertEqual(response.status_code, 400)

    def test_link_esterno_tutti_o_solo_chi_ha_il_permesso(self):
        self._accendi()
        GroupPermissionGrant.objects.create(group=self.capo, permission_id=PAGINA, enabled=True)
        link = NavigationItem.objects.create(code="link-ext", label="Link", section="topbar", url_path="https://esterno.example/", order=5)
        voce = self._voce(dati_menu(), link.id)
        self.assertTrue(voce["esterno"])
        self.assertIn(self.capo.id, voce["ruoli"])
        self.assertIn(PAGINA, [p["code"] for p in dati_menu()["permessi"]])
        # Un permesso che non protegge nessuna pagina non lo concede nessun ruolo: rifiutato.
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": link.id, "permesso": VECCHIO})
        self.assertEqual(response.status_code, 400)
        response = self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": link.id, "permesso": PAGINA})
        self.assertEqual(response.status_code, 200, response.content)
        link.refresh_from_db()
        self.assertEqual(link.required_permission_code, PAGINA)
        voce = self._voce(dati_menu(), link.id)
        self.assertEqual(voce["permesso"], PAGINA)
        self.assertIn(self.capo.id, voce["ruoli"])
        if self.base is not None:
            self.assertNotIn(self.base.id, voce["ruoli"])
        # Sulle pagine del portale il permesso non si sceglie qui.
        self._come_admin("post", "admin_portale:api_menu_voce_salva", {"id": self.sotto.id, "permesso": PAGINA})
        self.sotto.refresh_from_db()
        self.assertEqual(self.sotto.required_permission_code, "")

    def test_avanzati_link_esterno_senza_permesso_lo_vedono_tutti(self):
        NavigationItem.objects.create(code="link-ext", label="Link", section="topbar", url_path="https://esterno.example/", order=5)
        response = self._come_admin("get", "admin_portale:navigation_builder_avanzato", {"advanced": "1"})
        self.assertContains(response, "Link esterno senza permesso")

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
