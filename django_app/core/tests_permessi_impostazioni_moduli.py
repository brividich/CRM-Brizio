"""Impostazioni dei moduli con un'azione propria nella matrice (core/permessi/impostazioni.py).

Dati sintetici: ruoli e permessi si creano nel test.
"""
from __future__ import annotations

import importlib
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from core.models import (
    AccessGroup,
    GroupPermissionGrant,
    PermissionDefinition,
    RoutePermissionBinding,
    RuoloPermessoModulo,
)
from core.permessi.impostazioni import AZIONE_IMPOSTAZIONI, IMPOSTAZIONI, impostazioni_o
from core.permessi.preset import PRESETS
from core.permessi.registro import moduli_registrati
from core.permessi.sync import codici_desiderati, codici_per_modulo

DPI = IMPOSTAZIONI["dpi"].codici


class RegistroImpostazioniTests(TestCase):
    def test_ogni_modulo_della_tabella_ha_l_azione(self):
        registrati = moduli_registrati()
        for chiave, pagine in IMPOSTAZIONI.items():
            self.assertIn(chiave, registrati, chiave)
            spec = registrati[chiave]
            self.assertIn(AZIONE_IMPOSTAZIONI, spec.azioni, chiave)
            self.assertEqual(dict(spec.pagine_azioni)[AZIONE_IMPOSTAZIONI], pagine.codici, chiave)
            for code in pagine.codici:
                self.assertIn(code, spec.codici_acl, f"{chiave}: {code}")

    def test_un_codice_sta_in_un_solo_modulo(self):
        visti: dict[str, str] = {}
        for chiave, pagine in IMPOSTAZIONI.items():
            for code in pagine.codici:
                self.assertNotIn(code, visti, f"{code} in {visti.get(code)} e {chiave}")
                visti[code] = chiave

    def test_i_codici_finiscono_nel_modulo_giusto(self):
        for code in DPI:
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": "dpi"})
        PermissionDefinition.objects.get_or_create(
            code="formazione.impostazioni.manage", defaults={"label": "f", "module": "anagrafica"}
        )
        per_modulo = codici_per_modulo()
        for code in DPI:
            self.assertIn(code, per_modulo["dpi"])
        self.assertIn("formazione.impostazioni.manage", per_modulo["formazione"])
        self.assertNotIn("formazione.impostazioni.manage", per_modulo["anagrafica"])


class MatriceImpostazioniDpiTests(TestCase):
    def setUp(self):
        cache.clear()
        for code in (*DPI, "dpi.sintetico_gestione.manage"):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": "dpi"})
        self.ruolo = AccessGroup.objects.create(code="t-dpi", label="Gestore DPI (test)", priority=300)

    def _cella(self, azione, consentito=True):
        RuoloPermessoModulo.objects.create(
            ruolo=self.ruolo, modulo="dpi", azione=azione, ambito="tutti", consentito=consentito
        )

    def test_gestire_non_apre_le_impostazioni(self):
        self._cella("gestire")
        desiderati, _ = codici_desiderati(self.ruolo)
        self.assertIn("dpi.sintetico_gestione.manage", desiderati)
        self.assertFalse(set(DPI) & desiderati)

    def test_impostazioni_apre_le_pagine_del_catalogo(self):
        self._cella(AZIONE_IMPOSTAZIONI)
        desiderati, _ = codici_desiderati(self.ruolo)
        self.assertTrue(set(DPI) <= desiderati)
        self.assertNotIn("dpi.sintetico_gestione.manage", desiderati)


class GateViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="t.impostazioni", password="x")
        self.request = RequestFactory().get("/dpi/impostazioni/")
        self.request.user = self.user

    def test_sistema_spento_decide_il_controllo_storico(self):
        with mock.patch("core.permessi.motore.sistema_ruoli_attivo", return_value=False):
            self.assertTrue(impostazioni_o(self.request, "dpi", lambda r: True))
            self.assertFalse(impostazioni_o(self.request, "dpi", lambda r: False))

    def test_sistema_acceso_decide_il_permesso_delle_impostazioni(self):
        with mock.patch("core.permessi.motore.sistema_ruoli_attivo", return_value=True), \
                mock.patch("core.acl_v2.request_has_permission_code", side_effect=lambda r, c: c == DPI[0]):
            self.assertTrue(impostazioni_o(self.request, "dpi", lambda r: False))
        with mock.patch("core.permessi.motore.sistema_ruoli_attivo", return_value=True), \
                mock.patch("core.acl_v2.request_has_permission_code", return_value=False):
            self.assertFalse(impostazioni_o(self.request, "dpi", lambda r: True))

    def test_modulo_senza_impostazioni_lascia_il_controllo_storico(self):
        with mock.patch("core.permessi.motore.sistema_ruoli_attivo", return_value=True):
            self.assertTrue(impostazioni_o(self.request, "modulo_che_non_esiste", lambda r: True))


class PresetImpostazioniTests(TestCase):
    def test_chi_gestisce_da_preset_riceve_le_impostazioni(self):
        for preset in PRESETS:
            for modulo, azioni in preset.celle.items():
                if modulo in IMPOSTAZIONI and "gestire" in azioni:
                    self.assertEqual(azioni.get(AZIONE_IMPOSTAZIONI), azioni["gestire"], f"{preset.codice} {modulo}")


class Migrazione0097Tests(TestCase):
    """La migrazione lega le rotte, copia «gestire» su «impostazioni» e accende i permessi."""

    def setUp(self):
        self.mig = importlib.import_module("core.migrations.0097_impostazioni_moduli_azione_propria")
        PermissionDefinition.objects.get_or_create(code="rentri.route.view", defaults={"label": "r", "module": "rentri"})
        RoutePermissionBinding.objects.update_or_create(
            route_name="rentri_impostazioni", path_pattern="",
            defaults={"permission_id": "rentri.route.view", "match_strategy": "exact", "is_active": True},
        )
        self.gestore = AccessGroup.objects.create(code="t-rentri-g", label="Gestore RENTRI (test)", priority=300)
        self.lettore = AccessGroup.objects.create(code="t-rentri-l", label="Lettore RENTRI (test)", priority=200)
        RuoloPermessoModulo.objects.create(ruolo=self.gestore, modulo="rentri", azione="gestire", ambito="team")
        RuoloPermessoModulo.objects.create(ruolo=self.lettore, modulo="rentri", azione="vedere", ambito="tutti")
        # Ruoli gia' sincronizzati dalla matrice: hanno grant «matrice ruoli».
        for ruolo in (self.gestore, self.lettore):
            GroupPermissionGrant.objects.create(
                group=ruolo, permission_id="rentri.route.view", enabled=True, note="matrice ruoli"
            )

    def test_avanti(self):
        self.mig.avanti(django_apps, None)
        binding = RoutePermissionBinding.objects.get(route_name="rentri_impostazioni", path_pattern="")
        self.assertEqual(binding.permission_id, "rentri.impostazioni.manage")
        cella = RuoloPermessoModulo.objects.get(ruolo=self.gestore, modulo="rentri", azione=AZIONE_IMPOSTAZIONI)
        self.assertTrue(cella.consentito)
        self.assertEqual(cella.ambito, "team")
        self.assertFalse(
            RuoloPermessoModulo.objects.filter(ruolo=self.lettore, modulo="rentri", azione=AZIONE_IMPOSTAZIONI).exists()
        )
        self.assertTrue(GroupPermissionGrant.objects.filter(
            group=self.gestore, permission_id="rentri.impostazioni.manage", enabled=True
        ).exists())
        self.assertFalse(GroupPermissionGrant.objects.filter(
            group=self.lettore, permission_id="rentri.impostazioni.manage"
        ).exists())
        # Rieseguirla non duplica nulla.
        self.mig.avanti(django_apps, None)
        self.assertEqual(
            RuoloPermessoModulo.objects.filter(ruolo=self.gestore, modulo="rentri", azione=AZIONE_IMPOSTAZIONI).count(), 1
        )


class Migrazione0098Tests(TestCase):
    """0098: le pagine che non sono impostazioni tornano com'erano."""

    def setUp(self):
        self.mig = importlib.import_module("core.migrations.0098_impostazioni_solo_pagina_impostazioni")
        for code in ("anagrafica.skillmatrix.manage", "anagrafica.impostazioni.manage",
                     "assenze.assenze.manage", "legacy.assenze.admin_assenze"):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": code.split(".")[1]})
        RoutePermissionBinding.objects.update_or_create(
            route_name="anagrafica:skm_impostazioni", path_pattern="",
            defaults={"permission_id": "anagrafica.impostazioni.manage", "match_strategy": "exact", "is_active": True,
                      "note": "[SKM] x [CORE_0097] impostazioni con azione propria (era anagrafica.skillmatrix.manage)"},
        )
        RoutePermissionBinding.objects.update_or_create(
            route_name="anagrafica:sicurezza_operativa_config", path_pattern="",
            defaults={"permission_id": "anagrafica.impostazioni.manage", "match_strategy": "exact", "is_active": True,
                      "note": "[CORE_0097] impostazioni con azione propria"},
        )
        self.capo = AccessGroup.objects.create(code="t-capo-ass", label="Capo (test)", priority=300)
        GroupPermissionGrant.objects.create(group=self.capo, permission_id="assenze.assenze.manage",
                                            enabled=True, note="matrice ruoli")
        RuoloPermessoModulo.objects.create(ruolo=self.capo, modulo="assenze", azione="gestire", ambito="team")
        RuoloPermessoModulo.objects.create(ruolo=self.capo, modulo="assenze", azione=AZIONE_IMPOSTAZIONI,
                                           ambito="team", consentito=False)

    def test_avanti(self):
        self.mig.avanti(django_apps, None)
        skm = RoutePermissionBinding.objects.get(route_name="anagrafica:skm_impostazioni", path_pattern="")
        self.assertEqual(skm.permission_id, "anagrafica.skillmatrix.manage")
        self.assertEqual(skm.note, "[SKM] x")
        self.assertFalse(RoutePermissionBinding.objects.filter(route_name="anagrafica:sicurezza_operativa_config").exists())
        imp = RoutePermissionBinding.objects.get(route_name="assenze_impostazioni", path_pattern="")
        self.assertEqual(imp.permission_id, "assenze.impostazioni.manage")
        # Il capo gestisce (certificazione presenza, area HR) ma non apre le Impostazioni.
        codici = set(GroupPermissionGrant.objects.filter(group=self.capo, enabled=True).values_list("permission_id", flat=True))
        self.assertTrue({"assenze.assenze.manage", "legacy.assenze.admin_assenze"} <= codici)
        self.assertNotIn("assenze.impostazioni.manage", codici)
