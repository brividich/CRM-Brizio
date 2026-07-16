from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from anagrafica.models import (
    AreaAziendale, DipendenteQualifica, DipendenteRuoloOperativo, Reparto,
    RuoloOperativo, TipoQualifica,
)
from anagrafica.services.organigramma_albero import (
    build_certificazione_copertura, build_ruolo_albero,
)

User = get_user_model()


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


class CertificazioneCoperturaTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Saldatore")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=2, ruolo=self.ruolo)
        self.cert = TipoQualifica.objects.create(nome="Patentino saldatura")
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=1, tipo=self.cert,
            data_scadenza=self.oggi + timedelta(days=100),
        )

    def test_copertura_valida_scaduta_mancante(self):
        albero = build_certificazione_copertura(self.cert.pk)
        nodo = next(n for n in albero if n["ruolo"].nome == "Saldatore")
        stati = {t["legacy_id"]: t["stato"] for t in nodo["titolari"]}
        self.assertEqual(stati[1], "posseduta_valida")
        self.assertEqual(stati[2], "mancante")
        self.assertEqual(nodo["n_totale"], 2)
        self.assertEqual(nodo["n_copertura"], 1)


class OrganigrammaAlberoViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-org", "su-org@test.local", "x")
        self.capo = RuoloOperativo.objects.create(nome="CoordView")
        self.sub = RuoloOperativo.objects.create(nome="CaporepView", riporta_a=self.capo)

    def _get(self, **params):
        from anagrafica.views import organigramma_albero
        rf = RequestFactory()
        request = rf.get("/anagrafica/organigramma/albero/", params)
        request.user = self.su
        request.session = SessionStore()
        return organigramma_albero(request)

    def test_render_albero_ruoli(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("CoordView", body)
        self.assertIn("CaporepView", body)


class OrganigrammaAlberoCoperturaViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-cov", "su-cov@test.local", "x")
        self.ruolo = RuoloOperativo.objects.create(nome="SaldView")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=self.ruolo)
        self.cert = TipoQualifica.objects.create(nome="CertView")

    def test_render_copertura_certificazione(self):
        from anagrafica.views import organigramma_albero
        rf = RequestFactory()
        request = rf.get("/anagrafica/organigramma/albero/", {"certificazione": str(self.cert.pk)})
        request.user = self.su
        request.session = SessionStore()
        resp = organigramma_albero(request)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("CertView", body)   # selettore selezionato
        self.assertIn("SaldView", body)
        # Overlay: copertura per-nodo (0 su 1) e badge stato "mancante".
        self.assertIn("0/1", body)
        self.assertIn("Mancante", body)


class OrganigrammaGrigliaResponsabileEffettivoTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-grid", "su-grid@test.local", "x")
        self.rep = Reparto.objects.create(nome="RepGrid", caporeparto_legacy_id=10)
        self.area = AreaAziendale.objects.create(
            nome="AreaGrid", reparto=self.rep, responsabile_legacy_id=20,
        )

    def test_blocco_espone_responsabile_effettivo_area(self):
        self.client.force_login(self.su)
        resp = self.client.get(reverse("anagrafica:organigramma"))
        self.assertEqual(resp.status_code, 200)
        blocco = next(b for b in resp.context["blocchi"] if b["reparto"].nome == "RepGrid")
        aree = {a.nome: a for a in blocco["aree_aziendali"]}
        area = aree["AreaGrid"]
        # L'area vince sul caporeparto (10) quando ha un responsabile proprio (20).
        self.assertEqual(area.responsabile_effettivo_id, 20)
        self.assertTrue(area.responsabile_distinto)
