"""Passaggi tra uno step e l'altro: dopo l'azione si torna da dove si era o si va al passo dopo.

Dati sintetici.
"""
from __future__ import annotations

from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.legacy_models import AnagraficaDipendente

from .models import DipendenteQualifica, TipoQualifica
from .models_formazione import TrainingCourse, TrainingEnrollment, TrainingLesson, TrainingPlan, TrainingSession
from .tests import _ensure_anagrafica_table
from .views import _helpers

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class PassaggiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("ps_admin", "ps@example.invalid", "x")
        self.client.force_login(self.admin)
        self.p = AnagraficaDipendente.objects.create(nome="PIA", cognome="PASSO", aliasusername="ps.pia.t")
        piano = TrainingPlan.objects.create(codice="P-PS", nome="Piano sintetico")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="C-PS", titolo="Corso passi",
                                                   durata_ore_teorica=4, is_active=True)

    def _iscrivi(self, back="/anagrafica/mansionario/lacune/"):
        return self.client.post(reverse("anagrafica:formazione_rinnovo_da_scadenzario"),
                                {"corso_id": self.corso.pk, "dipendenti_selezionati": [self.p.pk], "back": back})

    def test_back_sicuro_accetta_percorsi_e_nomi_url(self):
        req = RequestFactory().get("/")
        self.assertEqual(_helpers.back_sicuro(req, "/anagrafica/scadenzario/"), "/anagrafica/scadenzario/")
        self.assertEqual(_helpers.back_sicuro(req, "anagrafica:scadenzario"), reverse("anagrafica:scadenzario"))
        self.assertEqual(_helpers.back_sicuro(req, "https://esterno.example/x"), "")

    def test_iscrivi_nuova_sessione_torna_alla_pagina_di_partenza(self):
        resp = self._iscrivi()
        self.assertIn("rinnovo=1", resp["Location"])
        form = self.client.get(resp["Location"])
        self.assertContains(form, "1 dipendente da iscrivere")
        self.assertContains(form, 'href="/anagrafica/mansionario/lacune/"')  # Annulla torna all'origine
        resp = self.client.post(reverse("anagrafica:formazione_sessione_create"), {
            "corso": self.corso.pk, "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": date.today().isoformat(), "data_fine": date.today().isoformat(), "sede": "Aula"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("back=%2Fanagrafica%2Fmansionario%2Flacune%2F", resp["Location"])
        self.assertTrue(TrainingEnrollment.objects.filter(legacy_anagrafica_id=self.p.pk).exists())
        iscritti = self.client.get(resp["Location"])
        self.assertContains(iscritti, "Torna a dove eri")

    def test_iscrivi_in_edizione_gia_pianificata(self):
        sess = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-PS1",
                                              data_inizio=date.today() + timedelta(days=7),
                                              data_fine=date.today() + timedelta(days=7))
        resp = self._iscrivi()
        self.assertContains(self.client.get(resp["Location"]), "Iscrivi qui")
        resp = self.client.post(reverse("anagrafica:formazione_rinnovo_in_sessione", args=[sess.pk]))
        self.assertIn("back=", resp["Location"])
        self.assertTrue(TrainingEnrollment.objects.filter(sessione=sess, legacy_anagrafica_id=self.p.pk).exists())

    def test_preselezione_vecchia_non_iscrive_per_sbaglio(self):
        self._iscrivi()
        self.client.get(f"{reverse('anagrafica:formazione_sessione_create')}?corso={self.corso.pk}")
        self.assertNotIn("rinnovo_preselect", self.client.session)

    def test_nome_url_come_back_funziona(self):
        self._iscrivi(back="anagrafica:formazione_scadenzario")
        self.assertEqual(self.client.session["rinnovo_preselect"]["back"], reverse("anagrafica:formazione_scadenzario"))

    def test_rinnovo_qualifica_torna_all_origine(self):
        tipo = TipoQualifica.objects.create(nome="Patentino passi", categoria=TipoQualifica.CAT_SICUREZZA)
        url = reverse("anagrafica:dipendente_qualifica_add", args=[self.p.pk])
        dati = {"tipo_id": tipo.pk, "data_conseguimento": date.today().isoformat()}
        resp = self.client.post(url, {**dati, "back": "/anagrafica/qualifiche/scadenzario/"})
        self.assertEqual(resp["Location"], "/anagrafica/qualifiche/scadenzario/")
        resp = self.client.post(url, dati)
        self.assertTrue(resp["Location"].endswith("#qualifiche"))
        self.assertTrue(DipendenteQualifica.objects.filter(tipo=tipo).exists())

    def test_scheda_con_rinnova_porta_il_back_nel_form(self):
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.p.pk]) + "?rinnova=1",
                               HTTP_REFERER="http://testserver/anagrafica/qualifiche/scadenzario/")
        self.assertEqual(resp.context["rinnova_back"], "/anagrafica/qualifiche/scadenzario/")

    def test_giornata_visite_ricorda_l_origine(self):
        resp = self.client.get(reverse("anagrafica:visite_mediche_nuova_sessione"),
                               HTTP_REFERER="http://testserver/anagrafica/libretto-sanitario/")
        self.assertContains(resp, 'name="back" value="/anagrafica/libretto-sanitario/"')

    def test_presenze_lezione_successiva_e_ultima(self):
        sess = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-PS2", data_inizio=date.today(),
                                              data_fine=date.today())
        l1 = TrainingLesson.objects.create(sessione=sess, numero=1, data=date.today(), ora_inizio=time(9),
                                           ora_fine=time(13), argomento="Uno")
        l2 = TrainingLesson.objects.create(sessione=sess, numero=2, data=date.today(), ora_inizio=time(14),
                                           ora_fine=time(18), argomento="Due")
        body = self.client.get(reverse("anagrafica:formazione_lezione_presenze", args=[sess.pk, l1.pk])).content.decode()
        self.assertIn(reverse("anagrafica:formazione_lezione_presenze", args=[sess.pk, l2.pk]), body)
        body = self.client.get(reverse("anagrafica:formazione_lezione_presenze", args=[sess.pk, l2.pk])).content.decode()
        self.assertIn("Esiti e completamenti", body)

    def test_azione_adempimento_per_tipo(self):
        req = RequestFactory().get("/")
        req.user = self.admin
        req.session = self.client.session
        html = render_to_string("anagrafica/partials/_azione_adempimento.html", {
            "tipo": "FORMAZIONE", "rif": self.corso.pk, "legacy_id": self.p.pk, "back": "/x/"}, request=req)
        self.assertIn(f'name="corso_id" value="{self.corso.pk}"', html)
        self.assertIn('name="back" value="/x/"', html)
        html = render_to_string("anagrafica/partials/_azione_adempimento.html", {
            "tipo": "DPI", "rif": 3, "legacy_id": self.p.pk, "back": "/x/"}, request=req)
        self.assertIn("#dpi", html)

    def test_onboarding_tutto_fatto_propone_chiusura(self):
        from types import SimpleNamespace
        pratica = SimpleNamespace(id=1, is_aperta=True)
        counts = {"percentuale": 100, "completati": 3, "eccezioni": 0, "da_fare": 0, "in_ritardo": 0, "fase_corrente": ""}
        req = RequestFactory().get("/")
        req.user = self.admin
        req.session = self.client.session
        html = render_to_string("anagrafica/partials/_onboarding_avanzamento.html",
                                {"pratica": pratica, "counts": counts}, request=req)
        self.assertIn("Chiudi la pratica", html)
        counts["da_fare"] = 1
        html = render_to_string("anagrafica/partials/_onboarding_avanzamento.html",
                                {"pratica": pratica, "counts": counts}, request=req)
        self.assertNotIn("Chiudi la pratica", html)
