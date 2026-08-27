"""Organigramma a diagramma: albero di POSIZIONI (ruolo + persona)."""
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase

from anagrafica.models import DipendenteRuoloOperativo, RuoloOperativo
from anagrafica.services.organigramma_albero import (
    build_posizioni_albero,
    griglia_riporti,
    spezza_in_colonne,
)

User = get_user_model()


class PosizioniAlberoTests(TestCase):
    def test_ruolo_con_un_titolare_e_un_solo_riquadro(self):
        ruolo = RuoloOperativo.objects.create(nome="Direttore")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=ruolo)
        albero = build_posizioni_albero()
        nodo = next(n for n in albero if n["ruolo"].nome == "Direttore")
        self.assertEqual(nodo["tipo"], "posizione")
        self.assertEqual([t["legacy_id"] for t in nodo["titolari"]], [1])

    def test_ruolo_foglia_con_piu_titolari_si_espande_in_riquadri_fratelli(self):
        capo = RuoloOperativo.objects.create(nome="Responsabile")
        eng = RuoloOperativo.objects.create(nome="Project Engineer", riporta_a=capo)
        for lid in (1, 2, 3):
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=lid, ruolo=eng)

        albero = build_posizioni_albero()
        nodo_capo = next(n for n in albero if n["ruolo"].nome == "Responsabile")
        figli = nodo_capo["figli"]
        self.assertEqual(len(figli), 3)  # un riquadro per persona
        self.assertTrue(all(f["ruolo"].nome == "Project Engineer" for f in figli))
        self.assertTrue(all(f["tipo"] == "posizione" for f in figli))
        self.assertTrue(all(len(f["titolari"]) == 1 for f in figli))
        self.assertEqual(
            {f["titolari"][0]["legacy_id"] for f in figli}, {1, 2, 3},
        )

    def test_ruolo_con_piu_titolari_e_riporti_resta_riquadro_unico(self):
        capo = RuoloOperativo.objects.create(nome="Capoturno")
        RuoloOperativo.objects.create(nome="Operatore", riporta_a=capo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=capo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=2, ruolo=capo)

        albero = build_posizioni_albero()
        nodi_capo = [n for n in albero if n["ruolo"].nome == "Capoturno"]
        self.assertEqual(len(nodi_capo), 1)
        self.assertEqual(nodi_capo[0]["tipo"], "condiviso")
        self.assertEqual(len(nodi_capo[0]["titolari"]), 2)
        self.assertEqual(len(nodi_capo[0]["figli"]), 1)

    def test_ruolo_senza_titolari_e_posizione_vacante(self):
        RuoloOperativo.objects.create(nome="Vacante")
        albero = build_posizioni_albero()
        nodo = next(n for n in albero if n["ruolo"].nome == "Vacante")
        self.assertEqual(nodo["tipo"], "vacante")
        self.assertEqual(nodo["titolari"], [])

    def test_titolari_hanno_flag_foto(self):
        ruolo = RuoloOperativo.objects.create(nome="ConFlag")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=7, ruolo=ruolo)
        albero = build_posizioni_albero()
        nodo = next(n for n in albero if n["ruolo"].nome == "ConFlag")
        self.assertIs(nodo["titolari"][0]["ha_foto"], False)


    def test_molti_riporti_foglia_vanno_su_piu_colonne(self):
        capo = RuoloOperativo.objects.create(nome="CapoColonne")
        ruolo = RuoloOperativo.objects.create(nome="Tecnico", riporta_a=capo)
        for lid in range(1, 7):  # 6 titolari > SOGLIA_COLONNE
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=lid, ruolo=ruolo)

        albero = build_posizioni_albero()
        nodo_capo = next(n for n in albero if n["ruolo"].nome == "CapoColonne")
        self.assertEqual(len(nodo_capo["figli"]), 6)
        self.assertIs(nodo_capo["griglia"], True)
        self.assertEqual([len(c) for c in nodo_capo["colonne"]], [3, 3])

    def test_riporti_con_sottoalbero_restano_in_colonna_singola(self):
        capo = RuoloOperativo.objects.create(nome="CapoMisto")
        for i in range(6):
            sub = RuoloOperativo.objects.create(nome=f"Sub{i}", riporta_a=capo)
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=100 + i, ruolo=sub)
        # uno dei riporti ha a sua volta un riporto: niente colonne
        RuoloOperativo.objects.create(nome="Nipote", riporta_a=RuoloOperativo.objects.get(nome="Sub0"))

        albero = build_posizioni_albero()
        nodo_capo = next(n for n in albero if n["ruolo"].nome == "CapoMisto")
        self.assertIs(nodo_capo["griglia"], False)
        self.assertEqual(len(nodo_capo["colonne"]), 1)  # colonna unica

    def test_colonne_spezzano_i_riporti_numerosi(self):
        foglie = [{"figli": []} for _ in range(6)]
        colonne = spezza_in_colonne(foglie)
        self.assertEqual([len(c) for c in colonne], [3, 3])
        self.assertEqual(sum(len(c) for c in colonne), 6)
        # oltre le tre colonne non si va: si allungano
        colonne = spezza_in_colonne([{"figli": []} for _ in range(20)])
        self.assertEqual(len(colonne), 3)
        self.assertEqual(sum(len(c) for c in colonne), 20)

    def test_colonna_unica_quando_i_riporti_sono_pochi(self):
        foglie = [{"figli": []} for _ in range(4)]
        self.assertEqual(spezza_in_colonne(foglie), [foglie])
        self.assertEqual(spezza_in_colonne([]), [])

    def test_griglia_riporti_soglia(self):
        foglie = [{"figli": []} for _ in range(5)]
        self.assertIs(griglia_riporti(foglie), False)
        self.assertIs(griglia_riporti(foglie + [{"figli": []}]), True)


class OrganigrammaDiagrammaViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-diag", "su-diag@test.local", "x")
        self.capo = RuoloOperativo.objects.create(nome="CoordDiag")
        self.sub = RuoloOperativo.objects.create(nome="TecnicoDiag", riporta_a=self.capo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=self.sub)

    def test_render_diagramma(self):
        from anagrafica.views import organigramma_diagramma

        request = RequestFactory().get("/anagrafica/organigramma/diagramma/")
        request.user = self.su
        request.session = SessionStore()
        resp = organigramma_diagramma(request)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("CoordDiag", body)
        self.assertIn("TecnicoDiag", body)
        self.assertIn("ogd-card", body)  # riquadri disegnati
