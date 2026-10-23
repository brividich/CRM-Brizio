"""Pagine personali che il ruolo base deve ricevere dalla matrice (accessi negati in produzione).

Home, «Le mie assenze», richiesta assenza, controllo corsi, notizie, schede di sicurezza.
Dati sintetici: i permessi si creano nel test come li crea il bootstrap.
"""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase

from core.models import AccessGroup, PermissionDefinition
from core.permessi.preset import applica_preset
from core.permessi.sync import capacita_permessi, codici_desiderati, codici_per_modulo

CODICI = {
    "home_portale.index.view": "home_portale",
    "assenze.mie_richieste.view": "assenze",
    "assenze.assenze_richiesta.view": "assenze",
    "assenze.assenze_check.manage": "assenze",
    "assenze.assenze.manage": "assenze",
    "legacy.notizie.notizie_lista": "notizie",
    "schede_sicurezza.prodotto.view": "schede_sicurezza",
}


class PaginePersonaliTests(TestCase):
    def setUp(self):
        cache.clear()
        for code, modulo in CODICI.items():
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": modulo})
        applica_preset()

    def test_ruolo_base_riceve_le_pagine_personali(self):
        self.assertIn("home_portale.index.view", codici_per_modulo()["bacheca"])
        cap = capacita_permessi()
        self.assertEqual(cap["assenze.mie_richieste.view"], "lettura")
        self.assertEqual(cap["legacy.notizie.notizie_lista"], "lettura")
        self.assertEqual(cap["schede_sicurezza.prodotto.view"], "lettura")
        base = AccessGroup.objects.get(code="ruolo-dipendente")
        desiderati, _ = codici_desiderati(base)
        for code in ("home_portale.index.view", "assenze.mie_richieste.view", "assenze.assenze_richiesta.view",
                     "assenze.assenze_check.manage", "legacy.notizie.notizie_lista", "schede_sicurezza.prodotto.view"):
            self.assertIn(code, desiderati, code)
        # La gestione amministrativa delle assenze resta fuori.
        self.assertNotIn("assenze.assenze.manage", desiderati)
