"""Remediation formazione R1 (26/11/2026): chiusura dei completamenti, rinnovi, corsi online e link
aperto. Un completamento storico/scaduto/futuro non chiude un rinnovo; il link aperto non riusa un
completamento quando è un rinnovo; cicli da qualunque strada; niente doppioni dal portale; nessuna
assegnazione a chi è in regola; «I miei corsi online» con la regola unica; numeri e-learning coerenti.
Dati sintetici."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import DipendenteAnagraficaAziendale
from .models_elearning import TrainingElearningRispostaAperta as R
from .models_formazione import (
    TrainingAssignment, TrainingCompletionRule, TrainingCourse, TrainingElearningEnrollment, TrainingEmployeeRecord,
    TrainingPlan, TrainingSlide,
)
from .services import formazione_completamento as fc
from .tests_elearning_link_aperto import _Base as _BaseLink

OGGI = timezone.localdate()
PID = 8801


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.r1", "hr@example.invalid", "pwd12345")
        UserOnboarding.objects.get_or_create(user=self.admin, defaults={"completed": True})
        self.client.force_login(self.admin)
        self.piano = TrainingPlan.objects.create(codice="PR1", nome="Piano sintetico R1")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="R1", titolo="Corso sintetico R1", durata_ore_teorica=Decimal("1"),
            is_elearning=True, is_active=True, stato="ATTIVO", validita_mesi=12, versione="2")
        TrainingSlide.objects.create(corso=self.corso, ordine=1, titolo="Intro", contenuto="Ciao")

    def record(self, lid=PID, completato=OGGI, scadenza=None, idoneo=True, **kw):
        return TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=lid,
                                                     data_completamento=completato, data_scadenza=scadenza,
                                                     idoneo=idoneo, **kw)

    def assegna(self, lid=PID, giorni_fa=0, ciclo=1, stato="ASSEGNATO"):
        a = TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=lid, stato=stato, ciclo=ciclo)
        if giorni_fa:
            TrainingAssignment.objects.filter(pk=a.pk).update(data_assegnazione=OGGI - timedelta(days=giorni_fa))
            a.refresh_from_db()
        return a


# ── A) dopo_completamento chiude solo con un completamento valido e nel suo ciclo ──────────────

class ChiusuraCompletamentiTests(_Base):
    def test_scaduto_o_futuro_non_chiude(self):
        a = self.assegna()
        fc.dopo_completamento(self.record(completato=OGGI - timedelta(days=400), scadenza=OGGI - timedelta(days=30)),
                              storico=True)
        fc.dopo_completamento(self.record(completato=OGGI + timedelta(days=5), scadenza=None), storico=True)
        a.refresh_from_db()
        self.assertEqual(a.stato, "ASSEGNATO")

    def test_vicino_alla_scadenza_non_chiude_il_rinnovo_aperto_dopo(self):
        a = self.assegna()  # oggi
        e = TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=PID, ciclo=1)
        fc.dopo_completamento(self.record(completato=OGGI - timedelta(days=300), scadenza=OGGI + timedelta(days=40)),
                              storico=True)
        a.refresh_from_db()
        e.refresh_from_db()
        self.assertEqual((a.stato, e.stato), ("ASSEGNATO", "ISCRITTO"))

    def test_valido_chiude_assegnazione_e_iscrizione_elearning(self):
        a = self.assegna(giorni_fa=3)
        e = TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=PID, ciclo=1)
        rec = self.record(scadenza=OGGI + timedelta(days=365))
        fc.dopo_completamento(rec, storico=True)
        a.refresh_from_db()
        e.refresh_from_db()
        self.assertEqual((a.stato, e.stato, e.record_completamento_id), ("COMPLETATO", "COMPLETATO", rec.pk))

    def test_data_futura_non_vale_ovunque(self):
        self.record(completato=OGGI + timedelta(days=3))
        self.assertIsNone(fc.completamento_valido(self.corso, PID))
        self.assertEqual(fc.ids_con_completamento_valido(self.corso, [PID]), set())
        self.assertNotEqual(fc.stato_persona_corso(self.corso, PID).codice, fc.COMPLETATO)

    def test_sessione_online_non_si_chiude_con_un_completamento_scaduto(self):
        from .services.sessione_online import completa_iscrizioni_da_record
        rec = self.record(completato=OGGI - timedelta(days=400), scadenza=OGGI - timedelta(days=30))
        self.assertEqual(completa_iscrizioni_da_record(rec), 0)


# ── B) link aperto: niente riuso quando è un rinnovo ───────────────────────────────────────────

class LinkApertoRinnovoTests(_BaseLink):
    def _esito(self):
        return {"punteggio_pct": Decimal("100"), "n_corrette": 1, "n_totali": 1, "superato": True, "risposte": []}

    def _registra(self):
        from .services import elearning_link_aperto as la
        return la.registra(self.corso, nome="Mario", cognome="Rossi Sintetico", esito=self._esito(), avviato_il=None,
                           ip="", user_agent="")

    def _record(self, scadenza):
        return TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=self.dip.id,
                                                     data_completamento=OGGI - timedelta(days=20),
                                                     data_scadenza=scadenza, idoneo=True)

    def test_riusa_se_in_regola_e_senza_rinnovo(self):
        rec = self._record(OGGI + timedelta(days=300))
        self.assertEqual(self._registra().record_id, rec.pk)

    def test_rinnovo_assegnato_crea_nuovo_completamento(self):
        rec = self._record(OGGI + timedelta(days=300))
        a = TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=self.dip.id, ciclo=2)
        r = self._registra()
        self.assertNotEqual(r.record_id, rec.pk)
        a.refresh_from_db()
        self.assertEqual(a.stato, "COMPLETATO")

    def test_scadenza_vicina_crea_nuovo_completamento(self):
        rec = self._record(OGGI + timedelta(days=30))
        self.assertNotEqual(self._registra().record_id, rec.pk)

    def test_pagina_pubblica_non_mostra_la_data(self):
        TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=self.dip.id,
                                              data_completamento=date(2026, 3, 4), idoneo=True)
        self.registra(nome="Mario", cognome="Rossi Sintetico")
        r = self.anonimo.get(self.url("pronto"))
        self.assertContains(r, "già completato")
        self.assertNotContains(r, "04-03-2026")
        r = self.anonimo.get(self.url("quiz"))
        self.assertEqual(r.status_code, 409)
        self.assertNotContains(r, "04-03-2026", status_code=409)


# ── G) link aperto: regole sulla partecipazione e corso senza quiz ──────────────────────────────

class LinkApertoRegoleTests(_BaseLink):
    def test_max_tentativi_sulla_partecipazione(self):
        TrainingCompletionRule.objects.filter(corso=self.corso).update(el_max_tentativi=1)
        self.segui_corso()
        r = self.consegna(self.sbagliata)
        self.assertEqual(r.status_code, 200)
        r = self.anonimo.get(self.url("quiz"))
        self.assertEqual(r.status_code, 409)
        self.assertContains(r, "esaurito i tentativi", status_code=409)

    def test_corso_senza_quiz_registra_il_completamento(self):
        TrainingCompletionRule.objects.filter(corso=self.corso).update(el_richiede_quiz=False)
        self.segui_corso(nome="Mario", cognome="Rossi Sintetico")
        r = self.anonimo.get(self.url() + "?s=2")
        self.assertContains(r, "Concludi il corso")
        r = self.anonimo.get(self.url("quiz"))
        self.assertContains(r, "Concludi il corso")
        r = self.anonimo.post(self.url("quiz"), {})
        self.assertContains(r, "Corso completato")
        rec = TrainingEmployeeRecord.objects.get(corso=self.corso, legacy_anagrafica_id=self.dip.id)
        self.assertIn("risposta #", rec.note)
        r = self.anonimo.post(self.url("quiz"), {})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(TrainingEmployeeRecord.objects.filter(corso=self.corso).count(), 1)

    def test_hub_conta_quiz_da_abbinare(self):
        R.objects.create(corso=self.corso, nome="X", cognome="Y", superato=True, stato=R.DA_ABBINARE)
        R.objects.create(corso=self.corso, nome="X", cognome="Z", superato=False, stato=R.DA_ABBINARE)
        admin = get_user_model().objects.create_superuser("hr.r1b", "hrb@example.invalid", "pwd12345")
        UserOnboarding.objects.get_or_create(user=admin, defaults={"completed": True})
        self.client.force_login(admin)
        resp = self.client.get(reverse("anagrafica:formazione_elearning_hub"))
        self.assertEqual(resp.context["tot"]["da_abbinare"], 1)
        self.assertContains(resp, "Quiz superati da abbinare")


# ── C) cicli da qualunque strada ─────────────────────────────────────────────────────────────────

class CicliTests(_Base):
    def test_ciclo_con_completamento_a_libretto_senza_assegnazione(self):
        from .services.elearning_fruizione import ciclo_per_nuova_assegnazione
        self.assertEqual(ciclo_per_nuova_assegnazione(self.corso, PID), 1)
        self.record(completato=OGGI - timedelta(days=400), scadenza=OGGI - timedelta(days=30))
        self.assertEqual(ciclo_per_nuova_assegnazione(self.corso, PID), 2)

    def test_riassegna_parte_dai_completamenti(self):
        from .services.elearning_versioni import _riassegna
        self.record(lid=PID, scadenza=None, course_version_snapshot="1")       # aula, versione vecchia
        self.record(lid=PID + 1, scadenza=None, course_version_snapshot="2")   # versione corrente
        self.record(lid=PID + 2, scadenza=None)                                # versione ignota
        self.assertEqual(_riassegna(self.corso), 1)
        self.assertEqual(list(TrainingAssignment.objects.values_list("legacy_anagrafica_id", "ciclo")), [(PID, 2)])
        self.assertEqual(_riassegna(self.corso), 0)


# ── D) niente doppio completamento dal portale ──────────────────────────────────────────────────

class PortaleDoppioneTests(_Base):
    def test_completa_riusa_il_completamento_valido(self):
        from .services.elearning_completamento import completa
        rec = self.record(completato=OGGI - timedelta(days=10), scadenza=OGGI + timedelta(days=300))
        enr = TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=PID, ciclo=2)
        self.assertEqual(completa(enr, tentativo=None).pk, rec.pk)
        enr.refresh_from_db()
        self.assertEqual((enr.stato, enr.record_completamento_id), ("COMPLETATO", rec.pk))
        self.assertEqual(TrainingEmployeeRecord.objects.filter(corso=self.corso).count(), 1)

    def test_blocco_quiz_dice_gia_completato(self):
        from .services import elearning_quiz as quiz
        from .services.elearning_regole import regola_corso
        self.record(completato=date(2026, 6, 1), scadenza=OGGI + timedelta(days=300))
        enr = TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=PID)
        self.assertEqual(quiz.blocco(enr, regola_corso(self.corso), [1]), "Hai già completato questo corso il 01-06-2026.")

    def test_rinnovo_aperto_non_blocca(self):
        from .services import elearning_quiz as quiz
        from .services.elearning_regole import regola_corso
        self.record(completato=OGGI - timedelta(days=10), scadenza=OGGI + timedelta(days=300))
        self.assegna(ciclo=2)
        TrainingAssignment.objects.filter(corso=self.corso).update(data_assegnazione=OGGI)
        TrainingEmployeeRecord.objects.filter(corso=self.corso).update(data_completamento=OGGI - timedelta(days=10))
        enr = TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=PID, ciclo=2)
        self.assertNotIn("già completato", quiz.blocco(enr, regola_corso(self.corso), [1]))


# ── E) niente assegnazioni a chi è in regola ────────────────────────────────────────────────────

class AssegnaInRegolaTests(_Base):
    def test_assegna_salta_chi_e_in_regola(self):
        self.record(lid=PID, scadenza=OGGI + timedelta(days=300))
        self.record(lid=PID + 1, scadenza=OGGI + timedelta(days=30))  # in scadenza: si assegna
        resp = self.client.post(reverse("anagrafica:formazione_elearning_assign", args=[self.corso.pk]),
                                {"dipendenti_selezionati": [PID, PID + 1]}, follow=True)
        self.assertEqual(list(TrainingAssignment.objects.values_list("legacy_anagrafica_id", flat=True)), [PID + 1])
        self.assertContains(resp, "1 già in regola, non assegnati")

    def test_ids_in_regola(self):
        self.record(lid=PID, scadenza=None)
        self.record(lid=PID + 1, scadenza=OGGI + timedelta(days=10))
        self.assertEqual(fc.ids_in_regola(self.corso, [PID, PID + 1, PID + 2]), {PID})


# ── F) «I miei corsi online» ────────────────────────────────────────────────────────────────────

class CatalogoDiscenteTests(_Base):
    def test_rivedi_consultazione_per_chi_ha_completato(self):
        from .services.elearning_fruizione import accesso_discente
        self.corso.elearning_self_service = False
        self.corso.save()
        self.assertFalse(accesso_discente(self.corso, PID, is_editor=False).consentito)
        self.record(scadenza=None)
        acc = accesso_discente(self.corso, PID, is_editor=False)
        self.assertTrue(acc.consentito and acc.anteprima and acc.consultazione)

    def test_catalogo_scaduto_non_e_completato(self):
        from unittest import mock
        self.corso.elearning_self_service = True
        self.corso.save()
        rec = self.record(completato=OGGI - timedelta(days=400), scadenza=OGGI - timedelta(days=30))
        TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=PID, stato="COMPLETATO",
                                                   record_completamento=rec)
        with mock.patch("anagrafica.views_elearning._ctx_utente", return_value=(PID, False)):
            resp = self.client.get(reverse("anagrafica:formazione_online_catalog"))
        card = next(c for c in resp.context["cards"] if c["corso"].pk == self.corso.pk)
        self.assertNotEqual(card["stato"], "COMPLETATO")


# ── H) numeri e-learning ────────────────────────────────────────────────────────────────────────

class NumeriTests(_Base):
    def test_risultati_escludono_i_cessati(self):
        from .services import elearning_corso_gestione as g
        self.assegna(lid=PID)
        self.assegna(lid=PID + 1)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=PID + 1, data_cessazione=date(2026, 1, 31))
        righe = g.righe_risultati(self.corso)
        self.assertEqual(g.numeri(righe)["persone"], 1)
        self.assertTrue(next(r for r in righe if r["legacy_id"] == PID + 1)["cessato"])

    def test_report_esclude_annullati_e_risposte_che_riusano(self):
        from .services import elearning_report as report
        rec = self.record(lid=PID, note="Fatto in aula")
        R.objects.create(corso=self.corso, nome="A", cognome="B", superato=True, stato=R.AUTO,
                         legacy_anagrafica_id=PID, record=rec)
        self.assertEqual(report.registro(corso_id=self.corso.pk), [])
        rec2 = self.record(lid=PID + 1)
        r2 = R.objects.create(corso=self.corso, nome="C", cognome="D", superato=True, stato=R.AUTO,
                              legacy_anagrafica_id=PID + 1, record=rec2)
        TrainingEmployeeRecord.objects.filter(pk=rec2.pk).update(note=f"Completato dal link aperto; risposta #{r2.pk}.")
        self.assertEqual(report.andamento(corso_id=self.corso.pk)["totale_periodo"], 1)
        TrainingEmployeeRecord.objects.filter(pk=rec2.pk).update(annullato_il=timezone.now())
        self.assertEqual(report.andamento(corso_id=self.corso.pk)["totale_periodo"], 0)

    def test_digest_esclude_completati_e_cessati(self):
        from .services.elearning_notifications import iter_corsi_da_completare
        self.assegna(lid=PID, giorni_fa=5)
        self.assegna(lid=PID + 1, giorni_fa=5)
        self.assegna(lid=PID + 2, giorni_fa=5)
        self.record(lid=PID, completato=OGGI - timedelta(days=1), scadenza=OGGI + timedelta(days=300))
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=PID + 2, data_cessazione=date(2026, 1, 31))
        self.assertEqual([v.legacy_anagrafica_id for v in iter_corsi_da_completare()], [PID + 1])


class SessioniRigaTests(_Base):
    def test_collega_completamento_rifiuta_non_validi(self):
        from .services.sessioni import collega_completamento
        rec = self.record(completato=OGGI - timedelta(days=400), scadenza=OGGI - timedelta(days=30))
        self.assertEqual(collega_completamento(rec), 0)
        self.assertFalse(fc.record_valido(rec))
        self.assertTrue(fc.record_valido(self.record(lid=PID + 5)))
