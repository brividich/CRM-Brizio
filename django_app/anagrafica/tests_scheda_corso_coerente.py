"""Scheda del corso coerente (26/11/2026 sera): «A chi serve» con la spunta «Obbligatorio per tutti»,
«con il corso valido» da qualunque strada, stato automatico delle sessioni, candidati all'assegnazione.
Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models_elearning import TrainingElearningPartecipazioneAperta
from .models_formazione import TrainingCourse, TrainingEmployeeRecord, TrainingPlan, TrainingSession, TrainingSlide
from .services import training_eligibility as te

OGGI = timezone.localdate()
DIP = {1: {"nome": "ROSSI MARIO", "mansione": "", "reparto": ""},
       2: {"nome": "BIANCHI LAURA", "mansione": "", "reparto": ""},
       3: {"nome": "VERDI PAOLO", "mansione": "", "reparto": ""}}


class SchedaCorsoCoerenteTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.scheda", "hr@example.invalid", "pwd12345")
        self.client.force_login(self.admin)
        piano = TrainingPlan.objects.create(codice="PSC", nome="Piano sintetico")
        self.corso = TrainingCourse.objects.create(
            piano=piano, codice="SC1", titolo="Corso sintetico per tutti", durata_ore_teorica=Decimal("1"),
            is_elearning=True, is_active=True, stato="ATTIVO", validita_mesi=24, obbligatorio=True)
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="Intro", contenuto="Ciao")
        self.sess = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="SC1-E1", modalita="ONLINE", stato="PIANIFICATA",
            data_inizio=OGGI - timedelta(days=1), data_fine=OGGI + timedelta(days=30))
        TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=1, idoneo=True,
                                              data_completamento=OGGI, data_scadenza=OGGI + timedelta(days=700))
        TrainingElearningPartecipazioneAperta.objects.create(corso=self.corso, nome="Mario", cognome="Rossi",
                                                             completata_il=timezone.now())

    def test_candidati_obbligatorio_per_tutti(self):
        with mock.patch.object(te, "_dipendenti_attivi", return_value=DIP):
            res = te.candidati_corso(self.corso)
        self.assertTrue(res["pool_filtrato"])
        # 1 ha il corso valido (scadenza non ancora ricalcolata): non è candidato
        self.assertEqual(sorted(c["legacy_id"] for c in res["idonei"]), [2, 3])

    def test_pagina(self):
        with mock.patch.object(te, "_dipendenti_attivi", return_value=DIP):
            r = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Tutti i dipendenti in forza", body)
        self.assertNotIn("Non ancora collegato a nessuno", body)
        self.assertEqual(r.context["n_a_chi_serve"], 1)
        self.assertEqual(r.context["n_in_forza"], 3)
        m = r.context["come_si_fa"]
        self.assertEqual((m["completati_validi"], m["dal_link_aperto"]), (1, 1))
        self.assertIn("con il corso valido", body)
        self.sess.refresh_from_db()
        self.assertEqual(self.sess.stato, "IN_CORSO")
        self.assertEqual(r.context["sessioni_sub"], "1 in corso")
        self.assertIn("Da assegnare", body)
        self.assertEqual(len(r.context["candidati_assegnazione"]), 2)
