"""core 0100: le pagine Impostazioni rimaste sul permesso condiviso hanno un binding proprio."""
from __future__ import annotations

import importlib

from django.apps import apps as django_apps
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.acl_v2 import _find_canonical_binding
from core.models import PermissionDefinition, RolePermissionGrant, RoutePermissionBinding
from core.permessi.impostazioni import IMPOSTAZIONI

migrazione = importlib.import_module("core.migrations.0100_impostazioni_rotte_proprie")


class ImpostazioniRotteProprieTests(TestCase):
    def setUp(self):
        cache.clear()
        for _rotta, code, fonti, modulo in migrazione.ROTTE + migrazione.ROTTE_PROPRIE:
            for c in (code, *fonti):
                PermissionDefinition.objects.get_or_create(code=c, defaults={"label": c, "module": modulo})
        # Prima: la pagina impostazioni del diario stava sotto il prefisso della lista.
        PermissionDefinition.objects.get_or_create(
            code="legacy.diario_preposto.diario_preposto_lista",
            defaults={"label": "lista", "module": "diario_preposto"},
        )
        RoutePermissionBinding.objects.create(
            route_name="", path_pattern="/diario-preposto", match_strategy="prefix",
            permission_id="legacy.diario_preposto.diario_preposto_lista", priority=100, is_active=True,
        )

    def test_tabella_e_migrazione_allineate(self):
        for rotta, code, _fonti, _modulo in migrazione.ROTTE:
            moduli = [k for k, p in IMPOSTAZIONI.items() if rotta in p.rotte]
            self.assertEqual(len(moduli), 1, rotta)
            self.assertEqual(IMPOSTAZIONI[moduli[0]].codici[0], code, rotta)

    def test_rotte_legate_al_permesso_delle_impostazioni(self):
        migrazione.avanti(django_apps, None)
        for rotta, code, _fonti, _modulo in migrazione.ROTTE + migrazione.ROTTE_PROPRIE:
            binding, come = _find_canonical_binding(route_name=rotta, path_norm=reverse(rotta).rstrip("/").lower())
            self.assertIsNotNone(binding, rotta)
            self.assertEqual(binding.permission_id, code, rotta)
            self.assertEqual(come, "route_name", rotta)

    def test_specifiche_pagina_principale_lettura_nonostante_il_namespace(self):
        from core.permessi.sync import capacita_permessi

        PermissionDefinition.objects.get_or_create(
            code="gestione_specifiche.specifica.view", defaults={"label": "x", "module": "gestione_specifiche"}
        )
        RoutePermissionBinding.objects.create(
            route_name="gestione_specifiche:lista", path_pattern="", match_strategy="exact",
            permission_id="gestione_specifiche.specifica.view", priority=80, is_active=True,
        )
        self.assertEqual(capacita_permessi()["gestione_specifiche.specifica.view"], "lettura")

    def test_pagina_principale_forzata_a_lettura(self):
        from core.permessi.sync import capacita_permessi

        PermissionDefinition.objects.get_or_create(
            code="legacy.tickets.tickets_dashboard", defaults={"label": "x", "module": "tickets"}
        )
        RoutePermissionBinding.objects.create(
            route_name="", path_pattern="/tickets", match_strategy="prefix",
            permission_id="legacy.tickets.tickets_dashboard", priority=100, is_active=True,
        )
        self.assertEqual(capacita_permessi()["legacy.tickets.tickets_dashboard"], "lettura")

    def test_concessioni_storiche_copiate(self):
        RolePermissionGrant.objects.create(legacy_role_id=7, permission_id="legacy.dpi.dpi_impostazioni", enabled=True)
        migrazione.avanti(django_apps, None)
        migrazione.avanti(django_apps, None)  # idempotente
        self.assertEqual(
            RolePermissionGrant.objects.filter(legacy_role_id=7, permission_id="dpi.impostazioni.view").count(), 1
        )
