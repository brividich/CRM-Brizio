"""Pannello Reception in «Ruoli e permessi»: Vedere, Creare/Modificare, Impostazioni. Dati sintetici."""
from __future__ import annotations

import importlib

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import (
    AccessGroup, GroupPermissionGrant, PermissionDefinition, RoutePermissionBinding, RuoloPermessoModulo, UserOnboarding,
)
from core.permessi.registro import moduli_registrati
from core.permessi.sync import capacita_permessi, codici_desiderati

PARTENZA = "legacy.portale_esterno.portale_esterno"
GESTIONE = "reception.pannello.manage"
IMPOSTAZIONI = "reception.impostazioni.manage"
migrazione = importlib.import_module("reception.migrations.0006_permessi_pannello")


class Base(TestCase):
    def setUp(self):
        PermissionDefinition.objects.get_or_create(code=PARTENZA, defaults={"label": "Portale esterno ospiti", "module": "portale_esterno"})


class MatriceTests(Base):
    def test_modulo_con_nome_giusto_e_azioni(self):
        spec = moduli_registrati()["portale_ospiti"]
        self.assertEqual(spec.nome, "Reception e visitatori")
        self.assertIn("impostazioni", spec.azioni)
        cap = capacita_permessi()
        self.assertEqual((cap[PARTENZA], cap[GESTIONE]), ("lettura", "modifica"))

    def test_ogni_azione_accende_le_sue_pagine(self):
        casi = {"vedere": {PARTENZA}, "creare": {GESTIONE}, "impostazioni": {IMPOSTAZIONI}}
        for azione, attesi in casi.items():
            ruolo = AccessGroup.objects.create(code=f"t-rc-{azione}", label=f"Prova {azione}", priority=100)
            RuoloPermessoModulo.objects.create(ruolo=ruolo, modulo="portale_ospiti", azione=azione, ambito="tutti")
            desiderati, _ = codici_desiderati(ruolo)
            codici = {c for c in desiderati if c in (PARTENZA, GESTIONE, IMPOSTAZIONI)}
            self.assertEqual(codici, attesi, azione)


class MigrazioneTests(Base):
    def test_sposta_binding_e_non_toglie_niente(self):
        RoutePermissionBinding.objects.filter(route_name__in=list(migrazione.ROTTE) + ["reception:cruscotto"]).delete()
        for rotta in ("reception:registra", "reception:impostazioni", "reception:cruscotto"):
            RoutePermissionBinding.objects.create(route_name=rotta, path_pattern="", match_strategy="exact", permission_id=PARTENZA,
                                                  source_app="reception", priority=80, is_active=True, note="[RECEPTION_0002] copiato")
        RoutePermissionBinding.objects.filter(route_name="reception:ditte").delete()
        RoutePermissionBinding.objects.create(route_name="reception:ditte", path_pattern="", match_strategy="exact", permission_id=PARTENZA,
                                              source_app="manuale", priority=80, is_active=True, note="scelta a mano")
        gruppo = AccessGroup.objects.create(code="t-rc-rec", label="Reception (prova)", priority=100)
        GroupPermissionGrant.objects.create(group=gruppo, permission_id=PARTENZA, enabled=True)
        RuoloPermessoModulo.objects.create(ruolo=gruppo, modulo="portale_ospiti", azione="gestire", ambito="tutti")

        migrazione.avanti(django_apps, None)

        permesso = dict(RoutePermissionBinding.objects.filter(route_name__startswith="reception:").values_list("route_name", "permission_id"))
        self.assertEqual(permesso["reception:registra"], GESTIONE)
        self.assertEqual(permesso["reception:impostazioni"], IMPOSTAZIONI)
        self.assertEqual(permesso["reception:cruscotto"], PARTENZA)
        self.assertEqual(permesso["reception:ditte"], PARTENZA)  # personalizzazione a mano: non si tocca
        self.assertEqual(set(GroupPermissionGrant.objects.filter(group=gruppo, enabled=True).values_list("permission_id", flat=True)),
                         {PARTENZA, GESTIONE, IMPOSTAZIONI})
        self.assertEqual(set(RuoloPermessoModulo.objects.filter(ruolo=gruppo).values_list("azione", flat=True)),
                         {"gestire", "vedere", "creare", "modificare", "cancellare", "impostazioni"})
        migrazione.avanti(django_apps, None)  # rieseguibile
        self.assertEqual(RuoloPermessoModulo.objects.filter(ruolo=gruppo).count(), 6)


class MenuTests(TestCase):
    def test_superuser_vede_tutte_le_voci(self):
        user = get_user_model().objects.create_superuser("adm_rcp", "adm@example.local", "x")
        UserOnboarding.objects.get_or_create(user=user, defaults={"completed": True})
        self.client.force_login(user)
        r = self.client.get(reverse("reception:cruscotto"))
        for etichetta in ("Oggi", "Inviti", "Storico", "Configurazione", "Registra ingresso"):
            self.assertContains(r, etichetta)

    def test_menu_filtrato_per_permesso(self):
        from unittest.mock import patch

        from django.test import RequestFactory

        from reception.views import _menu

        user = get_user_model().objects.create_user("op_rcp", "op@example.local", "x")
        request = RequestFactory().get("/reception/")
        request.user = user
        ammesse = {"/reception/", "/reception/storico/", "/reception/richieste/"}
        with patch("core.middleware.acl_allows_path", side_effect=lambda url, **k: url in ammesse):
            menu = _menu(request, "richieste")
        self.assertEqual([v["chiave"] for v in menu], ["oggi", "inviti", "storico"])
        inviti = menu[1]
        self.assertEqual((inviti["nome"], inviti["attiva"]), ("richieste", True))
        self.assertEqual([s["nome"] for s in inviti["schede"]], ["richieste"])
