"""Scheda della competenza e filo ruolo ↔ mansione ↔ competenza.

Dati sintetici.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.legacy_models import AnagraficaDipendente

from .models import AbilitazioneMacchina, AbilitazioneMacchinaVoce, CompetenzaCatalogo, CompetenzaSkm, RuoloOperativo
from .models_formazione import TrainingCourse, TrainingDeadline, TrainingPlan
from .models_skillmatrix import VoceMacchinaCatalogo
from .services import competenze_catalogo as cat_svc
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class SchedaCompetenzaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("sc_admin", "sc@example.invalid", "x")
        self.client.force_login(self.admin)
        self.ruolo = RuoloOperativo.objects.create(nome="Operatore sintetico")
        self.m1 = CompetenzaSkm.objects.create(competenza_key="P-TOR", display="Tornitura sintetica",
                                               tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.m2 = CompetenzaSkm.objects.create(competenza_key="P-FRE", display="Fresatura sintetica",
                                               tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.m1.ruoli.add(self.ruolo)
        piano = TrainingPlan.objects.create(codice="P-SC", nome="Piano sintetico")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="C-DIS", titolo="Lettura disegno base",
                                                   durata_ore_teorica=4, validita_mesi=0, is_active=True)
        self.cat = CompetenzaCatalogo.objects.create(nome="Lettura del disegno", chiave="lettura del disegno")
        self.v1 = VoceMacchinaCatalogo.objects.create(codice="SC-1", nome="Lettura del disegno", mansione=self.m1,
                                                      catalogo=self.cat, livello_minimo="U")
        self.v2 = VoceMacchinaCatalogo.objects.create(codice="SC-2", nome="Lettura del disegno", mansione=self.m2,
                                                      catalogo=self.cat, livello_minimo="L", corso=self.corso)
        self.ok = AnagraficaDipendente.objects.create(nome="ANNA", cognome="BRAVA", aliasusername="sc.ok.t")
        self.sotto = AnagraficaDipendente.objects.create(nome="BRUNO", cognome="SOTTO", aliasusername="sc.sotto.t")
        self.nuovo = AnagraficaDipendente.objects.create(nome="CARLO", cognome="NUOVO", aliasusername="sc.nuovo.t")
        self.senza = AnagraficaDipendente.objects.create(nome="DORA", cognome="SENZACORSO", aliasusername="sc.req.t")
        for p, lv in ((self.ok, "U"), (self.sotto, "L"), (self.nuovo, None)):
            a = AbilitazioneMacchina.objects.create(legacy_anagrafica_id=p.pk, competenza=self.m1, livello="L",
                                                    in_lista=True)
            if lv:
                AbilitazioneMacchinaVoce.objects.create(abilitazione=a, voce=self.v1, livello=lv)
        a = AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.senza.pk, competenza=self.m2, livello="L",
                                                in_lista=True)
        AbilitazioneMacchinaVoce.objects.create(abilitazione=a, voce=self.v2, livello="U")
        self.url = reverse("anagrafica:mansionario_competenza", args=[self.cat.pk])

    def test_stati_calcolati_come_nella_mansione(self):
        dati = cat_svc.scheda(self.cat)
        stati = {p["legacy_id"]: p["stato"] for p in dati["persone"]}
        self.assertEqual(stati[self.ok.pk], cat_svc.STATO_OK)
        self.assertEqual(stati[self.sotto.pk], cat_svc.STATO_SOTTO)
        self.assertEqual(stati[self.nuovo.pk], cat_svc.STATO_DA_VALUTARE)
        self.assertEqual(stati[self.senza.pk], cat_svc.STATO_REQUISITO)
        self.assertEqual(dati["conta"], {"requisito": 1, "da_valutare": 1, "sotto": 1, "ok": 1})
        # Prima chi ha qualcosa da sistemare: il requisito mancante in cima.
        self.assertEqual(dati["persone"][0]["legacy_id"], self.senza.pk)
        # Senza corso il livello U si ferma a «I».
        self.assertEqual(dati["persone"][0]["mansioni"][0]["livello"], "I")

    def test_corso_valido_toglie_il_requisito(self):
        TrainingDeadline.objects.create(legacy_anagrafica_id=self.senza.pk, corso=self.corso, is_required=True,
                                        data_scadenza=None, stato_scadenza="UNA_TANTUM")
        stati = {p["legacy_id"]: p["stato"] for p in cat_svc.scheda(self.cat)["persone"]}
        self.assertEqual(stati[self.senza.pk], cat_svc.STATO_OK)

    def test_pagina_filo_e_azioni(self):
        body = self.client.get(self.url).content.decode()
        self.assertIn("Lettura del disegno", body)
        # Filo a ritroso: ruolo e mansioni.
        self.assertIn(f'#ruolo-{self.ruolo.pk}"', body)
        self.assertIn(reverse("anagrafica:mansionario_mansione", args=[self.m1.pk]), body)
        self.assertIn(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]), body)
        # Requisito: iscrivi chi manca, solo chi non ha il corso.
        self.assertIn("Iscrivi chi manca (1)", body)
        self.assertIn(f'name="dipendenti_selezionati" value="{self.senza.pk}"', body)
        self.assertNotIn(f'name="dipendenti_selezionati" value="{self.ok.pk}"', body)
        self.assertIn(">Valuta<", body)
        self.assertIn(">Rivaluta<", body)

    def test_catalogo_e_mansione_portano_alla_scheda(self):
        body = self.client.get(reverse("anagrafica:mansionario_catalogo")).content.decode()
        self.assertIn(self.url, body)
        self.assertIn("Lettura disegno base", body)
        body = self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.m1.pk])).content.decode()
        self.assertIn(self.url, body)
        self.assertIn(f'#ruolo-{self.ruolo.pk}"', body)

    def test_ruolo_e_mansionario_collegati_nei_due_sensi(self):
        body = self.client.get(reverse("anagrafica:mansionario")).content.decode()
        self.assertIn(f'id="ruolo-{self.ruolo.pk}"', body)
        self.assertIn(f'{reverse("anagrafica:ruoli_operativi_list")}#ruolo-{self.ruolo.pk}', body)
        body = self.client.get(reverse("anagrafica:ruoli_operativi_list")).content.decode()
        self.assertIn(f'id="ruolo-{self.ruolo.pk}"', body)
        self.assertIn("Tornitura sintetica", body)
        self.assertIn(f'{reverse("anagrafica:mansionario")}#ruolo-{self.ruolo.pk}', body)

    def test_senza_permessi_niente_scheda(self):
        utente = User.objects.create_user("sc_base", "b@example.invalid", "x")
        self.client.force_login(utente)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("Lettura del disegno", resp.content.decode())
