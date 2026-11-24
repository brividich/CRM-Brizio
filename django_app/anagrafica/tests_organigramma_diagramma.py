"""Organigramma a diagramma: albero di POSIZIONI (ruolo + persona)."""
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from datetime import date

from django.test import RequestFactory, TestCase

from anagrafica.models import (
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    RuoloOperativo,
)
from anagrafica.services.organigramma_albero import build_posizioni_albero

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
        self.assertEqual(nodo["titolari"][0]["foto_v"], "")

    def test_titolare_con_foto_porta_la_versione_della_miniatura(self):
        from anagrafica.models import DipendenteAnagraficaCivile
        from anagrafica.views.dipendenti import _foto_versione

        ruolo = RuoloOperativo.objects.create(nome="ConFoto")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=8, ruolo=ruolo)
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=8, foto="anagrafica/dipendenti/8/foto/p_20261123.jpg")
        albero = build_posizioni_albero()
        titolare = next(n for n in albero if n["ruolo"].nome == "ConFoto")["titolari"][0]
        self.assertIs(titolare["ha_foto"], True)
        self.assertEqual(titolare["foto_v"], _foto_versione("anagrafica/dipendenti/8/foto/p_20261123.jpg"))


    def test_molti_riporti_foglia_restano_fratelli_dello_stesso_livello(self):
        """L'albero e' genealogico: i riporti stanno affiancati sotto il genitore,
        non spezzati in colonne (il layout li dispone in orizzontale)."""
        capo = RuoloOperativo.objects.create(nome="CapoLargo")
        ruolo = RuoloOperativo.objects.create(nome="Tecnico", riporta_a=capo)
        for lid in range(1, 7):
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=lid, ruolo=ruolo)

        albero = build_posizioni_albero()
        nodo_capo = next(n for n in albero if n["ruolo"].nome == "CapoLargo")
        self.assertEqual(len(nodo_capo["figli"]), 6)
        self.assertNotIn("colonne", nodo_capo)
        self.assertNotIn("griglia", nodo_capo)

    def test_sottoalbero_annidato_resta_nei_figli(self):
        capo = RuoloOperativo.objects.create(nome="CapoMisto")
        sub = RuoloOperativo.objects.create(nome="Sub", riporta_a=capo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=100, ruolo=sub)
        RuoloOperativo.objects.create(nome="Nipote", riporta_a=sub)

        albero = build_posizioni_albero()
        nodo_capo = next(n for n in albero if n["ruolo"].nome == "CapoMisto")
        self.assertEqual(len(nodo_capo["figli"]), 1)
        self.assertEqual(nodo_capo["figli"][0]["figli"][0]["ruolo"].nome, "Nipote")


    def test_ex_dipendenti_non_occupano_posizioni(self):
        """Chi ha una data di cessazione esce dall'organigramma: l'assegnazione
        resta a storico, la posizione no."""
        ruolo = RuoloOperativo.objects.create(nome="RuoloConEx")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=11, ruolo=ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=12, ruolo=ruolo)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=12, data_cessazione=date(2026, 1, 31),
        )

        albero = build_posizioni_albero()
        nodi = [n for n in albero if n["ruolo"].nome == "RuoloConEx"]
        self.assertEqual(len(nodi), 1)  # resta un solo titolare: niente fratelli
        self.assertEqual([t["legacy_id"] for t in nodi[0]["titolari"]], [11])

    def test_ruolo_del_solo_ex_dipendente_diventa_vacante(self):
        ruolo = RuoloOperativo.objects.create(nome="RuoloSoloEx")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=21, ruolo=ruolo)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=21, data_cessazione=date(2026, 2, 28),
        )

        albero = build_posizioni_albero()
        nodo = next(n for n in albero if n["ruolo"].nome == "RuoloSoloEx")
        self.assertEqual(nodo["tipo"], "vacante")
        self.assertEqual(nodo["titolari"], [])


class OrganigrammaPersonaPopupTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-popup", "su-popup@test.local", "x")
        self.ruolo = RuoloOperativo.objects.create(nome="RuoloPopup")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=77, ruolo=self.ruolo)

    def test_persona_inesistente_risponde_404(self):
        """Il DB legacy non ha la riga: frammento di errore, non 500."""
        from anagrafica.views import organigramma_persona_popup

        request = RequestFactory().get("/anagrafica/dipendenti/999999/scheda-popup/")
        request.user = self.su
        request.session = SessionStore()
        resp = organigramma_persona_popup(request, 999999)
        self.assertEqual(resp.status_code, 404)


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
        # albero genealogico: livelli annidati di fratelli, non colonne appese
        self.assertIn("ogd-level", body)
        self.assertNotIn("ogd-colonna", body)
        # zoom: comandi in toolbar e wrapper scalabile attorno all'albero
        self.assertIn('data-ogd-zoom="fit"', body)
        self.assertIn('id="ogdScale"', body)
        # tela: schermo intero, stampa e popup della persona
        self.assertIn('id="ogdFull"', body)
        self.assertIn('id="ogdPrint"', body)
        self.assertIn('data-url-popup', body)
        self.assertIn('data-persona=', body)
        # superuser = admin anagrafica: modalità Modifica disponibile
        self.assertIn('id="ogdEditToggle"', body)
        self.assertIn('data-url-azione', body)


class DiagrammaAmbitoDefaultTests(TestCase):
    """Niente più «Tutti gli ambiti»: si apre l'ambito della scheda, con i ruoli senza ambito."""

    def setUp(self):
        from anagrafica.models import AmbitoRuolo

        self.su = User.objects.create_superuser("su-amb", "su-amb@test.local", "x")
        self.prod = AmbitoRuolo.objects.create(nome="ProduttivoT", alimenta_scheda=True, ordine=20)
        self.iso = AmbitoRuolo.objects.create(nome="Iso45001T", ordine=10)
        RuoloOperativo.objects.create(nome="RuoloProdT", ambito=self.prod)
        RuoloOperativo.objects.create(nome="RuoloSenzaT")
        RuoloOperativo.objects.create(nome="RuoloIsoT", ambito=self.iso)

    def _get(self, qs="", session=None):
        from anagrafica.views import organigramma_diagramma

        request = RequestFactory().get("/anagrafica/organigramma/diagramma/" + qs)
        request.user = self.su
        request.session = session if session is not None else SessionStore()
        return organigramma_diagramma(request).content.decode(), request.session

    def test_default_ambito_scheda_con_ruoli_senza_ambito(self):
        body, _ = self._get()
        self.assertNotIn("Tutti gli ambiti", body)
        self.assertNotIn("Ruoli senza ambito", body)
        self.assertIn("RuoloProdT", body)
        self.assertIn("RuoloSenzaT", body)
        self.assertNotIn("RuoloIsoT", body)

    def test_altro_ambito_solo_i_suoi_ruoli_e_resta_ricordato(self):
        body, sessione = self._get(f"?ambito={self.iso.pk}")
        self.assertIn("RuoloIsoT", body)
        self.assertNotIn("RuoloSenzaT", body)
        body, _ = self._get(session=sessione)
        self.assertIn("RuoloIsoT", body)
        self.assertNotIn("RuoloProdT", body)


class DiagrammaSezioniTests(TestCase):
    def setUp(self):
        from anagrafica.models import OrganigrammaSezione

        self.capo = RuoloOperativo.objects.create(nome="CapoSez")
        self.a = RuoloOperativo.objects.create(nome="SaldatoreSez", riporta_a=self.capo)
        self.b = RuoloOperativo.objects.create(nome="TornitoreSez", riporta_a=self.capo)
        for lid in (11, 12):
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=lid, ruolo=self.a)
        self.sez = OrganigrammaSezione.objects.create(nome="Team Saldatura", ruolo_padre=self.capo)

    def _capo(self):
        return next(n for n in build_posizioni_albero() if n["ruolo"].pk == self.capo.pk)

    def test_sezione_vuota_e_tessere_libere(self):
        gruppi = self._capo()["gruppi"]
        self.assertIsNone(gruppi[0]["sezione"])
        self.assertEqual(len(gruppi[0]["figli"]), 3)  # 2 saldatori (fratelli) + tornitore
        self.assertEqual(gruppi[1]["sezione"].pk, self.sez.pk)
        self.assertEqual(gruppi[1]["figli"], [])

    def test_persona_singola_e_ruolo_intero_in_sezione(self):
        from anagrafica.services import organigramma_modifica as om

        om.metti_in_sezione(self.sez.pk, self.a.pk, 11)
        gruppi = self._capo()["gruppi"]
        self.assertEqual([f["chiave_persona"] for f in gruppi[1]["figli"]], [11])
        om.metti_in_sezione(self.sez.pk, self.b.pk, 0)
        gruppi = self._capo()["gruppi"]
        self.assertEqual(len(gruppi[1]["figli"]), 2)
        self.assertEqual(len(gruppi[0]["figli"]), 1)

    def test_entrare_in_sezione_di_altro_ruolo_sposta_la_gerarchia(self):
        from anagrafica.models import OrganigrammaSezione
        from anagrafica.services import organigramma_modifica as om

        altro = RuoloOperativo.objects.create(nome="AltroCapoSez")
        sez2 = OrganigrammaSezione.objects.create(nome="Team Altro", ruolo_padre=altro)
        _, spostato = om.metti_in_sezione(sez2.pk, self.b.pk, 0)
        self.assertTrue(spostato)
        self.b.refresh_from_db()
        self.assertEqual(self.b.riporta_a_id, altro.pk)

    def test_sposta_toglie_dalla_sezione_e_rifiuta_i_cerchi(self):
        from anagrafica.models import OrganigrammaSezioneMembro
        from anagrafica.services import organigramma_modifica as om

        om.metti_in_sezione(self.sez.pk, self.b.pk, 0)
        om.sposta(self.b.pk, None)
        self.assertFalse(OrganigrammaSezioneMembro.objects.filter(ruolo=self.b).exists())
        with self.assertRaises(om.ModificaNonValida):
            om.sposta(self.capo.pk, self.a.pk)

    def test_togli_chiude_assegnazione_con_storico(self):
        from datetime import timedelta

        from django.utils import timezone

        from anagrafica.services import organigramma_modifica as om

        ass = DipendenteRuoloOperativo.objects.get(legacy_anagrafica_id=11, ruolo=self.a)
        ass.data_inizio = date(2020, 1, 1)
        ass.save()
        om.togli(self.a.pk, 11)
        ass.refresh_from_db()
        self.assertEqual(ass.data_fine, timezone.localdate() - timedelta(days=1))
        titolari = {t["legacy_id"] for f in self._capo()["figli"] for t in f["titolari"]}
        self.assertNotIn(11, titolari)
        om.assegna(self.a.pk, 11)  # riassegnare riapre la stessa assegnazione
        ass.refresh_from_db()
        self.assertIsNone(ass.data_fine)


class DiagrammaAzioneEndpointTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-az", "su-az@test.local", "x")
        self.normale = User.objects.create_user("normale-az", "n-az@test.local", "x")
        self.capo = RuoloOperativo.objects.create(nome="CapoAz")
        self.sub = RuoloOperativo.objects.create(nome="SubAz")

    def _post(self, user, dati):
        from django.contrib.auth.models import AnonymousUser

        from anagrafica.views import organigramma_diagramma_azione

        request = RequestFactory().post("/anagrafica/organigramma/diagramma/azione/", dati)
        request.user = user or AnonymousUser()
        request.session = SessionStore()
        return organigramma_diagramma_azione(request)

    def test_anonimo_401_e_non_admin_403_in_json(self):
        r = self._post(None, {"azione": "sposta", "ruolo": self.sub.pk, "padre": self.capo.pk})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r["Content-Type"], "application/json")
        r = self._post(self.normale, {"azione": "sposta", "ruolo": self.sub.pk, "padre": self.capo.pk})
        self.assertEqual(r.status_code, 403)
        self.sub.refresh_from_db()
        self.assertIsNone(self.sub.riporta_a_id)

    def test_admin_sposta_e_crea_sezione(self):
        import json

        from anagrafica.models import OrganigrammaSezione

        r = self._post(self.su, {"azione": "sposta", "ruolo": self.sub.pk, "padre": self.capo.pk})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(json.loads(r.content)["ok"])
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.riporta_a_id, self.capo.pk)
        r = self._post(self.su, {"azione": "sezione_crea", "ruolo": self.capo.pk, "nome": "Team X",
                                 "colore": "javascript:alert(1)"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(OrganigrammaSezione.objects.get(nome="Team X").colore, "#2563eb")
        r = self._post(self.su, {"azione": "sezione_crea", "ruolo": self.capo.pk, "nome": "team x"})
        self.assertEqual(r.status_code, 400)

    def test_cerchio_rifiutato_con_400(self):
        self.sub.riporta_a = self.capo
        self.sub.save()
        r = self._post(self.su, {"azione": "sposta", "ruolo": self.capo.pk, "padre": self.sub.pk})
        self.assertEqual(r.status_code, 400)
