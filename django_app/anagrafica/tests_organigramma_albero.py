from django.test import TestCase
from anagrafica.models import RuoloOperativo, DipendenteRuoloOperativo
from anagrafica.services.organigramma_albero import build_ruolo_albero


class RuoloAlberoTests(TestCase):
    def setUp(self):
        self.capo = RuoloOperativo.objects.create(nome="Coordinatore")
        self.sub = RuoloOperativo.objects.create(nome="Caporeparto", riporta_a=self.capo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=self.sub)

    def test_radici_sono_ruoli_senza_riporta_a(self):
        albero = build_ruolo_albero()
        nomi_radici = {n["ruolo"].nome for n in albero}
        self.assertIn("Coordinatore", nomi_radici)
        self.assertNotIn("Caporeparto", nomi_radici)  # è figlio

    def test_gerarchia_ruolo_e_titolari_come_foglie(self):
        albero = build_ruolo_albero()
        coord = next(n for n in albero if n["ruolo"].nome == "Coordinatore")
        figlio = coord["figli"][0]
        self.assertEqual(figlio["ruolo"].nome, "Caporeparto")
        self.assertEqual({t["legacy_id"] for t in figlio["titolari"]}, {1})
        # i titolari non hanno "figli": sono foglie, mai gerarchia tra persone
        self.assertNotIn("figli", figlio["titolari"][0])
