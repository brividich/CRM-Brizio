"""Un ruolo solo per persona: accessi al portale dal ruolo in azienda.

Comando ``allinea_accessi_ruoli``, ruolo in azienda accanto agli accessi, controllo
«nome diverso dal principale» di ``report_ruoli_disallineati``. Dati sintetici.
"""
from __future__ import annotations

from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import AccessGroup
from core.permessi.preset import applica_preset
from core.permessi.ruolo_azienda import ruoli_in_azienda

from .models import AmbitoRuolo, DipendenteAnagraficaAziendale, DipendenteRuoloOperativo, RuoloOperativo
from .tests import _ensure_anagrafica_table


@override_settings(LEGACY_AUTH_ENABLED=False)
class AccessiDalRuoloTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        cache.clear()
        applica_preset()
        ambito, _ = AmbitoRuolo.objects.get_or_create(nome="Produttivo", defaults={"alimenta_scheda": True})
        ambito.alimenta_scheda = True
        ambito.save()
        self.car = RuoloOperativo.objects.create(nome="Caporeparto", sigla="CAR", ambito=ambito)
        self.vecchio = RuoloOperativo.objects.create(nome="CLG Manager sintetico", ambito=ambito, is_active=False)
        self.cq = AccessGroup.objects.get(code="ruolo-controllo-qualita")
        self.capo = AccessGroup.objects.get(code="ruolo-responsabile")
        self.car.profili_permessi.add(self.cq)
        self.vecchio.profili_permessi.add(self.cq)
        self.utente = UtenteLegacy.objects.create(nome="PROVA Gino", email="g.prova", password="x", attivo=True)
        self.persona = AnagraficaDipendente.objects.create(nome="Gino", cognome="PROVA", aliasusername="g.prova",
                                                           utente=self.utente)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.persona.pk, ruolo=self.car,
                                                tipologia=DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE)

    def test_prova_non_scrive_e_applica_allinea(self):
        out = StringIO()
        call_command("allinea_accessi_ruoli", stdout=out)
        self.assertIn("PROVA", out.getvalue())
        self.assertIn("Caporeparto (1 persone): ruolo-controllo-qualita -> ruolo-responsabile", out.getvalue())
        self.assertEqual(set(self.car.profili_permessi.all()), {self.cq})
        call_command("allinea_accessi_ruoli", "--applica", stdout=StringIO())
        self.assertEqual(set(self.car.profili_permessi.all()), {self.capo})
        self.assertFalse(self.vecchio.profili_permessi.exists())

    def test_ruolo_in_azienda_accanto_agli_accessi(self):
        self.assertEqual(ruoli_in_azienda([self.utente.pk]), {self.utente.pk: "CAR · Caporeparto"})

    def test_scheda_con_nome_vecchio_si_allinea(self):
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=self.persona.pk, ruolo_aziendale="Dept Chief")
        out = StringIO()
        call_command("report_ruoli_disallineati", "--solo", "ruoli", stdout=out)
        self.assertIn("«Dept Chief» -> «Caporeparto»", out.getvalue())
        call_command("report_ruoli_disallineati", "--solo", "ruoli", "--apply", stdout=StringIO())
        self.assertEqual(DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.persona.pk).ruolo_aziendale,
                         "Caporeparto")
