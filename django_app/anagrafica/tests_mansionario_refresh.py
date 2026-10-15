"""Mansionario fase 4: refresh al caporeparto a richiesta della qualità. Dati sintetici."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente

from .models import (
    AbilitazioneMacchina, AbilitazioneMacchinaStorico, CampagnaRefresh, CompetenzaSkm, Mansione, Reparto,
)
from .services import mansionario_competenze as comp
from .services import mansionario_struttura as svc
from .services import skillmatrix_refresh as R
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RefreshMansionarioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("rf4_admin", "rf4@example.invalid", "x")
        self.client.force_login(self.admin)
        self.reparto = Reparto.objects.create(nome="VERNICIATURA SINT", caporeparto_legacy_id=990)
        asset = Asset.objects.create(name="Cabina sintetica", asset_tag="CAB-RF4", reparto="VERNICIATURA SINT")
        self.macchina = CompetenzaSkm.objects.create(competenza_key="RF4-CAB", display="Cabina RF4",
                                                     tipo=CompetenzaSkm.TIPO_MACCHINA, asset=asset)
        self.processo = CompetenzaSkm.objects.create(competenza_key="RF4-MASK", display="Mascheratura RF4",
                                                     tipo=CompetenzaSkm.TIPO_PROCESSO, reparto=self.reparto)
        self.rischio = Mansione.objects.create(nome="ADDETTO VERNICIATURA SINT")
        self.processo.mansioni_rischio.add(self.rischio)
        self.p1 = AnagraficaDipendente.objects.create(nome="UNO", cognome="REFRESH", aliasusername="refresh.uno",
                                                      mansione="ADDETTO MAGAZZINO SINT")
        self.p2 = AnagraficaDipendente.objects.create(nome="DUE", cognome="REFRESH", aliasusername="refresh.due")
        self.ab_macchina = svc.assegna(self.macchina, legacy_anagrafica_id=self.p1.pk, livello="L")
        self.ab_processo = svc.assegna(self.processo, legacy_anagrafica_id=self.p1.pk, livello="U")
        self.url = reverse("anagrafica:skm_refresh")

    def test_processi_senza_asset_nel_reparto(self):
        self.assertEqual(set(R.abilitazioni_reparto("VERNICIATURA SINT")), {self.ab_macchina, self.ab_processo})
        self.assertIn("VERNICIATURA SINT", R.reparti_con_mansioni())
        righe = {r["reparto"]: r for r in R.scadenzario_reparti()}
        self.assertEqual(righe["VERNICIATURA SINT"]["n_totali"], 2)

    def test_scatto_storico_porta_la_mansione(self):
        R.applica_refresh(reparto="VERNICIATURA SINT",
                          decisioni={self.ab_processo.id: {"azione": "conferma", "livello": "O"}})
        s = AbilitazioneMacchinaStorico.objects.filter(fonte=AbilitazioneMacchinaStorico.FONTE_REFRESH).get()
        self.assertEqual(s.competenza_id, self.processo.pk)
        self.assertIsNone(s.asset_id)

    def test_post_aggiunge_persona_su_processo_note_e_chiude(self):
        resp = self.client.post(self.url, {
            "reparto": "VERNICIATURA SINT",
            "nuovo_legacy": str(self.p2.pk), "nuova_mansione": str(self.processo.pk), "nuovo_livello": "I",
            "nota_car": "Una persona è passata al montaggio",
            "chiudi_campagna": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(AbilitazioneMacchina.objects.filter(
            legacy_anagrafica_id=self.p2.pk, competenza=self.processo, in_lista=True).exists())
        camp = CampagnaRefresh.objects.get(reparto="VERNICIATURA SINT")
        self.assertEqual(camp.stato, CampagnaRefresh.STATO_CHIUSA)
        self.assertIn("passata al montaggio", camp.note)

    def test_mansione_con_competenze_rimanda_alla_valutazione(self):
        comp.salva_competenza(self.processo, nome="Preparazione superfici", livello_minimo="U")
        resp = self.client.get(self.url, {"reparto": "VERNICIATURA SINT"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Valuta competenze")
        self.assertNotContains(resp, f'name="livello_{self.ab_processo.id}"')
        self.assertContains(resp, f'name="livello_{self.ab_macchina.id}"')

    def test_valuta_da_refresh_torna_al_refresh(self):
        voce = comp.salva_competenza(self.processo, nome="Preparazione superfici", livello_minimo="U")
        url = reverse("anagrafica:mansionario_valuta", args=[self.processo.pk, self.ab_processo.pk])
        resp = self.client.post(url, {f"livello_{voce.pk}": "U", "da": "refresh", "reparto": "VERNICIATURA SINT"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("anagrafica:skm_refresh"), resp["Location"])

    def test_sollecito_solo_con_campagna_aperta(self):
        from core.models import Notifica
        self.assertFalse(R.sollecita_car("VERNICIATURA SINT"))
        R.avvia_refresh(reparto="VERNICIATURA SINT", avviatore_ruolo="Qualità")
        self.assertTrue(R.sollecita_car("VERNICIATURA SINT"))
        testi = list(Notifica.objects.filter(legacy_user_id=990, tipo="skm_refresh").values_list("messaggio", flat=True))
        self.assertEqual(len(testi), 2)
        self.assertTrue(any(t.startswith("Sollecito") for t in testi))

    def test_post_sollecita_dallo_scadenzario(self):
        R.avvia_refresh(reparto="VERNICIATURA SINT", avviatore_ruolo="Qualità")
        resp = self.client.post(reverse("anagrafica:skm_scadenzario"),
                                {"azione": "sollecita", "reparto": "VERNICIATURA SINT"})
        self.assertEqual(resp.status_code, 302)

    def test_coerenza_rischio(self):
        dati = R.coerenza_rischio_reparto("VERNICIATURA SINT")
        self.assertEqual([m.pk for m in dati["mansioni_senza_rischio"]], [self.macchina.pk])
        persona = next(p for p in dati["persone"] if p["legacy_id"] == self.p1.pk)
        self.assertEqual(persona["stato"], "diversa")
        self.assertEqual(persona["attese"], ["ADDETTO VERNICIATURA SINT"])

    def test_capo_skill_matrix_puo_valutare_senza_essere_admin_anagrafica(self):
        from unittest import mock
        from django.test import RequestFactory
        from . import views_mansionario as vm
        req = RequestFactory().get("/")
        req.user = User.objects.create_user("rf4_car", "car@example.invalid", "x")
        req.session = {}
        with mock.patch("anagrafica.views._is_anagrafica_admin", return_value=False):
            with mock.patch("anagrafica.views._check_skm_permission", return_value=True):
                self.assertTrue(vm._puo_valutare(req))
            with mock.patch("anagrafica.views._check_skm_permission", return_value=False):
                self.assertFalse(vm._puo_valutare(req))
