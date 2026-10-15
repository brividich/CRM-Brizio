"""Dashboard formazione · copertura dei corsi obbligatori (stile C).

Una scheda per corso obbligatorio: quante persone a cui il corso è richiesto sono
in regola, in scadenza, scadute o mai formate, e la prossima sessione. I numeri
vengono dalla stessa cache dei KPI (TrainingDeadline), quindi devono tornare con
essi; i corsi non obbligatori non compaiono.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models_formazione import (
    TrainingCourse,
    TrainingDeadline,
    TrainingEnrollment,
    TrainingPlan,
    TrainingSession,
)
from .views import _copertura_corsi_obbligatori

User = get_user_model()


def _corso(codice, titolo, piano="Emergenze", validita=60):
    p, _ = TrainingPlan.objects.get_or_create(codice=piano[:10].upper(), defaults={"nome": piano})
    return TrainingCourse.objects.create(
        piano=p, codice=codice, titolo=titolo, durata_ore_teorica=Decimal("8.00"),
        validita_mesi=validita, stato="ATTIVO", obbligatorio=True,
    )


def _scadenze(corso, stati, required=True, primo_id=1000):
    for i, stato in enumerate(stati):
        TrainingDeadline.objects.create(
            corso=corso, legacy_anagrafica_id=primo_id + i, stato_scadenza=stato, is_required=required,
        )


class CoperturaCorsiObbligatoriTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.antincendio = _corso("AI-05", "Antincendio aggiornamento")
        self.primo = _corso("PS-12", "Primo soccorso")
        _scadenze(self.antincendio, ["VALIDO"] * 6 + ["UNA_TANTUM", "IN_SCADENZA_30", "SCADUTO", "MAI_FREQUENTATO"])
        _scadenze(self.primo, ["VALIDO"] * 4 + ["IN_SCADENZA_90"], primo_id=2000)

    def test_conta_per_stato_e_tratta_una_tantum_come_in_regola(self):
        righe = {r["corso"].codice: r for r in _copertura_corsi_obbligatori(self.oggi)}
        ai = righe["AI-05"]
        self.assertEqual((ai["ok"], ai["s30"], ai["ko"], ai["mai"], ai["totale"]), (7, 1, 1, 1, 10))
        self.assertEqual(ai["perc_ok"], 70)
        self.assertEqual(ai["scoperti"], 3)

    def test_prima_i_corsi_piu_scoperti(self):
        codici = [r["corso"].codice for r in _copertura_corsi_obbligatori(self.oggi)]
        self.assertEqual(codici, ["AI-05", "PS-12"])

    def test_le_scadenze_non_obbligatorie_non_contano(self):
        facoltativo = _corso("EX-01", "Excel avanzato", piano="Professionale")
        _scadenze(facoltativo, ["SCADUTO", "SCADUTO"], required=False, primo_id=3000)
        codici = [r["corso"].codice for r in _copertura_corsi_obbligatori(self.oggi)]
        self.assertNotIn("EX-01", codici)

    def test_i_segmenti_della_barra_sommano_a_cento(self):
        for r in _copertura_corsi_obbligatori(self.oggi):
            self.assertAlmostEqual(sum(s["perc"] for s in r["segmenti"]), 100, delta=0.1)
            self.assertTrue(all(s["n"] for s in r["segmenti"]))

    def test_prossima_sessione_pianificata_con_iscritti(self):
        passata = TrainingSession.objects.create(
            corso=self.antincendio, codice_sessione="AI-05-E0",
            data_inizio=self.oggi - timedelta(days=3), data_fine=self.oggi - timedelta(days=3),
        )
        annullata = TrainingSession.objects.create(
            corso=self.antincendio, codice_sessione="AI-05-E1", stato="ANNULLATA",
            data_inizio=self.oggi + timedelta(days=2), data_fine=self.oggi + timedelta(days=2),
        )
        prossima = TrainingSession.objects.create(
            corso=self.antincendio, codice_sessione="AI-05-E2",
            data_inizio=self.oggi + timedelta(days=8), data_fine=self.oggi + timedelta(days=8),
        )
        TrainingSession.objects.create(
            corso=self.antincendio, codice_sessione="AI-05-E3",
            data_inizio=self.oggi + timedelta(days=30), data_fine=self.oggi + timedelta(days=30),
        )
        for i in range(3):
            TrainingEnrollment.objects.create(sessione=prossima, legacy_anagrafica_id=1000 + i)
        ai = {r["corso"].codice: r for r in _copertura_corsi_obbligatori(self.oggi)}["AI-05"]
        self.assertEqual(ai["prossima"].pk, prossima.pk)
        self.assertEqual(ai["prossima"].n_iscritti, 3)
        self.assertNotIn(ai["prossima"].pk, (passata.pk, annullata.pk))

    def test_senza_scadenze_nessuna_scheda(self):
        TrainingDeadline.objects.all().delete()
        self.assertEqual(_copertura_corsi_obbligatori(date(2026, 10, 15)), [])


class DashboardFormazioneCoperturaPaginaTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("fd_admin", "fd@e.it", "pwd12345"))

    def test_la_pagina_mostra_le_schede_e_i_link_allo_scadenzario(self):
        corso = _corso("AI-05", "Antincendio aggiornamento")
        _scadenze(corso, ["VALIDO", "SCADUTO"])
        r = self.client.get(reverse("anagrafica:formazione_dashboard"))
        self.assertEqual(r.status_code, 200)
        scad = reverse("anagrafica:formazione_scadenzario")
        self.assertContains(r, "Copertura dei corsi obbligatori")
        self.assertContains(r, f"{scad}?corso={corso.pk}")
        self.assertContains(r, f"{scad}?stato=SCADUTO")
        self.assertContains(r, "50%")
        self.assertNotContains(r, "{#")

    def test_senza_dati_la_pagina_spiega_perche(self):
        r = self.client.get(reverse("anagrafica:formazione_dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Lo scadenzario non è ancora stato calcolato.")
        # Le aree del modulo restano tutte raggiungibili
        self.assertContains(r, reverse("anagrafica:formazione_ccnl_dashboard"))
        self.assertContains(r, reverse("anagrafica:formazione_plan"))
