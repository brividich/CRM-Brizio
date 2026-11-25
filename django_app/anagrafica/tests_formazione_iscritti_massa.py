"""Iscrizione in blocco a una sessione dal pannello «Aggiungi iscritti»."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import DipendenteAnagraficaAziendale
from .models_formazione import TrainingCourse, TrainingEmployeeRecord, TrainingEnrollment, TrainingPlan, TrainingSession
from .services import elearning_corso_gestione as g


class IscrittiMassaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.massa", "hr@example.com", "pwd12345")
        self.client.force_login(self.admin)
        piano = TrainingPlan.objects.create(codice="PM", nome="Piano")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="CM", titolo="Corso", durata_ore_teorica=Decimal("1"),
                                                   validita_mesi=12)
        oggi = timezone.localdate()
        self.sessione = TrainingSession.objects.create(corso=self.corso, codice_sessione="SM1", modalita="ONLINE",
                                                       data_inizio=oggi, data_fine=oggi + timedelta(days=10))

    def test_iscrizione_in_blocco_e_ritorno(self):
        url = reverse("anagrafica:formazione_iscrizione_bulk", args=[self.sessione.pk])
        r = self.client.post(url, {"dipendenti_selezionati": ["11", "12", "13"], "next": "/anagrafica/"})
        self.assertRedirects(r, "/anagrafica/", fetch_redirect_response=False)
        self.assertEqual(TrainingEnrollment.objects.filter(sessione=self.sessione).count(), 3)
        self.client.post(url, {"dipendenti_selezionati": ["11", "14"]})
        self.assertEqual(TrainingEnrollment.objects.filter(sessione=self.sessione).count(), 4)

    def test_stato_rispetto_al_corso(self):
        for lid in (21, 22, 23):
            DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=lid)
        oggi = timezone.localdate()
        TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=22, data_completamento=oggi,
                                              data_scadenza=oggi + timedelta(days=30))
        TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=23, data_completamento=oggi,
                                              data_scadenza=oggi + timedelta(days=300))
        from unittest import mock
        righe = {i: {"id": i, "nome": "N", "cognome": f"C{i}", "utente_id": None} for i in (21, 22, 23)}
        with mock.patch.object(g, "_anagrafica", return_value=righe):
            stati = {p["legacy_id"]: p["stato"] for p in g.persone_iscrivibili(self.sessione)}
        self.assertEqual(stati, {21: "da_formare", 22: "in_scadenza", 23: "in_regola"})

    def test_pagina_iscritti_ha_il_pannello(self):
        r = self.client.get(reverse("anagrafica:formazione_sessione_iscritti", args=[self.sessione.pk]))
        self.assertContains(r, 'id="pim-side"')
        self.assertContains(r, "+ Aggiungi iscritti")
