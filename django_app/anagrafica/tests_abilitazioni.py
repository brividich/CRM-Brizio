"""Abilitazioni (carrellista, PLE, primo soccorso…): a chi servono, com'è messa la persona, chi può usare un mezzo.

Solo dati sintetici.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, AssetCategory
from core.legacy_models import AnagraficaDipendente

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    Mansione,
    RuoloOperativo,
    RuoloQualifica,
    TipoQualifica,
)
from .models_formazione import TrainingCourse, TrainingPlan
from .services import abilitazioni
from .tests import _ensure_anagrafica_table
from .tests_coerenza_ag4 import _onboarded

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class AbilitazioniTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("abil_admin", "abil@example.invalid", "x")
        _onboarded(self.admin)
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        self.tipo = TipoQualifica.objects.create(nome="Carrellista sintetico", categoria=TipoQualifica.CAT_SICUREZZA,
                                                 durata_mesi=60)
        self.mansione = Mansione.objects.create(nome="CARRELLISTA SINT")
        self.tipo.mansioni_rischio.add(self.mansione)

    def _persona(self, nome, cognome, *, mansione="", reparto="Magazzino sint", cessata=False):
        p = AnagraficaDipendente.objects.create(nome=nome, cognome=cognome, aliasusername=f"abil.{nome.lower()}",
                                                mansione=mansione, reparto=reparto)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=p.pk, data_cessazione=self.oggi - timedelta(days=400) if cessata else None)
        return p

    def _qualifica(self, persona, giorni_alla_scadenza, tipo=None):
        return DipendenteQualifica.objects.create(
            legacy_anagrafica_id=persona.pk, tipo=tipo or self.tipo,
            data_conseguimento=self.oggi - timedelta(days=100),
            data_scadenza=self.oggi + timedelta(days=giorni_alla_scadenza))

    def test_mansione_di_rischio_chiede_l_abilitazione(self):
        manca = self._persona("ADA", "MANCA", mansione="CARRELLISTA SINT")
        valida = self._persona("BRUNO", "VALIDA", mansione="CARRELLISTA SINT")
        scaduta = self._persona("CARLA", "SCADUTA", mansione="CARRELLISTA SINT")
        altro = self._persona("DINO", "ALTRO", mansione="IMPIEGATO SINT")
        cessato = self._persona("ELSA", "CESSATA", mansione="CARRELLISTA SINT", cessata=True)
        self._qualifica(valida, 400)
        self._qualifica(scaduta, -3)
        self._qualifica(altro, 30)

        quadro = abilitazioni.quadro()
        stati = {lid: [(v["nome"], v["stato"], v["richiesta"]) for v in voci] for lid, voci in quadro.items()}
        self.assertEqual(stati[manca.pk], [("Carrellista sintetico", "mancante", True)])
        self.assertEqual(stati[valida.pk], [("Carrellista sintetico", "valida", True)])
        self.assertEqual(stati[scaduta.pk], [("Carrellista sintetico", "scaduta", True)])
        # Chi la possiede senza che gli serva la vede lo stesso, non richiesta.
        self.assertEqual(stati[altro.pk], [("Carrellista sintetico", "in_scadenza", False)])
        self.assertNotIn(cessato.pk, quadro)
        self.assertEqual(quadro[manca.pk][0]["motivi"], ["Mansione di rischio «CARRELLISTA SINT»"])

        # La pagina dell'abilitazione elenca chi manca con lo stesso motivo.
        resp = self.client.get(reverse("anagrafica:tipo_qualifica_detail", args=[self.tipo.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({m["legacy_id"]: m["stato"] for m in resp.context["mancanti"]},
                         {manca.pk: "mancante", scaduta.pk: "scaduta"})
        self.assertContains(resp, "Mansione di rischio «CARRELLISTA SINT»")
        self.assertEqual(resp.context["n_mancanti"], 1)

    def test_corso_base_a_chi_manca_aggiornamento_a_chi_scade(self):
        piano = TrainingPlan.objects.create(codice="PABIL", nome="Piano sintetico")
        base = TrainingCourse.objects.create(piano=piano, codice="ABIL-B", titolo="Carrellista base", stato="ATTIVO",
                                             durata_ore_teorica=12, qualifica=self.tipo)
        agg = TrainingCourse.objects.create(piano=piano, codice="ABIL-A", titolo="Carrellista aggiornamento",
                                            stato="ATTIVO", durata_ore_teorica=4, qualifica=self.tipo,
                                            qualifica_effetto=TrainingCourse.EFFETTO_AGGIORNAMENTO)
        manca = self._persona("ADA", "MANCA", mansione="CARRELLISTA SINT")
        scaduta = self._persona("CARLA", "SCADUTA", mansione="CARRELLISTA SINT")
        self._qualifica(scaduta, -3)
        quadro = abilitazioni.quadro()
        self.assertEqual(quadro[manca.pk][0]["corso"], base)
        self.assertEqual(quadro[scaduta.pk][0]["corso"], agg)
        resp = self.client.get(reverse("anagrafica:tipo_qualifica_detail", args=[self.tipo.pk]))
        self.assertContains(resp, "Corso base")
        self.assertContains(resp, "Aggiornamento")

    def test_serve_a_si_salva_dalla_pagina(self):
        ruolo = RuoloOperativo.objects.create(nome="Addetto magazzino sint")
        vecchio = RuoloOperativo.objects.create(nome="Ruolo da togliere sint")
        RuoloQualifica.objects.create(ruolo=vecchio, qualifica=self.tipo, obbligatoria=True)
        categoria = AssetCategory.objects.create(code="carrelli-sint", label="Carrelli sintetici")
        altra = Mansione.objects.create(nome="MAGAZZINIERE SINT")
        resp = self.client.post(reverse("anagrafica:tipo_qualifica_serve_a", args=[self.tipo.pk]), {
            "ruoli": [ruolo.pk], "mansioni": [altra.pk], "categorie": [categoria.pk], "mostra_in_presenti": "1"})
        self.assertEqual(resp.status_code, 302)
        self.tipo.refresh_from_db()
        self.assertEqual(list(RuoloQualifica.objects.filter(qualifica=self.tipo).values_list("ruolo_id", "obbligatoria")),
                         [(ruolo.pk, True)])
        self.assertEqual(list(self.tipo.mansioni_rischio.all()), [altra])
        self.assertEqual(list(self.tipo.categorie_asset.all()), [categoria])
        self.assertTrue(self.tipo.mostra_in_presenti)

    def test_serve_a_solo_per_chi_amministra(self):
        utente = User.objects.create_user("abil_utente", "u@example.invalid", "x")
        _onboarded(utente)
        self.client.force_login(utente)
        self.client.post(reverse("anagrafica:tipo_qualifica_serve_a", args=[self.tipo.pk]), {"mostra_in_presenti": "1"})
        self.tipo.refresh_from_db()
        self.assertFalse(self.tipo.mostra_in_presenti)
        self.assertEqual(list(self.tipo.mansioni_rischio.all()), [self.mansione])

    def test_chi_puo_usare_il_mezzo(self):
        madre = AssetCategory.objects.create(code="mezzi-sint", label="Mezzi sintetici")
        figlia = AssetCategory.objects.create(code="carrelli-sint", label="Carrelli sintetici", parent=madre)
        self.tipo.categorie_asset.add(madre)
        carrello = Asset.objects.create(asset_tag="AST-ABIL-1", name="Carrello sintetico", asset_category=figlia)
        libero = Asset.objects.create(asset_tag="AST-ABIL-2", name="Tornio sintetico")
        valida = self._persona("BRUNO", "VALIDA")
        scaduta = self._persona("CARLA", "SCADUTA")
        self._persona("DINO", "SENZA")
        self._qualifica(valida, 400)
        self._qualifica(scaduta, -3)

        self.assertIsNone(abilitazioni.abilitati_asset(libero))
        esito = abilitazioni.abilitati_asset(carrello, nomi={valida.pk: "Bruno Valida", scaduta.pk: "Carla Scaduta"})
        self.assertEqual([(p["nome"], p["puo"]) for p in esito["persone"]],
                         [("Bruno Valida", True), ("Carla Scaduta", False)])
        self.assertEqual(esito["n_validi"], 1)

        resp = self.client.get(reverse("assets:asset_view", args=[carrello.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Chi può usarlo")
        resp = self.client.get(reverse("assets:asset_view", args=[libero.pk]))
        self.assertNotContains(resp, "Chi può usarlo")

    def test_elenco_per_reparto_tessere_e_righe_coincidono(self):
        manca = self._persona("ADA", "MANCA", mansione="CARRELLISTA SINT", reparto="Magazzino sint")
        valida = self._persona("BRUNO", "VALIDA", mansione="CARRELLISTA SINT", reparto="Officina sint")
        self._qualifica(valida, 400)
        url = reverse("anagrafica:abilitazioni_persone")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["conta"], {"valida": 1, "in_scadenza": 0, "scaduta": 0, "mancante": 1})
        self.assertEqual([g["reparto"] for g in resp.context["gruppi"]], ["Magazzino sint", "Officina sint"])
        # La tessera «Mancanti» apre un elenco con tante voci quante ne conta.
        resp = self.client.get(url, {"stato": "mancante"})
        voci = [v for g in resp.context["gruppi"] for r in g["righe"] for v in r["voci"]]
        self.assertEqual(len(voci), resp.context["conta"]["mancante"])
        self.assertEqual([r["id"] for g in resp.context["gruppi"] for r in g["righe"]], [manca.pk])
        resp = self.client.get(url, {"reparto": "Officina sint"})
        self.assertEqual(resp.context["conta"], {"valida": 1, "in_scadenza": 0, "scaduta": 0, "mancante": 0})
        # Export con gli stessi filtri.
        resp = self.client.get(reverse("anagrafica:export", args=["abilitazioni_persone"]),
                               {"format": "xlsx", "scope": "filtered", "stato": "mancante"})
        self.assertEqual(resp.status_code, 200)

    def test_presenti_bollino_e_incarico_scoperto(self):
        bls = TipoQualifica.objects.create(nome="BLS-D sintetico", mostra_in_presenti=True)
        soccorso = TipoQualifica.objects.create(nome="Primo soccorso sintetico")
        ruolo = RuoloOperativo.objects.create(nome="Addetto primo soccorso sint")
        RuoloQualifica.objects.create(ruolo=ruolo, qualifica=soccorso, obbligatoria=True)
        coperto = self._persona("ADA", "COPERTA")
        scoperto = self._persona("BRUNO", "SCOPERTO")
        for p in (coperto, scoperto):
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=p.pk, ruolo=ruolo)
        self._qualifica(coperto, 200, tipo=soccorso)
        self._qualifica(scoperto, -5, tipo=soccorso)
        self._qualifica(coperto, 200, tipo=bls)
        self._qualifica(scoperto, -5, tipo=bls)

        self.assertEqual(abilitazioni.incarichi_scoperti(), {scoperto.pk: {"Addetto primo soccorso sint"}})
        bollini = abilitazioni.bollini_presenti()
        self.assertEqual([b["nome"] for b in bollini[coperto.pk]], ["BLS-D sintetico"])
        self.assertNotIn(scoperto.pk, bollini)

    def test_scheda_persona_mostra_le_mancanti(self):
        manca = self._persona("ADA", "MANCA", mansione="CARRELLISTA SINT")
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[manca.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Le servono e non le ha (1)")
        self.assertContains(resp, "Mansione di rischio «CARRELLISTA SINT»")
