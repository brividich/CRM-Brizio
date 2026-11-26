"""Remediation formazione R2 (26/11/2026): edizioni e sessioni.

Stato non modificabile a mano, edizioni annullate, lezione online su edizioni chiuse,
sessioni miste, presenze per turno, proposta di chiusura (ex dipendenti, già completati),
annullamento di un completamento, stato effettivo, conteggi, QR d'aula, promemoria,
edizione collegata delle sessioni competenze. Solo dati sintetici.
"""
from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import TrainingSessionForm
from .models_formazione import (
    TrainingAssignment,
    TrainingCourse,
    TrainingEfficacia,
    TrainingElearningEnrollment,
    TrainingEmployeeRecord,
    TrainingEnrollment,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingSession,
)
from .services import formazione_aula as aula
from .services import formazione_integrita as fi
from .services import sessione_online as so
from .services.formazione_completamento import IN_CORSO, stati_persona_corso

A, B, C = 7201, 7202, 7203
NOMI = {A: "ROSSI MARIO", B: "BIANCHI LAURA", C: "VERDI ANNA"}
OGGI = timezone.localdate()
IERI = OGGI - timedelta(days=1)


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.r2", "hr@example.com", "pwd12345")
        self.client.force_login(self.admin)
        piano = TrainingPlan.objects.create(codice="PR2", nome="Piano R2")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="R2-1", titolo="Corso R2",
                                                   durata_ore_teorica=Decimal("4"), stato="ATTIVO")
        self.s = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-R2-1", modalita="IN_SEDE",
                                                data_inizio=IERI, data_fine=IERI, docente_nome="Docente",
                                                stato="IN_CORSO")
        self.ea = TrainingEnrollment.objects.create(sessione=self.s, legacy_anagrafica_id=A)
        self.eb = TrainingEnrollment.objects.create(sessione=self.s, legacy_anagrafica_id=B)
        for target, kw in (("anagrafica.views._helpers._build_nomi_map", {"return_value": NOMI}),
                           ("anagrafica.services.training_eligibility._cessati_ids", {"return_value": set()})):
            p = mock.patch(target, **kw)
            self.mock_cessati = p.start()
            self.addCleanup(p.stop)


# ── A) Stato non modificabile a mano ────────────────────────────────────────

class StatoNonAManoTests(_Base):
    def test_form_senza_stato(self):
        self.assertNotIn("stato", TrainingSessionForm().fields)

    def test_modifica_non_cambia_lo_stato(self):
        self.client.post(reverse("anagrafica:formazione_sessione_edit", args=[self.s.pk]), {
            "corso": self.corso.pk, "stato": "COMPLETATA", "modalita": "IN_SEDE",
            "data_inizio": IERI.isoformat(), "data_fine": IERI.isoformat()})
        self.s.refresh_from_db()
        self.assertEqual(self.s.stato, "IN_CORSO")

    def test_creazione_nasce_pianificata(self):
        dom = OGGI + timedelta(days=10)
        self.client.post(reverse("anagrafica:formazione_sessione_create"), {
            "corso": self.corso.pk, "stato": "COMPLETATA", "modalita": "IN_SEDE",
            "data_inizio": dom.isoformat(), "data_fine": dom.isoformat()})
        nuova = TrainingSession.objects.exclude(pk=self.s.pk).get()
        self.assertEqual(nuova.stato, "PIANIFICATA")


# ── B) Edizioni annullate ───────────────────────────────────────────────────

class AnnullataTests(_Base):
    def test_annulla_ritira_le_iscrizioni_aperte(self):
        n = aula.annulla(self.s)
        self.assertEqual(n, 2)
        self.ea.refresh_from_db()
        self.assertEqual(self.ea.stato, "RITIRATO")
        self.assertIn("edizione annullata", self.ea.note)
        self.s.refresh_from_db()
        self.assertEqual(self.s.stato, "ANNULLATA")

    def test_annulla_rifiuta_verifica_superata(self):
        TrainingEnrollment.objects.filter(pk=self.ea.pk).update(verifica_superata=True)
        with self.assertRaisesMessage(aula.AulaError, "superato la verifica"):
            aula.annulla(self.s)

    def test_stato_persona_ignora_edizioni_annullate(self):
        self.assertEqual(stati_persona_corso(self.corso, [A])[A].codice, IN_CORSO)
        TrainingSession.objects.filter(pk=self.s.pk).update(stato="ANNULLATA")
        self.assertNotEqual(stati_persona_corso(self.corso, [A])[A].codice, IN_CORSO)

    def test_chiudi_fase_blocco_e_riapri(self):
        aula.annulla(self.s)
        self.s.refresh_from_db()
        with self.assertRaises(aula.AulaError):
            aula.chiudi(self.s, self.admin, {})
        self.assertEqual(aula.fase(self.s), "annullata")
        self.assertIn("annullata", fi.motivo_blocco_edizione(self.s))
        r = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[self.s.pk]))
        self.assertContains(r, "Edizione annullata")
        self.assertNotContains(r, "La sessione è finita: chiudila")
        fi.riapri_edizione(self.s, self.admin, "annullata per errore")
        self.ea.refresh_from_db()
        self.assertEqual((self.s.stato, self.ea.stato), ("IN_CORSO", "ISCRITTO"))
        self.assertNotIn("edizione annullata", self.ea.note)

    def test_pulsanti_in_blocco_chiedono_conferma(self):
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list") + "?da_chiudere=1")
        self.assertContains(r, 'data-hub-confirm="Chiudere le edizioni selezionate?')
        self.assertContains(r, 'data-hub-confirm="Annullare le edizioni selezionate?')


# ── C/D) Lezione online su edizioni chiuse, sessioni miste ─────────────────

class LezioneOnlineTests(_Base):
    def setUp(self):
        super().setUp()
        self.so = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-R2-ON", modalita="ONLINE",
                                                 data_inizio=IERI, data_fine=OGGI, stato="IN_CORSO")
        self.eo = TrainingEnrollment.objects.create(sessione=self.so, legacy_anagrafica_id=C)
        self.cfg = so.config(self.so, crea=True)
        self.cfg.pubblicata_il = timezone.now()
        self.cfg.save()

    def test_accesso_negato_su_edizione_chiusa_o_esito_finale(self):
        self.assertEqual(so.motivo_accesso_negato(self.so, self.cfg, self.eo, anteprima=False), "")
        self.so.stato = "COMPLETATA"
        self.assertIn("chiusa", so.motivo_accesso_negato(self.so, self.cfg, self.eo, anteprima=False))
        self.so.stato = "IN_CORSO"
        self.eo.stato = "ASSENTE"
        self.assertIn("esito", so.motivo_accesso_negato(self.so, self.cfg, self.eo, anteprima=False))

    def test_lezioni_della_persona_e_allineamento_senza_edizioni_chiuse(self):
        self.assertEqual(len(so.lezioni_della_persona(C)), 1)
        self.assertEqual(list(so.iscrizioni_da_allineare(self.corso.pk, C)), [self.eo])
        TrainingSession.objects.filter(pk=self.so.pk).update(stato="COMPLETATA")
        self.assertEqual(so.lezioni_della_persona(C), [])
        self.assertEqual(list(so.iscrizioni_da_allineare(self.corso.pk, C)), [])

    def test_allineamento_solo_online(self):
        mista = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-R2-MX", modalita="MISTO",
                                               data_inizio=IERI, data_fine=OGGI, stato="IN_CORSO")
        TrainingEnrollment.objects.create(sessione=mista, legacy_anagrafica_id=C)
        self.assertEqual([e.sessione_id for e in so.iscrizioni_da_allineare(self.corso.pk, C)], [self.so.pk])

    def test_mista_senza_giornate_e_solo_verifica(self):
        mista = TrainingSession(corso=self.corso, modalita="MISTO")
        self.assertTrue(so.solo_verifica(mista))
        self.assertFalse(so.solo_verifica(self.so))

    def test_chiudi_sospende_la_lezione_online(self):
        TrainingEnrollment.objects.filter(pk=self.eo.pk).update(stato="ASSENTE")
        out = aula.chiudi(self.so, self.admin, {})
        self.assertTrue(out.chiusa)
        self.cfg.refresh_from_db()
        self.assertIsNone(self.cfg.pubblicata_il)


# ── E) Presenze e turni ─────────────────────────────────────────────────────

class TurniTests(_Base):
    def test_percentuale_sulle_sole_giornate_del_turno(self):
        from .services.training_turni import set_turni
        from .views import _helpers
        from .views.formazione import _ricalcola_presenza_enrollment

        l1 = TrainingLesson.objects.create(sessione=self.s, numero=1, data=IERI, ora_inizio=time(8), ora_fine=time(10))
        l2 = TrainingLesson.objects.create(sessione=self.s, numero=2, data=IERI, ora_inizio=time(14), ora_fine=time(16))
        set_turni(self.eb, [l2.pk])
        TrainingLessonAttendance.objects.create(lezione=l2, legacy_anagrafica_id=B, enrollment=self.eb,
                                                stato_presenza="PRESENTE")
        TrainingLessonAttendance.objects.create(lezione=l1, legacy_anagrafica_id=A, enrollment=self.ea,
                                                stato_presenza="PRESENTE")
        self.assertEqual(_helpers._calcola_percentuale_presenza(self.eb), 100.0)
        self.assertEqual(_helpers._calcola_percentuale_presenza(self.ea), 50.0)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as q1:
            _ricalcola_presenza_enrollment(self.ea)
        for n in range(3, 7):  # più giornate: le query restano le stesse
            lz = TrainingLesson.objects.create(sessione=self.s, numero=n, data=IERI, ora_inizio=time(17),
                                               ora_fine=time(18))
            TrainingLessonAttendance.objects.create(lezione=lz, legacy_anagrafica_id=A, enrollment=self.ea,
                                                    stato_presenza="PRESENTE")
        with CaptureQueriesContext(connection) as q2:
            _ricalcola_presenza_enrollment(self.ea)
        self.assertEqual(len(q1), len(q2))
        _ricalcola_presenza_enrollment(self.eb)
        self.eb.refresh_from_db()
        self.assertEqual((float(self.eb.ore_frequentate), float(self.eb.percentuale_presenza)), (2.0, 100.0))

    def test_tutti_presenti_query_costanti(self):
        lz = TrainingLesson.objects.create(sessione=self.s, numero=1, data=IERI, ora_inizio=time(8), ora_fine=time(10))
        self.assertEqual(aula.tutti_presenti(lz, self.admin), 2)
        self.ea.refresh_from_db()
        self.assertEqual(float(self.ea.percentuale_presenza), 100.0)


# ── F) Proposta di chiusura ────────────────────────────────────────────────

class PropostaTests(_Base):
    def test_cessati_e_gia_completati_proposti_ritirati(self):
        self.mock_cessati.return_value = {B}
        altra = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-R2-0", modalita="IN_SEDE",
                                               data_inizio=IERI - timedelta(days=30), data_fine=IERI - timedelta(days=30),
                                               stato="COMPLETATA")
        TrainingEmployeeRecord.objects.create(corso=self.corso, sessione=altra, legacy_anagrafica_id=A,
                                              data_completamento=IERI - timedelta(days=30), idoneo=True)
        righe = {r.enrollment.legacy_anagrafica_id: r for r in aula.proposta(self.s)}
        self.assertEqual((righe[B].proposto, righe[B].motivo), ("RITIRATO", "non più in forza"))
        self.assertEqual(righe[A].proposto, "RITIRATO")
        self.assertIn("già completato il", righe[A].motivo)
        self.assertIn("(altra strada)", righe[A].motivo)
        aula.chiudi_con_proposta(self.s, self.admin)
        self.assertEqual(TrainingEmployeeRecord.objects.filter(sessione=self.s).count(), 0)

    def test_cessati_fuori_dagli_esiti_aperti(self):
        self.mock_cessati.return_value = {B}
        self.assertEqual(aula.cosa_manca_breve(self.s), ("esito di 1 persona", "warn"))

    def test_efficacia_senza_cessati_e_annullati(self):
        from .services.formazione_efficacia import valutazioni_da_fare
        rec = TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=B,
                                                    data_completamento=IERI, idoneo=True)
        TrainingEfficacia.objects.filter(record=rec).delete()
        TrainingEfficacia.objects.create(record=rec, legacy_anagrafica_id=B, attesa_dal=IERI)
        self.assertEqual(valutazioni_da_fare().count(), 1)
        self.mock_cessati.return_value = {B}
        self.assertEqual(valutazioni_da_fare().count(), 0)


# ── G) Annullare un completamento ──────────────────────────────────────────

class AnnullaRecordTests(_Base):
    def test_annulla_riapre_edizione_e_rimette_in_corso(self):
        self.ea.stato, self.ea.data_completamento = "COMPLETATO", IERI
        self.ea.save()
        TrainingSession.objects.filter(pk=self.s.pk).update(stato="COMPLETATA")
        rec = TrainingEmployeeRecord.objects.create(corso=self.corso, sessione=self.s, enrollment=self.ea,
                                                    legacy_anagrafica_id=A, data_completamento=IERI, idoneo=True)
        TrainingEfficacia.objects.filter(record=rec).delete()
        TrainingEfficacia.objects.create(record=rec, legacy_anagrafica_id=A, attesa_dal=OGGI)
        ass = TrainingAssignment.objects.create(corso=self.corso, legacy_anagrafica_id=A, stato="COMPLETATO")
        el = TrainingElearningEnrollment.objects.create(corso=self.corso, legacy_anagrafica_id=A, stato="COMPLETATO",
                                                        data_completamento=IERI, record_completamento=rec)
        out = fi.annulla_record(TrainingEmployeeRecord.objects.get(pk=rec.pk), self.admin, "errore di persona")
        self.s.refresh_from_db()
        ass.refresh_from_db()
        el.refresh_from_db()
        self.assertEqual(self.s.stato, "IN_CORSO")
        self.assertEqual(out["edizione_riaperta"], "S-R2-1")
        self.assertFalse(TrainingEfficacia.objects.filter(record=rec).exists())
        self.assertEqual(ass.stato, "ASSEGNATO")
        self.assertEqual((el.stato, el.record_completamento_id), ("IN_CORSO", None))


# ── H/I) Stato effettivo, conteggi, QR, verifiche NC, promemoria ───────────

class StatoEConteggiTests(_Base):
    def test_stato_effettivo(self):
        s = TrainingSession(stato="PIANIFICATA", data_inizio=IERI)
        self.assertEqual((s.stato_effettivo, s.stato_effettivo_display), ("IN_CORSO", "In corso"))
        s.data_inizio = OGGI + timedelta(days=3)
        self.assertEqual(s.stato_effettivo, "PIANIFICATA")

    def test_iscritti_senza_ritirati(self):
        TrainingEnrollment.objects.filter(pk=self.eb.pk).update(stato="RITIRATO")
        r = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[self.s.pk]))
        self.assertEqual(r.context["n_iscritti"], 1)
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list"))
        self.assertEqual([s.n_iscritti_tot for s in r.context["page_obj"]], [1])

    def test_qr_non_vale_su_edizione_chiusa(self):
        tok = aula.token(self.s)
        self.assertIsNotNone(aula.sessione_da_token(tok))
        TrainingSession.objects.filter(pk=self.s.pk).update(stato="COMPLETATA")
        self.assertIsNone(aula.sessione_da_token(tok))
        TrainingSession.objects.filter(pk=self.s.pk).update(stato="IN_CORSO", approvata_il=timezone.now())
        self.assertIsNone(aula.sessione_da_token(tok))

    def test_verifiche_nc_una_regola(self):
        vecchia = OGGI - timedelta(days=400)
        TrainingSession.objects.filter(pk=self.s.pk).update(stato="COMPLETATA", approvata_il=timezone.now(),
                                                            data_inizio=vecchia, data_fine=vecchia)
        self.assertEqual([s.pk for s in aula.verifiche_nc_dovute()], [self.s.pk])
        n = {c.codice: c.n for c in fi.controlli_integrita()}["verifiche_nc_dovute"]
        self.assertEqual(n, 1)

    def test_promemoria_testo_e_link(self):
        from .management.commands.send_formazione_session_reminders import testo_e_link
        testo, link = testo_e_link(self.s, "01-01-2027")
        self.assertNotIn("/iscritti/", link)
        on = TrainingSession.objects.create(corso=self.corso, codice_sessione="S-R2-P", modalita="ONLINE",
                                            data_inizio=OGGI + timedelta(days=1), data_fine=OGGI + timedelta(days=8))
        testo, link = testo_e_link(on, "x")
        self.assertIn("disponibile dal", testo)
        self.assertIn("entro il", testo)
        self.assertEqual(link, reverse("anagrafica:sessione_online_player", args=[on.pk]))

    def test_comando_promemoria_gira(self):
        call_command("send_formazione_session_reminders", "--dry-run", stdout=StringIO())


# ── J) Edizione collegata delle sessioni competenze ────────────────────────

class EdizioneCollegataTests(_Base):
    def test_completato_senza_libretto_non_e_completamento(self):
        from .services import sessioni as svc
        TrainingEnrollment.objects.filter(pk=self.ea.pk).update(stato="COMPLETATO", idoneo=True)
        self.assertIsNone(svc._iscrizione_completata(A, self.corso.pk))
        rec = TrainingEmployeeRecord.objects.create(corso=self.corso, sessione=self.s, enrollment=self.ea,
                                                    legacy_anagrafica_id=A, data_completamento=IERI, idoneo=True)
        self.assertEqual(svc._iscrizione_completata(A, self.corso.pk), self.ea)
        TrainingEmployeeRecord.objects.filter(pk=rec.pk).update(data_scadenza=IERI - timedelta(days=1))
        self.assertIsNone(svc._iscrizione_completata(A, self.corso.pk))
