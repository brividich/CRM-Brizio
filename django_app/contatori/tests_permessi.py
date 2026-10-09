"""Consultazione e gestione separate (ACL v2). Dati sintetici."""
from importlib import import_module
from unittest import mock

from django.apps import apps as django_apps
from django.test import TestCase
from django.urls import reverse

from .models import Fattura, ImpostazioniSNMP, Macchina
from .tests import _AuthedClientMixin

MIG = import_module("contatori.migrations.0025_acl_consultazione_gestione")


class SolaLetturaTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        p1 = mock.patch("contatori.permessi.puo_gestire", return_value=False)
        p2 = mock.patch("contatori.templatetags.contatori_acl._puo_gestire", return_value=False)
        p1.start(), p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-P1", host="192.0.2.61")

    def test_scritture_bloccate(self):
        r = self.client.post(reverse("contatori:fattura_nuova"), {"numero": "X"})
        self.assertRedirects(r, reverse("contatori:dashboard"))
        self.assertFalse(Fattura.objects.exists())
        for url in (reverse("contatori:importa_lettura"), reverse("contatori:macchina_edit", args=[self.m.pk]),
                    reverse("contatori:discovery"), reverse("contatori:snmp_profilo_nuovo")):
            self.assertRedirects(self.client.get(url), reverse("contatori:dashboard"), msg_prefix=url)

    def test_config_globale_solo_in_lettura(self):
        cfg = ImpostazioniSNMP.get_solo()
        r = self.client.get(reverse("contatori:macchine"))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "+ Nuova MFC")
        self.assertNotContains(r, "Configurazione SNMP globale")
        self.client.post(reverse("contatori:macchine"), {"community": "x", "port": 1, "timeout": 1, "version": "v1"})
        cfg.refresh_from_db()
        self.assertNotEqual(cfg.port, 1)

    def test_pulsanti_nascosti(self):
        r = self.client.get(reverse("contatori:dashboard"))
        self.assertNotContains(r, "Leggi MFC ora")
        self.assertNotContains(r, "+ Inserisci")
        self.assertNotContains(r, ">Discovery<")
        r = self.client.get(reverse("contatori:macchina", args=[self.m.pk]))
        self.assertNotContains(r, "+ Nuova lettura")


class GestioneTests(_AuthedClientMixin, TestCase):
    def test_superuser_vede_i_pulsanti(self):
        r = self.client.get(reverse("contatori:dashboard"))
        self.assertContains(r, "Leggi MFC ora")
        self.assertContains(r, ">Discovery<")


class MigrazioneAclTests(TestCase):
    def setUp(self):
        from core.models import PermissionDefinition, RoutePermissionBinding
        RoutePermissionBinding.objects.filter(route_name__startswith="contatori:").delete()
        for code in ("contatori.dashboard.view", "contatori.macchina.edit"):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"module": "contatori", "label": code})

    def test_binding_solo_dove_mancano_e_grant_ereditati(self):
        from core.models import RolePermissionGrant, RoutePermissionBinding as B, UserPermissionGrant
        B.objects.create(route_name="contatori:dashboard", path_pattern="", match_strategy="exact",
                         permission_id="contatori.dashboard.view", is_active=True)
        B.objects.create(route_name="contatori:analisi", path_pattern="", match_strategy="exact",
                         permission_id="contatori.dashboard.view", is_active=False)
        RolePermissionGrant.objects.create(legacy_role_id=7, permission_id="contatori.dashboard.view", enabled=True)
        RolePermissionGrant.objects.create(legacy_role_id=8, permission_id="contatori.dashboard.view", enabled=False)
        UserPermissionGrant.objects.create(legacy_user_id=40, permission_id="contatori.macchina.edit", enabled=True)

        MIG.avanti(django_apps, None)
        MIG.avanti(django_apps, None)  # idempotente

        self.assertEqual(B.objects.get(route_name="contatori:dashboard").permission_id, "contatori.dashboard.view")
        self.assertFalse(B.objects.get(route_name="contatori:analisi").is_active)  # disattivato a mano: resta
        self.assertEqual(B.objects.get(route_name="contatori:fattura_nuova").permission_id, MIG.GESTIONE)
        self.assertEqual(B.objects.get(route_name="contatori:snmp_centrale").permission_id, MIG.VIEW)
        self.assertTrue(RolePermissionGrant.objects.get(legacy_role_id=7, permission_id=MIG.VIEW).enabled)
        self.assertFalse(RolePermissionGrant.objects.filter(legacy_role_id=8, permission_id=MIG.VIEW).exists())
        self.assertTrue(UserPermissionGrant.objects.get(legacy_user_id=40, permission_id=MIG.GESTIONE).enabled)

    def test_tutte_le_route_del_modulo_sono_coperte(self):
        from django.urls import get_resolver
        modulo = {k for k, _ in get_resolver().namespace_dict["contatori"][1].reverse_dict.items() if isinstance(k, str)}
        self.assertTrue(modulo)
        mig27 = import_module("contatori.migrations.0027_acl_verifica_oid")
        mig29 = import_module("contatori.migrations.0029_acl_wizard_dispositivo")
        self.assertEqual(modulo - set(MIG.ROUTE_VIEW) - set(MIG.ROUTE_GESTIONE) - set(mig27.ROUTE_GESTIONE)
                         - set(mig29.ROUTE_GESTIONE), set(),
                         "Route nuova senza binding ACL: aggiungila a ROUTE_VIEW o ROUTE_GESTIONE")
