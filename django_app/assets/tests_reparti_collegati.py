"""Reparti scritti sugli asset collegati ai capi, co-capi, moduli «IT e rete» e «Fornitori e contratti». Dati sintetici."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, TestCase
from django.urls import reverse

from anagrafica.models import AreaAziendale, Reparto
from core.models import AccessGroup, AccessGroupMembership, RuoloPermessoModulo
from core.permessi.cache import invalida_permessi
from core.permessi.preset import PRESETS, applica_preset
from core.permessi.registro import modulo as modulo_registrato
from core.tests_permessi import PersoneMixin, ensure_anagrafica_table

from .models import Asset, RepartoAssetCollegato
from .registro_permessi import CODICI_FORNITORI, CODICI_IT, CODICI_MANUTENZIONE, MODULO_FORNITORI, MODULO_IT
from .services import reparti_collegati, responsabile_asset, visibilita


class RepartiCollegatiTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        applica_preset()
        ensure_anagrafica_table()
        self.capo, self.capo_legacy = self.persona("Capo Sintetico")
        self.vice, self.vice_legacy = self.persona("Vice Sintetico")
        ruolo = AccessGroup.objects.create(code="syn-car", label="CAR sintetico", priority=900)
        RuoloPermessoModulo.objects.create(ruolo=ruolo, modulo="assets", azione="vedere", ambito="propri")
        for legacy in (self.capo_legacy, self.vice_legacy):
            AccessGroupMembership.objects.create(group=ruolo, legacy_user_id=legacy.id)
        with connection.cursor() as c:
            for pid, nome, utente in ((9201, "Capo", self.capo_legacy.id), (9202, "Vice", self.vice_legacy.id)):
                c.execute(
                    "INSERT INTO anagrafica_dipendenti (id, nome, cognome, reparto, utente_id) VALUES (%s, %s, %s, %s, %s)",
                    [pid, nome, "Sintetico", "LOGISTICA", utente],
                )
        self.logistica = Reparto.objects.create(nome="LOGISTICA", caporeparto_legacy_id=9201)
        self.logistica.responsabili.add(9202)
        self.area = AreaAziendale.objects.create(nome="RETTIFICA", reparto=self.logistica)
        nuovo = Asset.objects.create
        self.muletto = nuovo(asset_tag="SYN-MUL", name="Muletto", asset_type=Asset.TYPE_OTHER, reparto="LOG")
        self.rettifica = nuovo(asset_tag="SYN-RET", name="Rettifica", asset_type=Asset.TYPE_WORK_MACHINE,
                               reparto="rettifiche")
        self.ufficiale = nuovo(asset_tag="SYN-LOG", name="Reggiatrice", asset_type=Asset.TYPE_OTHER,
                               reparto="Logistica")
        self.attiva_sistema()

    def tearDown(self):
        cache.clear()
        invalida_permessi()

    def _request(self, user):
        request = RequestFactory().get("/assets/")
        request.user = self.ricarica(user)
        request.session = {}
        return request

    def test_testo_non_riconosciuto_non_arriva_a_nessuno_finche_non_si_collega(self):
        self.assertEqual(visibilita.ids_visibili(self._request(self.capo)), {self.ufficiale.id})
        reparti_collegati.collega("LOG", f"r:{self.logistica.pk}", utente="syn")
        reparti_collegati.collega("rettifiche", f"a:{self.area.pk}", utente="syn")
        self.assertEqual(
            visibilita.ids_visibili(self._request(self.capo)), {self.ufficiale.id, self.muletto.id, self.rettifica.id}
        )
        resp = responsabile_asset.responsabile(self.muletto, {"log": (9201, "Capo Sintetico")})
        self.assertTrue(resp.da_caporeparto)

    def test_co_capo_vede_le_macchine_del_reparto_come_il_capo(self):
        self.assertEqual(visibilita.ids_visibili(self._request(self.vice)), {self.ufficiale.id})
        self.assertEqual(responsabile_asset.utenti_responsabili(self.ufficiale), {self.capo_legacy.id, self.vice_legacy.id})

    def test_area_senza_responsabile_segue_capo_e_co_capi_del_reparto(self):
        persone = responsabile_asset.persone_per_reparto()
        self.assertEqual(persone["rettifica"], {9201, 9202})

    def test_righe_da_collegare_prima_con_proposta(self):
        righe, senza = reparti_collegati.righe()
        stati = {r.testo: r.stato for r in righe}
        self.assertEqual(stati["LOG"], reparti_collegati.STATO_DA_COLLEGARE)
        self.assertEqual(stati["Logistica"], reparti_collegati.STATO_RICONOSCIUTO)
        self.assertEqual(righe[-1].testo, "Logistica")
        proposta = {r.testo: r.suggerita for r in righe}["rettifiche"]
        self.assertEqual(proposta, f"a:{self.area.pk}")
        self.assertEqual(senza, 0)
        self.assertEqual(reparti_collegati.testi_da_collegare(), 2)

    def test_togliere_il_collegamento_e_unita_non_valida(self):
        reparti_collegati.collega("LOG", f"r:{self.logistica.pk}")
        reparti_collegati.collega(" log ", "")
        self.assertFalse(RepartoAssetCollegato.objects.exists())
        with self.assertRaises(ValueError):
            reparti_collegati.collega("LOG", "x:1")

    def test_tab_impostazioni_collega_un_reparto(self):
        admin = get_user_model().objects.create_superuser("syn-admin", "admin@example.test", "x")
        self.client.force_login(admin)
        url = reverse("assets:gestione_admin")
        pagina = self.client.get(url + "?tab=reparti")
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "Reparti e capi")
        self.assertContains(pagina, "Da collegare")
        risposta = self.client.post(url, {"action": "collega_reparto_asset", "testo": "LOG", "unita": f"r:{self.logistica.pk}"})
        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(RepartoAssetCollegato.objects.get().reparto, self.logistica)


class ModuliItFornitoriTests(TestCase):
    def test_registrati_con_le_loro_pagine(self):
        self.assertIsNotNone(modulo_registrato(MODULO_IT))
        self.assertIsNotNone(modulo_registrato(MODULO_FORNITORI))
        self.assertIn("legacy.assets.assets_software_licenses", CODICI_IT)
        self.assertIn("legacy.assets.assets_assistance_contracts", CODICI_FORNITORI)
        self.assertFalse(set(CODICI_FORNITORI) & set(CODICI_MANUTENZIONE))

    def test_preset_it_solo_a_chi_ha_l_inventario_su_tutti(self):
        for preset in PRESETS:
            assets = {a: amb for a, amb in preset.celle.get("assets", {}).items() if a != "impostazioni"}
            attese = {a: amb for a, amb in assets.items() if amb == "tutti"}
            self.assertEqual(preset.celle.get(MODULO_IT, {}), attese, preset.chiave)
            if "assets_manutenzione" in preset.celle:
                self.assertEqual(preset.celle[MODULO_FORNITORI], preset.celle["assets_manutenzione"], preset.chiave)


class PagineLetturaForzateTests(TestCase):
    def test_scheda_asset_si_apre_con_vedere_anche_con_rotte_bulk_sotto(self):
        from core.models import PermissionDefinition, RoutePermissionBinding
        from core.permessi.sync import capacita_permessi

        perm, _ = PermissionDefinition.objects.get_or_create(
            code="legacy.assets.assets_view", defaults={"module": "assets", "label": "Dettaglio asset"}
        )
        RoutePermissionBinding.objects.get_or_create(
            path_pattern="/assets/view/", match_strategy="prefix", defaults={"permission": perm}
        )
        self.assertEqual(capacita_permessi()["legacy.assets.assets_view"], "lettura")
