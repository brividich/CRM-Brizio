"""Pagina del corso e-learning: stato chiaro, risultati unificati, export, conferma RSPP facoltativa."""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models_formazione import (
    TrainingAssignment, TrainingCourse, TrainingElearningEnrollment, TrainingPlan, TrainingQuizOption,
    TrainingQuizQuestion, TrainingSlide,
)
from .services import elearning_corso_gestione as g
from .services.elearning_fruizione import corso_pubblicato
from .services.elearning_link_aperto import attiva_o_rigenera, link_valido


class GestioneCorsoTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.el", "hr@example.com", "pwd12345")
        self.client.force_login(self.admin)
        piano = TrainingPlan.objects.create(codice="PE", nome="Piano")
        self.corso = TrainingCourse.objects.create(
            piano=piano, codice="EL231", titolo="Modello 231", durata_ore_teorica=Decimal("1"),
            is_elearning=True, stato="BOZZA", quiz_punteggio_minimo=66)
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="Intro", contenuto="Ciao")
        q = TrainingQuizQuestion.objects.create(corso=self.corso, ordine=1, testo="Domanda?")
        TrainingQuizOption.objects.create(domanda=q, ordine=1, testo="Sì", corretta=True)
        TrainingQuizOption.objects.create(domanda=q, ordine=2, testo="No")

    def test_pubblica_senza_regole_fad_e_link_aperto_funziona(self):
        self.client.post(reverse("anagrafica:formazione_elearning_publish_toggle", args=[self.corso.pk]))
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.stato, "ATTIVO")
        self.assertTrue(corso_pubblicato(self.corso))
        link = attiva_o_rigenera(self.corso, self.admin)
        self.assertIsNotNone(link_valido(link.token))

    def test_stato_corso(self):
        st = g.stato_corso(self.corso, n_slide=1, n_domande=1, n_invalid=0, link=None)
        self.assertFalse(st["visibile"])
        self.assertIn("Pubblica", st["frase"])
        self.corso.stato = "ATTIVO"
        st = g.stato_corso(self.corso, n_slide=1, n_domande=1, n_invalid=0, link=None)
        self.assertTrue(st["visibile"])
        self.assertEqual(st["link_stato"], "spento")

    def test_righe_unificate(self):
        TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=1, piano=self.corso.piano)
        from django.utils import timezone
        from .models_formazione import TrainingEmployeeRecord
        rec = TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=2,
                                                    data_completamento=timezone.localdate())
        TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=2, stato="COMPLETATO",
                                                   n_slide_totali=1, ultima_slide_ordine=1,
                                                   best_punteggio_pct=Decimal("100"), record_completamento=rec)
        righe = g.righe_risultati(self.corso)
        stati = {r["legacy_id"]: r["stato"] for r in righe}
        self.assertEqual(stati, {1: g.DA_INIZIARE, 2: g.COMPLETATO})
        num = g.numeri(righe)
        self.assertEqual((num["persone"], num["assegnati"], num["completati_pct"]), (2, 1, 50))

    def test_pagina_e_export(self):
        r = self.client.get(reverse("anagrafica:formazione_elearning_manage", args=[self.corso.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Non visibile ai dipendenti")
        self.assertContains(r, 'id="elg-assegna"')
        for tipo in g.EXPORT:
            for formato in ("xlsx", "pdf"):
                r = self.client.get(reverse("anagrafica:formazione_elearning_manage", args=[self.corso.pk]),
                                    {"export": tipo, "formato": formato})
                self.assertEqual(r.status_code, 200, (tipo, formato))
                self.assertIn("attachment", r["Content-Disposition"])


class LinkApertoUrlPubblicoTests(TestCase):
    def test_usa_site_url_in_https(self):
        from django.test import RequestFactory, override_settings
        from .views_elearning import url_link_aperto

        class L:
            token = "abc123"
        req = RequestFactory().get("/", HTTP_HOST="hub.cnovicrom.local")
        with override_settings(SITE_URL="https://hub.costruzioninovicrom.it", ELEARNING_LINK_APERTO_URL_PUBBLICO="",
                               RECEPTION_RICHIESTE_URL_PUBBLICO=""):
            self.assertEqual(url_link_aperto(req, L()), "https://hub.costruzioninovicrom.it/corso-aperto/abc123/")


class CompletamentoDaLinkApertoTests(TestCase):
    """Un corso completato dal link aperto (record senza iscrizione e-learning) risulta fatto."""

    def test_record_senza_iscrizione_conta_come_completato(self):
        from datetime import date
        from .models_formazione import TrainingEmployeeRecord
        piano = TrainingPlan.objects.create(codice="PLA", nome="Piano")
        corso = TrainingCourse.objects.create(piano=piano, codice="LA1", titolo="Corso link", durata_ore_teorica=Decimal("1"),
                                              is_elearning=True, stato="ATTIVO")
        TrainingSlide.objects.create(corso=corso, ordine=1, titolo="S", contenuto="x")
        TrainingEmployeeRecord.objects.create(corso=corso, legacy_anagrafica_id=160, data_completamento=date(2026, 11, 25))
        righe = g.righe_risultati(corso)
        self.assertEqual([(r["legacy_id"], r["stato"]) for r in righe], [(160, g.COMPLETATO)])
        from unittest import mock
        from core.models import UserOnboarding
        u = get_user_model().objects.create_user("dip.la", "d@example.com", "x")
        UserOnboarding.objects.create(user=u, completed=True)
        self.client.force_login(u)
        with mock.patch("anagrafica.views._current_legacy_anagrafica_id", return_value=160), \
                mock.patch("anagrafica.views._can_edit_formazione", return_value=False):
            r = self.client.get(reverse("anagrafica:formazione_online_catalog"))
        self.assertEqual([v["titolo"] for v in r.context["completati"]], ["Corso link"])
        self.assertEqual(r.context["da_fare"], [])
