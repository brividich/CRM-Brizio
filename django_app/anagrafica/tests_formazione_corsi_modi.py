"""Riordino corsi: tipi di corso, piani doppi, filtri «Come si fa», online sul corso, modalità chiare."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models_formazione import (
    TrainingAssignment, TrainingCourse, TrainingCourseType, TrainingPlan, TrainingSession, TrainingSlide,
)
from .services import formazione_tipi as tipi
from .services.elearning_fruizione import corso_pubblicato, corsi_pubblicati


class CorsiModiTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.modi", "hr@example.com", "pwd12345")
        self.client.force_login(self.admin)
        self.piano = TrainingPlan.objects.create(codice="P1", nome="Componenti critici e il loro impatto sulla sicurezza")
        self.corso = TrainingCourse.objects.create(piano=self.piano, codice="C1", titolo="Corso aula",
                                                   durata_ore_teorica=Decimal("2"), stato="ATTIVO")
        TrainingSession.objects.create(corso=self.corso, codice_sessione="S1", modalita="IN_SEDE",
                                       data_inizio=date(2026, 11, 1), data_fine=date(2026, 11, 1))

    def test_tipi_iniziali_e_assegnazione_per_piano(self):
        self.assertTrue(TrainingCourseType.objects.filter(nome="Sicurezza").exists())
        tipo = TrainingCourseType.objects.create(nome="Prova tipo")
        self.assertEqual(tipi.assegna_tipo_a_piano(self.piano, tipo), 1)
        self.corso.refresh_from_db()
        self.assertEqual(self.corso.tipo, tipo)

    def test_doppioni_e_accorpa(self):
        tagliato = TrainingPlan.objects.create(codice="P2", nome="COMPONENTI CRITICI E IL LORO IMPATTO SULLA SICUREZ")
        c2 = TrainingCourse.objects.create(piano=tagliato, codice="C2", titolo="Altro", durata_ore_teorica=Decimal("1"))
        TrainingAssignment.objects.create(corso=c2, legacy_anagrafica_id=5, piano=tagliato)
        coppie = tipi.doppioni()
        self.assertEqual(len(coppie), 1)
        self.assertEqual(coppie[0]["togli"], tagliato)
        esito = tipi.accorpa(tagliato, self.piano)
        self.assertEqual((esito["corsi"], esito["assegnazioni"]), (1, 1))
        tagliato.refresh_from_db()
        self.assertFalse(tagliato.is_active)
        self.assertEqual(tipi.doppioni(), [])

    def test_non_doppi(self):
        altro = TrainingPlan.objects.create(codice="P3", nome="Componenti critici e il loro impatto sulla sicurezza.")
        self.assertEqual(len(tipi.doppioni()), 1)
        tipi.segna_non_doppi(altro, self.piano, "hr")
        self.assertEqual(tipi.doppioni(), [])

    def test_pagina_tipi(self):
        r = self.client.get(reverse("anagrafica:formazione_tipi_corso"))
        self.assertEqual(r.status_code, 200)
        self.client.post(reverse("anagrafica:formazione_tipi_corso_azione"), {"azione": "crea", "nome": "Ambiente"})
        self.assertTrue(TrainingCourseType.objects.filter(nome="Ambiente").exists())

    def test_elenco_filtri_come_si_fa(self):
        url = reverse("anagrafica:formazione_corsi_list")
        r = self.client.get(url, {"modo": "aula"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["page_obj"].paginator.count, 1)
        self.assertEqual(self.client.get(url, {"modo": "sempre"}).context["page_obj"].paginator.count, 0)
        conteggi = dict((k, n) for k, _e, n in r.context["modi_conteggi"])
        self.assertEqual(conteggi["aula"], 1)

    def test_online_sul_corso_visibile_solo_con_slide(self):
        url = reverse("anagrafica:formazione_corso_modo_online", args=[self.corso.pk])
        self.client.post(url, {"azione": "accendi"})
        self.corso.refresh_from_db()
        self.assertTrue(self.corso.is_elearning)
        self.assertFalse(corso_pubblicato(self.corso))
        self.assertFalse(corsi_pubblicati().filter(pk=self.corso.pk).exists())
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="S", contenuto="x")
        self.assertTrue(corso_pubblicato(self.corso))
        self.assertTrue(corsi_pubblicati().filter(pk=self.corso.pk).exists())
        r = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]))
        self.assertContains(r, "Come si fa questo corso")
        self.client.post(url, {"azione": "spegni"})
        self.corso.refresh_from_db()
        self.assertFalse(self.corso.is_elearning)

    def test_modalita_nomi_chiari(self):
        self.assertEqual(dict(TrainingSession.MODALITA_CHOICES)["IN_SEDE"], "In aula, in azienda")
        r = self.client.get(reverse("anagrafica:formazione_sessione_create"))
        self.assertContains(r, "Online in diretta")
        self.assertContains(r, "Vuoi che sia sempre aperto?")

    def test_i_miei_corsi_online(self):
        r = self.client.get(reverse("anagrafica:formazione_online_catalog"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "I miei corsi online")
        self.assertContains(r, "Da fare")
