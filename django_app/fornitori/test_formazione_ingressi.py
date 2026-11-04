"""Ingresso del docente esterno (GuestPortal) collegato a una sessione formativa."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models_formazione import (
    TrainingCourse, TrainingInstructor, TrainingLesson, TrainingPlan, TrainingProvider, TrainingSession,
)
from fornitori import guestportal as gp
from fornitori import ingressi as ing
from fornitori.models import IngressoIntervento
from fornitori.nomi import chiave_persona

GP_DB = {"GUESTPORTAL_DB_HOST": "db", "GUESTPORTAL_DB_NAME": "GuestManagement", "GUESTPORTAL_DB_USER": "hub_ro"}
OGGI = date.today()


def _accesso(visita_id=21, nome="ROSSI Mario", azienda="Ente Formazione Esempio Srl", **extra):
    dati = dict(
        visita_id=visita_id, stato="CHECKEDOUT", tipo="CONSULTANT", nome=nome, azienda=azienda,
        referente="Referente", motivo="Corso", badge="07",
        ingresso=datetime.combine(OGGI, time(8, 30)), uscita=datetime.combine(OGGI, time(13, 15)),
    )
    dati.update(extra)
    return gp.Accesso(**dati)


class ChiavePersonaTests(TestCase):
    def test_ordine_maiuscole_accenti(self):
        self.assertEqual(chiave_persona("ROSSI Mario"), chiave_persona("mario rossi"))
        self.assertEqual(chiave_persona("Niccolò De Sanctis"), chiave_persona("DE SANCTIS NICCOLO"))

    def test_una_sola_parola_non_basta(self):
        self.assertEqual(chiave_persona("Rossi"), "")


@override_settings(**GP_DB)
class FormazioneIngressiTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("gp.for", "gp.for@example.com", "pwd12345")
        self.client.force_login(self.admin)
        ente = TrainingProvider.objects.create(nome="Ente Formazione Esempio S.r.l.")
        self.docente = TrainingInstructor.objects.create(nome="Mario Rossi", tipo="ESTERNO", azienda=ente)
        piano = TrainingPlan.objects.create(codice="PGP", nome="Piano")
        corso = TrainingCourse.objects.create(piano=piano, codice="CGP", titolo="Carrelli elevatori", durata_ore_teorica=4)
        self.sessione = TrainingSession.objects.create(
            corso=corso, codice_sessione="SGP1", data_inizio=OGGI, data_fine=OGGI, docente=self.docente,
            docente_nome="Mario Rossi",
        )
        TrainingLesson.objects.create(sessione=self.sessione, numero=1, data=OGGI,
                                      ora_inizio=time(9, 0), ora_fine=time(13, 0), argomento="Teoria")
        self.iv = ing.intervento(ing.TIPO_FORMAZIONE, self.sessione.pk)

    def test_proposte_per_nome_docente_o_ente(self):
        righe = [
            _accesso(21),
            _accesso(22, nome="Altro Visitatore", azienda="ENTE FORMAZIONE ESEMPIO"),
            _accesso(23, nome="Persona Estranea", azienda="Altra Ditta"),
        ]
        with patch.object(gp, "storico", return_value=(righe, False)):
            proposte = ing.proposte(self.iv)
        self.assertEqual([a.visita_id for a in proposte], [21, 22])

    def test_collega_senza_ditta_e_confronto_ore(self):
        with patch.object(gp, "visita", return_value=_accesso()):
            link = ing.collega(self.iv, 21, utente=self.admin, modo="PROPOSTA")
        self.assertEqual(link.sessione_formazione, self.sessione)
        self.assertIsNone(link.fornitore)
        self.assertEqual(link.nota_ditta, "")
        confronto = ing.confronto_ore(self.iv, list(self.iv.collegamenti()))
        self.assertEqual((confronto.presenza_minuti, confronto.dichiarate_minuti), (285, 240))
        self.assertFalse(confronto.da_controllare)

    def test_sessione_chiusa_si_collega_annullata_no(self):
        self.sessione.stato = "COMPLETATA"
        self.sessione.save()
        iv = ing.intervento(ing.TIPO_FORMAZIONE, self.sessione.pk)
        with patch.object(gp, "visita", return_value=_accesso()):
            ing.collega(iv, 21, utente=self.admin, modo="MANUALE")
        self.sessione.stato = "ANNULLATA"
        self.sessione.save()
        iv = ing.intervento(ing.TIPO_FORMAZIONE, self.sessione.pk)
        with patch.object(gp, "visita", return_value=_accesso(22)), self.assertRaises(ing.CollegamentoNonValido):
            ing.collega(iv, 22, utente=self.admin, modo="MANUALE")

    def test_riquadro_sessione(self):
        url = reverse("fornitori:presenze_intervento", args=["formazione", self.sessione.pk])
        with patch.object(gp, "storico", return_value=([_accesso()], False)), patch.object(gp, "visita", return_value=None):
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Presenze in azienda del docente")
        self.assertContains(resp, "Ingressi del docente o dell")
        self.assertNotContains(resp, "Nessuna ditta")

        with patch.object(gp, "visita", return_value=_accesso()), patch.object(gp, "storico", return_value=([], False)), \
                patch("fornitori.views.log_action"):
            resp = self.client.post(reverse("fornitori:presenze_collega", args=["formazione", self.sessione.pk]),
                                    {"visita_id": "21", "modo": "PROPOSTA"})
        self.assertContains(resp, "collegato")
        self.assertEqual(self.sessione.ingressi_esterni.count(), 1)

        link = self.sessione.ingressi_esterni.get()
        with patch.object(gp, "storico", return_value=([], False)), patch.object(gp, "visita", return_value=None), \
                patch("fornitori.views.log_action"):
            resp = self.client.post(reverse("fornitori:presenze_scollega", args=[link.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.sessione.ingressi_esterni.exists())

    def test_senza_permesso_formazione_403(self):
        with patch("anagrafica.views._helpers._can_view_formazione", return_value=False), \
                patch("anagrafica.views._helpers._can_edit_formazione", return_value=False):
            resp = self.client.get(reverse("fornitori:presenze_intervento", args=["formazione", self.sessione.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_collega_da_ingresso_propone_la_sessione_del_giorno(self):
        url = reverse("fornitori:ingresso_collega", args=[21])
        with patch.object(gp, "visita", return_value=_accesso()):
            resp = self.client.get(url)
            self.assertContains(resp, "Sessione SGP1")
            self.assertContains(resp, "Carrelli elevatori")
            with patch("fornitori.views.log_action"):
                resp = self.client.post(url, {"tipo": "formazione", "pk": str(self.sessione.pk)})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(IngressoIntervento.objects.filter(visita_gp_id=21, sessione_formazione=self.sessione).exists())

    def test_sessione_di_altro_giorno_non_proposta(self):
        self.sessione.data_inizio = self.sessione.data_fine = OGGI - timedelta(days=5)
        self.sessione.save()
        with patch.object(gp, "visita", return_value=_accesso()):
            resp = self.client.get(reverse("fornitori:ingresso_collega", args=[21]))
        self.assertNotContains(resp, "Sessione SGP1")

    def test_accessi_esterni_e_pagina_sessione(self):
        IngressoIntervento.objects.create(visita_gp_id=21, sessione_formazione=self.sessione, ingresso=timezone.now())
        self.assertEqual(ing.interventi_per_visite([21])[21][0][0], "Formazione SGP1")
        resp = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[self.sessione.pk]))
        self.assertContains(resp, reverse("fornitori:presenze_intervento", args=["formazione", self.sessione.pk]))

    def test_docente_interno_senza_collegamenti_niente_riquadro(self):
        self.docente.tipo = "INTERNO"
        self.docente.save()
        resp = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[self.sessione.pk]))
        self.assertNotContains(resp, reverse("fornitori:presenze_intervento", args=["formazione", self.sessione.pk]))
