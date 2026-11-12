"""Matrice dei ruoli: dal percorso di una pagina alla riga del suo permesso."""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.models import AccessGroup, PermissionDefinition, RoutePermissionBinding
from core.permessi.percorsi import normalizza_percorso, trova_permessi_percorso
from core.tests_permessi import PersoneMixin


class NormalizzaPercorsoTests(TestCase):
    def test_toglie_indirizzo_e_query(self):
        for testo in (
            "assenze/calendario",
            "/assenze/calendario",
            " assenze/calendario?mese=11#giorno ",
            "hub.azienda-sintetica.it/assenze/calendario",
            "https://hub.azienda-sintetica.it/assenze/calendario?mese=11",
        ):
            self.assertEqual(normalizza_percorso(testo), "/assenze/calendario", testo)

    def test_vuoto(self):
        self.assertEqual(normalizza_percorso("   "), "")


class TrovaPermessiPercorsoTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        RoutePermissionBinding.objects.filter(route_name__startswith="assenze_calendario").delete()
        RoutePermissionBinding.objects.filter(path_pattern__startswith="/assenze/calendario").delete()
        self.calendario, _ = PermissionDefinition.objects.update_or_create(
            code="assenze.calendario_prova.view", defaults={"label": "Calendario prova", "module": "assenze", "is_active": True}
        )
        RoutePermissionBinding.objects.create(route_name="assenze_calendario", permission=self.calendario, is_active=True)

    def test_pagina_esatta_e_la_prima_riga_con_il_suo_permesso(self):
        righe = trova_permessi_percorso("assenze/calendario")
        self.assertTrue(righe[0]["esatta"])
        self.assertEqual(righe[0]["percorso"], "/assenze/calendario")
        self.assertEqual(righe[0]["code"], "assenze.calendario_prova.view")
        self.assertEqual(righe[0]["modulo"], "assenze")
        self.assertTrue(righe[0]["modulo_nome"])

    def test_piu_righe_quando_il_percorso_ne_contiene_altre(self):
        percorsi = [r["percorso"] for r in trova_permessi_percorso("assenze/calendario")]
        self.assertIn("/assenze/calendario/partial", percorsi)
        self.assertEqual(len(percorsi), len(set(percorsi)))

    def test_vale_anche_per_un_percorso_con_id(self):
        RoutePermissionBinding.objects.create(
            route_name="admin_portale:ruoli_portale_ruolo", permission=self.calendario, is_active=True
        )
        righe = trova_permessi_percorso("/admin-portale/ruoli-portale/ruolo/123/")
        self.assertEqual(righe[0]["code"], "assenze.calendario_prova.view")
        self.assertTrue(righe[0]["esatta"])

    def test_pagina_senza_permesso_lo_dice(self):
        RoutePermissionBinding.objects.filter(permission=self.calendario).delete()
        riga = trova_permessi_percorso("assenze/calendario")[0]
        self.assertEqual(riga["code"], "")
        self.assertEqual(riga["modulo"], "")

    def test_percorso_inesistente(self):
        self.assertEqual(trova_permessi_percorso("pagina/che-non-esiste-sintetica"), [])


class EndpointPercorsoTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("admin_portale:ruoli_portale_percorso")

    def test_non_connesso_json_401(self):
        resp = self.client.get(self.url, {"q": "assenze/calendario"}, headers={"accept": "application/json"})
        self.assertEqual(resp.status_code, 401)

    def test_non_amministratore_json_403(self):
        user, _ = self.persona("Operatore sintetico")
        self.client.force_login(user)
        resp = self.client.get(self.url, {"q": "assenze/calendario"}, headers={"accept": "application/json"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp["Content-Type"].split(";")[0], "application/json")

    def test_amministratore_riceve_le_righe_e_la_pagina_ha_la_ricerca(self):
        admin, _ = self.persona("Amministratore sintetico", superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(self.url, {"q": "assenze/calendario"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["righe"])
        ruolo = AccessGroup.objects.create(code="pg_cerca", label="Ruolo prova", priority=300)
        pagina = self.client.get(reverse("admin_portale:ruoli_portale"), {"tab": "matrice", "ruolo": ruolo.id})
        self.assertContains(pagina, 'id="rp-cerca-testo"')
        self.assertContains(pagina, self.url)
