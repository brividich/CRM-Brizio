"""Coerenza formazione (analisi 26/11/2026, punti 1, 11, 17, 20): una sola regola «stato persona × corso»,
un solo interruttore «online», rinnovo assegnabile dopo l'aula, esito onesto del link aperto. Dati sintetici."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models_elearning import TrainingElearningRispostaAperta
from .models_formazione import (
    TrainingAssignment, TrainingCourse, TrainingElearningEnrollment, TrainingEmployeeRecord, TrainingEnrollment,
    TrainingPlan, TrainingSession, TrainingSlide,
)
from .services import elearning_corso_gestione as g
from .services import formazione_completamento as fc
from .services.elearning_fruizione import ciclo_per_nuova_assegnazione

OGGI = timezone.localdate()


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.ag1", "hr@example.invalid", "pwd12345")
        self.client.force_login(self.admin)
        self.piano = TrainingPlan.objects.create(codice="PAG1", nome="Piano sintetico")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="AG1", titolo="Corso sintetico", durata_ore_teorica=Decimal("1"),
            is_elearning=True, is_active=True, stato="ATTIVO", validita_mesi=12)
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="Intro", contenuto="Ciao")
        self.sess = TrainingSession.objects.create(corso=self.corso, codice_sessione="AG1-S1", modalita="IN_SEDE",
                                                   data_inizio=date(2026, 1, 10), data_fine=date(2026, 1, 10))

    def record(self, lid, completato, scadenza=None, idoneo=True, **kw):
        return TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=lid,
                                                     data_completamento=completato, data_scadenza=scadenza,
                                                     idoneo=idoneo, **kw)

    def iscrivi(self, lid, stato="ISCRITTO", **kw):
        return TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=lid, stato=stato, **kw)


class StatoPersonaCorsoTests(_Base):
    def test_regola_unica(self):
        self.record(1, OGGI - timedelta(days=10), OGGI + timedelta(days=300))       # valido
        self.record(2, OGGI - timedelta(days=400), OGGI - timedelta(days=35))       # scaduto
        self.iscrivi(3, "COMPLETATO")                                              # senza record
        self.iscrivi(4, "ISCRITTO")
        self.iscrivi(5, "ASSENTE")
        self.record(6, OGGI - timedelta(days=400), OGGI - timedelta(days=35))       # scaduto ...
        self.iscrivi(6, "IN_CORSO", verifica_superata=True, data_verifica=OGGI)     # ... ma test superato dopo
        stati = fc.stati_persona_corso(self.corso, [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual({k: v.codice for k, v in stati.items()}, {
            1: fc.COMPLETATO, 2: fc.SCADUTO, 3: fc.DA_REGISTRARE, 4: fc.IN_CORSO, 5: fc.DA_FARE,
            6: fc.DA_REGISTRARE, 7: fc.DA_FARE})
        self.assertEqual(stati[4].etichetta, "Iscritto")
        self.assertEqual(stati[5].etichetta, "Assente")
        self.assertEqual(stati[2].data, OGGI - timedelta(days=35))
        self.assertEqual(fc.stato_persona_corso(self.corso, 1).etichetta, "Completato")

    def test_scheda_corso_non_dice_completato_a_scaduti_e_senza_record(self):
        e1 = self.iscrivi(1, "COMPLETATO")
        self.record(1, OGGI - timedelta(days=400), OGGI - timedelta(days=35), enrollment=e1, sessione=self.sess)
        self.iscrivi(2, "COMPLETATO")
        e3 = self.iscrivi(3, "COMPLETATO")
        self.record(3, OGGI, None, enrollment=e3, sessione=self.sess)
        resp = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.corso.pk]))
        self.assertEqual(resp.status_code, 200)
        stati = {d["legacy_id"]: d["stato_label"] for d in resp.context["dipendenti_iscritti"]}
        self.assertEqual(stati, {1: "Scaduto", 2: "Da registrare", 3: "Completato"})

    def test_pagina_iscritti_da_registrare(self):
        self.iscrivi(2, "IN_CORSO", verifica_superata=True, data_verifica=OGGI)
        resp = self.client.get(reverse("anagrafica:formazione_sessione_iscritti", args=[self.sess.pk]))
        self.assertContains(resp, "Da registrare")

    def test_etichetta_lezione_online(self):
        from .services import sessione_online as so
        self.assertEqual(so.ETICHETTE_STATO[so.SUPERATA], "Superata, da registrare")


class CorsoOnlineTests(_Base):
    def test_risultati_aula_conta_scaduto_no(self):
        self.record(1, OGGI - timedelta(days=5), OGGI + timedelta(days=360))
        self.record(2, OGGI - timedelta(days=400), OGGI - timedelta(days=35))
        TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=3, stato="COMPLETATO",
                                                   n_slide_totali=1, ultima_slide_ordine=1)
        righe = {r["legacy_id"]: r for r in g.righe_risultati(self.corso)}
        self.assertEqual(righe[1]["stato"], g.COMPLETATO)
        self.assertEqual((righe[2]["stato"], righe[2]["etichetta"]), (g.DA_INIZIARE, "Scaduto"))
        # Iscrizione e-learning «completata» senza completamento a libretto: da registrare, non completato.
        self.assertEqual((righe[3]["stato"], righe[3]["etichetta"]), (g.IN_CORSO, "Da registrare"))

    def test_risultati_assegnazione_dell_ultimo_ciclo(self):
        self.record(1, OGGI - timedelta(days=400), OGGI - timedelta(days=35))
        TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=1, stato="ASSEGNATO", ciclo=2)
        TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=1, stato="COMPLETATO", ciclo=1)
        riga = g.righe_risultati(self.corso)[0]
        self.assertEqual(riga["assegnazione"].ciclo, 2)
        self.assertEqual(riga["stato"], g.DA_INIZIARE)

    def test_hub_completati_da_ogni_strada_e_iscritti_persone(self):
        self.record(1, OGGI, None)                                                    # aula
        self.record(2, OGGI - timedelta(days=400), OGGI - timedelta(days=35))         # scaduto
        for ciclo in (1, 2):
            TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=3, ciclo=ciclo)
        resp = self.client.get(reverse("anagrafica:formazione_elearning_hub"))
        corso = next(r["corso"] for r in resp.context["rows"] if r["corso"].pk == self.corso.pk)
        self.assertEqual((corso.n_iscritti, corso.n_completati), (1, 1))

    def test_registro_e_andamento_con_link_aperto(self):
        from .services import elearning_report as report
        rec = self.record(9, OGGI, None)
        risposta = TrainingElearningRispostaAperta.objects.create(
            corso=self.corso, nome="Anna", cognome="Prova", superato=True, punteggio_pct=Decimal("100"),
            stato=TrainingElearningRispostaAperta.AUTO, legacy_anagrafica_id=9, record=rec)
        # Conta solo il completamento nato da quella risposta (nota «risposta #pk»).
        type(rec).objects.filter(pk=rec.pk).update(note=f"Completato dal link aperto; risposta #{risposta.pk}.")
        righe = report.registro(corso_id=self.corso.pk)
        self.assertEqual([r["fonte"] for r in righe], ["Link aperto"])
        self.assertEqual(report.andamento(corso_id=self.corso.pk)["totale_periodo"], 1)

    def test_spegni_online_tre_comandi_stesso_effetto(self):
        self.client.post(reverse("anagrafica:formazione_elearning_publish_toggle", args=[self.corso.pk]),
                         {"azione": "spegni"})
        self.corso.refresh_from_db()
        self.assertEqual((self.corso.stato, self.corso.is_elearning), ("ATTIVO", False))
        self.corso.is_elearning = True
        self.corso.save()
        self.client.post(reverse("anagrafica:formazione_corso_modo_online", args=[self.corso.pk]), {"azione": "spegni"})
        self.corso.refresh_from_db()
        self.assertEqual((self.corso.stato, self.corso.is_elearning), ("ATTIVO", False))
        self.corso.is_elearning = True
        self.corso.save()
        self.client.post(reverse("anagrafica:elearning_impostazioni_corsi"), {"corso_id": self.corso.pk, "azione": "online"})
        self.corso.refresh_from_db()
        self.assertEqual((self.corso.stato, self.corso.is_elearning), ("ATTIVO", False))

    def test_rinnovo_assegnabile_dopo_l_aula(self):
        a = TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=1, stato="ASSEGNATO")
        self.assertEqual(ciclo_per_nuova_assegnazione(self.corso, 1), 1)
        rec = self.record(1, OGGI, OGGI + timedelta(days=30), sessione=self.sess)
        fc.dopo_completamento(rec, storico=True)  # chiude l'assegnazione aperta
        a.refresh_from_db()
        self.assertEqual(a.stato, "COMPLETATO")
        self.assertEqual(ciclo_per_nuova_assegnazione(self.corso, 1), 2)


from .tests_elearning_link_aperto import _Base as _LinkBase  # noqa: E402


class LinkApertoEsitoTests(_LinkBase):
    def test_superato_non_abbinato_non_dice_completato(self):
        self.segui_corso(nome="Nessuno", cognome="Sconosciuto")
        r = self.consegna(self.giusta)
        self.assertContains(r, "Quiz superato: l&#x27;ufficio HR verifica i tuoi dati e registra il corso")
        self.assertNotContains(r, "Corso completato")
        self.assertFalse(TrainingEmployeeRecord.objects.exists())
