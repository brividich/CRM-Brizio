"""Formazione HR — ente formativo del corso e ripiego docente/ente in sessione.

Il corso a catalogo non aveva alcun collegamento all'ente che lo eroga: solo
la sessione e la lezione avevano un docente. Qui si presidiano la regola di
ripiego di `TrainingSession.erogatore_display` (docente se valorizzato,
altrimenti ente formativo del corso) e la visibilità del campo in scheda
corso e nella ricerca globale.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import (
    TrainingCourse,
    TrainingInstructor,
    TrainingPlan,
    TrainingProvider,
    TrainingSession,
)

User = get_user_model()


class ErogatoreDisplayTests(TestCase):
    def setUp(self):
        self.piano = TrainingPlan.objects.create(codice="ENT", nome="Piano Enti")
        self.ente = TrainingProvider.objects.create(nome="Ente Test SRL")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="ENT-01", titolo="Corso con ente",
            durata_ore_teorica=Decimal("8.00"), stato="ATTIVO",
            ente_formativo=self.ente,
        )

    def _sessione(self, **kw):
        return TrainingSession.objects.create(
            corso=self.corso, codice_sessione=kw.pop("codice_sessione", "ENT-01-S1"),
            data_inizio=date(2026, 5, 4), data_fine=date(2026, 5, 4), **kw,
        )

    def test_docente_valorizzato_vince_sull_ente(self):
        docente = TrainingInstructor.objects.create(nome="Mario Rossi")
        sess = self._sessione(docente=docente, docente_nome="Mario Rossi")
        self.assertEqual(sess.erogatore_display, "Mario Rossi")

    def test_senza_docente_ripiega_su_ente_del_corso(self):
        sess = self._sessione()
        self.assertEqual(sess.erogatore_display, "Ente Test SRL")

    def test_senza_docente_ne_ente_stringa_vuota(self):
        self.corso.ente_formativo = None
        self.corso.save()
        sess = self._sessione()
        self.assertEqual(sess.erogatore_display, "")


@override_settings(LEGACY_AUTH_ENABLED=False)
class CorsoEnteFormativoUiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("ente_ui", "e@b.c", "pwd12345")
        self.client.force_login(self.user)
        self.piano = TrainingPlan.objects.create(codice="ENT2", nome="Piano Enti UI")
        self.ente = TrainingProvider.objects.create(nome="Formatori Riuniti")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="ENT2-01", titolo="Corso ente visibile",
            durata_ore_teorica=Decimal("4.00"), stato="ATTIVO",
            ente_formativo=self.ente,
        )

    def test_scheda_corso_mostra_ente_formativo(self):
        resp = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Formatori Riuniti")

    def test_ricerca_globale_trova_corso_per_ente(self):
        resp = self.client.get(reverse("anagrafica:formazione_ricerca"), {"q": "Formatori Riuniti"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.corso, resp.context["risultati"]["corsi"])
