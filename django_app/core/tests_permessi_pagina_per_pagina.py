"""Matrice dei ruoli, pagina per pagina: eccezioni «Sì, sempre» / «No, mai» per ruolo.

La granularita' del vecchio ACL canonico (un permesso di pagina alla volta)
dentro la matrice: le eccezioni sono grant di gruppo fuori dalla matrice, la
sincronizzazione non le tocca e il resolver le legge come ogni grant di ruolo.
"""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.models import AccessGroup, GroupPermissionGrant, PermissionDefinition, RuoloPermessoModulo
from core.permessi.sync import (
    NOTA_ECCEZIONE,
    NOTA_MATRICE,
    imposta_eccezioni_pagina,
    pagine_modulo_ruolo,
    sincronizza_ruolo,
)
from core.tests_permessi import PersoneMixin


class MatricePaginaPerPaginaTests(PersoneMixin, TestCase):
    def setUp(self):
        cache.clear()
        for code in ("dpi.detail.view", "dpi.approva.view"):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": "dpi"})
        self.ruolo = AccessGroup.objects.create(code="pg_magazzino", label="Magazzino prova", priority=300)
        RuoloPermessoModulo.objects.create(ruolo=self.ruolo, modulo="dpi", azione="vedere", ambito="tutti")
        sincronizza_ruolo(self.ruolo)

    def _grant(self, code):
        return GroupPermissionGrant.objects.filter(group=self.ruolo, permission_id=code).first()

    def test_dettaglio_elenca_ogni_pagina_del_modulo(self):
        righe = {r["code"]: r for r in pagine_modulo_ruolo(self.ruolo)["dpi"]}
        self.assertIn("dpi.detail.view", righe)
        self.assertIn("dpi.approva.view", righe)
        self.assertTrue(righe["dpi.detail.view"]["aperta"])
        self.assertEqual(righe["dpi.detail.view"]["eccezione"], "")
        self.assertIn("Approvare", righe["dpi.approva.view"]["colonna"])
        self.assertFalse(righe["dpi.approva.view"]["aperta"])

    def test_no_mai_chiude_una_pagina_che_la_colonna_concede_e_resta(self):
        imposta_eccezioni_pagina(self.ruolo, {"dpi.detail.view": "no"})
        sincronizza_ruolo(self.ruolo)
        g = self._grant("dpi.detail.view")
        self.assertFalse(g.enabled)
        self.assertEqual(g.note, NOTA_ECCEZIONE)
        self.assertEqual({r["code"]: r["eccezione"] for r in pagine_modulo_ruolo(self.ruolo)["dpi"]}["dpi.detail.view"], "no")

    def test_si_sempre_apre_una_pagina_che_la_colonna_non_concede(self):
        imposta_eccezioni_pagina(self.ruolo, {"dpi.approva.view": "si"})
        RuoloPermessoModulo.objects.filter(ruolo=self.ruolo).delete()
        sincronizza_ruolo(self.ruolo)
        self.assertTrue(self._grant("dpi.approva.view").enabled)
        self.assertIsNone(self._grant("dpi.detail.view"))

    def test_segue_la_matrice_toglie_l_eccezione(self):
        imposta_eccezioni_pagina(self.ruolo, {"dpi.detail.view": "no"})
        modifiche = imposta_eccezioni_pagina(self.ruolo, {"dpi.detail.view": ""})
        self.assertEqual(modifiche, [{"pagina": "dpi.detail.view", "prima": "no", "dopo": "matrice"}])
        sincronizza_ruolo(self.ruolo)
        g = self._grant("dpi.detail.view")
        self.assertTrue(g.enabled)
        self.assertEqual(g.note, NOTA_MATRICE)

    def test_code_fuori_dai_moduli_ignorato(self):
        self.assertEqual(imposta_eccezioni_pagina(self.ruolo, {"inesistente.view": "si"}), [])

    def test_salva_matrice_dalla_pagina(self):
        admin, _ = self.persona("Amministratore sintetico", superuser=True)
        self.client.force_login(admin)
        resp = self.client.get(reverse("admin_portale:ruoli_portale"), {"tab": "matrice", "ruolo": self.ruolo.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Pagina per pagina")
        self.assertContains(resp, 'name="p__dpi.approva.view"')
        resp = self.client.post(
            reverse("admin_portale:ruoli_portale_matrice", args=[self.ruolo.id]),
            {"p__dpi.approva.view": "si", "p__dpi.detail.view": ""},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self._grant("dpi.approva.view").enabled)
        self.assertEqual(self._grant("dpi.detail.view").note, NOTA_MATRICE)

    def test_salva_matrice_in_un_solo_campo_json(self):
        """Oltre mille tendine non devono sfondare DATA_UPLOAD_MAX_NUMBER_FIELDS (400)."""
        import json

        admin, _ = self.persona("Amministratore sintetico", superuser=True)
        self.client.force_login(admin)
        valori = {f"p__sintetico.pagina{i}.view": "" for i in range(1500)}
        valori["p__dpi.approva.view"] = "si"
        resp = self.client.get(reverse("admin_portale:ruoli_portale"), {"tab": "matrice", "ruolo": self.ruolo.id})
        self.assertContains(resp, 'name="matrice_json"')
        resp = self.client.post(
            reverse("admin_portale:ruoli_portale_matrice", args=[self.ruolo.id]),
            {"matrice_json": json.dumps(valori)},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(self._grant("dpi.approva.view").enabled)

    def test_matrice_json_illeggibile_non_tocca_nulla(self):
        admin, _ = self.persona("Amministratore sintetico", superuser=True)
        self.client.force_login(admin)
        resp = self.client.post(
            reverse("admin_portale:ruoli_portale_matrice", args=[self.ruolo.id]),
            {"matrice_json": "[non json"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIsNone(self._grant("dpi.approva.view"))
