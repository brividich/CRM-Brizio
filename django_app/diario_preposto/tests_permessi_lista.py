"""La lista e le ispezioni del diario si aprono con «vedere», non solo con «gestire»."""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase

from core.models import AccessGroup, PermissionDefinition, RuoloPermessoModulo
from core.permessi.sync import capacita_permessi, codici_desiderati

LISTA = "legacy.diario_preposto.diario_preposto_lista"
ISPEZIONI = "legacy.diario_preposto.diario_preposto_ispezioni"
IMPOSTAZIONI = "diario_preposto.impostazioni.view"


class PermessiListaDiarioTests(TestCase):
    def setUp(self):
        cache.clear()
        for code in (LISTA, ISPEZIONI, IMPOSTAZIONI):
            PermissionDefinition.objects.get_or_create(
                code=code, defaults={"label": code, "module": "diario_preposto"}
            )

    def test_lista_e_ispezioni_sono_lettura(self):
        cap = capacita_permessi()
        self.assertEqual(cap[LISTA], "lettura")
        self.assertEqual(cap[ISPEZIONI], "lettura")

    def test_ruolo_con_solo_vedere_apre_lista_e_ispezioni_non_impostazioni(self):
        ruolo = AccessGroup.objects.create(code="ruolo-test-preposto", label="Preposto test", priority=300)
        RuoloPermessoModulo.objects.create(ruolo=ruolo, modulo="diario_preposto", azione="vedere", ambito="tutti")
        desiderati, _ = codici_desiderati(ruolo)
        self.assertIn(LISTA, desiderati)
        self.assertIn(ISPEZIONI, desiderati)
        self.assertNotIn(IMPOSTAZIONI, desiderati)
