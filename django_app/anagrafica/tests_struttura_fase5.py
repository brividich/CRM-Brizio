"""Struttura Fase 5: catalogo unico delle competenze, riuso delle valutazioni, storico, matrice.

Solo dati sintetici.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente

from .models import (
    AbilitazioneMacchina, CompetenzaCatalogo, CompetenzaSkm, Reparto, ValutazioneCompetenzaStorico,
    VoceMacchinaCatalogo,
)
from .services import competenze_catalogo as cat_svc
from .services import mansionario_competenze as comp_svc
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class CatalogoCompetenzeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("f5_admin", "f5@example.invalid", "x", first_name="Ada",
                                                   last_name="SINTETICA")
        self.reparto = Reparto.objects.create(nome="Reparto sintetico F5")
        self.fresa = CompetenzaSkm.objects.create(competenza_key="F5-FRESA", display="F5 Fresa",
                                                  tipo=CompetenzaSkm.TIPO_PROCESSO, reparto=self.reparto)
        self.tornio = CompetenzaSkm.objects.create(competenza_key="F5-TORNIO", display="F5 Tornio",
                                                   tipo=CompetenzaSkm.TIPO_PROCESSO, reparto=self.reparto)
        self.v_fresa = comp_svc.salva_competenza(self.fresa, nome="Lettura del disegno", livello_minimo="L")
        self.v_tornio = comp_svc.salva_competenza(self.tornio, nome="  lettura   del DISEGNO ", livello_minimo="U")
        self.persona = AnagraficaDipendente.objects.create(nome="Franco", cognome="PROVA", aliasusername="f5.franco")
        self.ab_fresa = AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.persona.pk, competenza=self.fresa,
                                                            livello="I")
        self.ab_tornio = AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.persona.pk,
                                                             competenza=self.tornio, livello="I")

    def test_stesso_nome_stessa_competenza(self):
        self.assertEqual(CompetenzaCatalogo.objects.count(), 1)
        self.assertEqual(self.v_fresa.catalogo_id, self.v_tornio.catalogo_id)
        righe = cat_svc.elenco()
        self.assertEqual(len(righe[0]["mansioni"]), 2)

    def test_storico_e_livello_proposto_altrove(self):
        comp_svc.registra_livelli(self.ab_fresa, {self.v_fresa.pk: "U"}, user=self.admin)
        comp_svc.registra_livelli(self.ab_fresa, {self.v_fresa.pk: "O"}, user=self.admin)
        storico = cat_svc.storico_persona(self.persona.pk)
        self.assertEqual([(s.livello_prima, s.livello) for s in storico], [("U", "O"), ("", "U")])
        self.assertEqual(storico[0].valutato_da, self.admin.get_full_name())
        # Nessuna variazione, nessuna riga.
        comp_svc.registra_livelli(self.ab_fresa, {self.v_fresa.pk: "O"}, user=self.admin)
        self.assertEqual(ValutazioneCompetenzaStorico.objects.count(), 2)
        noti = cat_svc.livelli_noti(self.persona.pk, escludi_abilitazione_id=self.ab_tornio.pk)
        self.assertEqual(noti[self.v_tornio.catalogo_id]["livello"], "O")
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:mansionario_valuta", args=[self.tornio.pk, self.ab_tornio.pk]))
        self.assertContains(resp, "Già valutato")
        self.assertContains(resp, "Riprendi 1 livello già valutato")
        resp = self.client.get(reverse("anagrafica:mansionario_persona", args=[self.persona.pk]))
        self.assertContains(resp, "Storico delle valutazioni")

    def test_rinomina_e_unisci(self):
        cat = self.v_fresa.catalogo
        self.assertEqual(cat_svc.rinomina(cat, "Lettura disegno tecnico"), 2)
        self.v_tornio.refresh_from_db()
        self.assertEqual(self.v_tornio.nome, "Lettura disegno tecnico")
        altra_v = comp_svc.salva_competenza(self.fresa, nome="Disegno tecnico")
        with self.assertRaises(ValueError):
            cat_svc.rinomina(altra_v.catalogo, "lettura disegno TECNICO")
        # La fresa ha già entrambe: non si unisce finché non se ne toglie una.
        with self.assertRaises(ValueError):
            cat_svc.unisci(altra_v.catalogo, cat)
        altra_v.attiva = False
        altra_v.save()
        self.assertEqual(cat_svc.unisci(altra_v.catalogo, cat), 1)
        altra_v.refresh_from_db()
        self.assertEqual((altra_v.catalogo_id, altra_v.nome), (cat.pk, "Lettura disegno tecnico"))

    def test_pagine_e_matrice(self):
        comp_svc.registra_livelli(self.ab_fresa, {self.v_fresa.pk: "U"}, user=self.admin)
        dati = cat_svc.matrice(self.reparto.pk)
        self.assertEqual(dati["righe"][0]["livelli"], ["U"])
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:mansionario_catalogo"))
        self.assertContains(resp, "Lettura del disegno")
        self.assertContains(resp, "Rinomina in tutte")
        resp = self.client.get(reverse("anagrafica:mansionario_matrice_competenze"), {"reparto": self.reparto.pk})
        self.assertContains(resp, "PROVA")
        resp = self.client.get(reverse("anagrafica:mansionario_matrice_competenze"),
                               {"reparto": self.reparto.pk, "formato": "xlsx"})
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse("anagrafica:mansionario_catalogo"),
                                {"competenza": self.v_fresa.catalogo_id, "azione": "rinomina", "nome": "Disegno F5"})
        self.assertEqual(VoceMacchinaCatalogo.objects.filter(nome="Disegno F5").count(), 2)

    def test_catalogo_negato_senza_permessi(self):
        utente = User.objects.create_user("f5_op", "f5op@example.invalid", "x")
        self.client.force_login(utente)
        resp = self.client.get(reverse("anagrafica:mansionario_catalogo"))
        self.assertEqual(resp.status_code, 302)
