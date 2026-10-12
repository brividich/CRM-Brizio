"""Integrità dati della formazione d'aula: edizione chiusa, approvazione MOD.040,
riapertura e annullamento motivati, controlli di integrità (MT CN 06 §9, MT CN 08 §7.3)."""
from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog

from .forms import TrainingEnrollmentEditForm, TrainingLessonAttendanceForm
from .models_formazione import (
    TrainingCourse,
    TrainingEmployeeRecord,
    TrainingEnrollment,
    TrainingExportLog,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingSession,
)
from .services import formazione_integrita as fi

User = get_user_model()
MODULO = "anagrafica.formazione"
OGGI = timezone.localdate()
IERI = OGGI - timedelta(days=1)


def _corso(codice="INT-01", **extra) -> TrainingCourse:
    piano, _ = TrainingPlan.objects.get_or_create(codice="INT", defaults={"nome": "Piano INT"})
    campi = {"piano": piano, "codice": codice, "titolo": f"Corso {codice}",
             "durata_ore_teorica": Decimal("8.00"), "stato": "ATTIVO"}
    campi.update(extra)
    return TrainingCourse.objects.create(**campi)


def _edizione(corso, codice="INT-01-E1", *, stato="IN_CORSO", giorno=IERI, docente_nome="Mario Docente"):
    sess = TrainingSession.objects.create(
        corso=corso, codice_sessione=codice, stato=stato,
        data_inizio=giorno, data_fine=giorno, docente_nome=docente_nome,
    )
    lez = TrainingLesson.objects.create(
        sessione=sess, numero=1, data=giorno, ora_inizio=time(8, 0), ora_fine=time(12, 0),
        argomento="Rischi generali",
    )
    return sess, lez


def _record(enr, **extra):
    campi = {"corso": enr.sessione.corso, "sessione": enr.sessione, "enrollment": enr,
             "legacy_anagrafica_id": enr.legacy_anagrafica_id, "data_completamento": IERI}
    campi.update(extra)
    return TrainingEmployeeRecord.objects.create(**campi)


class _Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser("form_int", "f@i.t", "pwd12345")
        self.client.force_login(self.user)
        self.corso = _corso()
        self.sess, self.lez = _edizione(self.corso)
        self.enr = TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=501)

    def _voci(self, azione):
        return AuditLog.objects.filter(modulo=MODULO, azione=azione)


@override_settings(LEGACY_AUTH_ENABLED=False)
class IscrizioneDeleteTests(_Base):
    def test_get_non_elimina(self):
        r = self.client.get(reverse("anagrafica:formazione_iscrizione_delete", args=[self.sess.pk, self.enr.pk]))
        self.assertEqual(r.status_code, 405)
        self.assertTrue(TrainingEnrollment.objects.filter(pk=self.enr.pk).exists())

    def test_con_completamento_a_libretto_non_si_elimina(self):
        _record(self.enr)
        self.client.post(reverse("anagrafica:formazione_iscrizione_delete", args=[self.sess.pk, self.enr.pk]))
        self.assertTrue(TrainingEnrollment.objects.filter(pk=self.enr.pk).exists())

    def test_eliminazione_tracciata(self):
        self.client.post(reverse("anagrafica:formazione_iscrizione_delete", args=[self.sess.pk, self.enr.pk]))
        self.assertFalse(TrainingEnrollment.objects.filter(pk=self.enr.pk).exists())
        self.assertTrue(self._voci("iscrizione_eliminata").exists())


@override_settings(LEGACY_AUTH_ENABLED=False)
class EdizioneChiusaTests(_Base):
    def _chiudi(self):
        self.sess.stato = "COMPLETATA"
        self.sess.save()

    def test_completata_blocca_calendario_iscritti_presenze(self):
        self._chiudi()
        self.client.post(reverse("anagrafica:formazione_lezione_delete", args=[self.sess.pk, self.lez.pk]))
        self.assertTrue(TrainingLesson.objects.filter(pk=self.lez.pk).exists())
        self.client.post(reverse("anagrafica:formazione_iscrizione_add", args=[self.sess.pk]),
                         {"legacy_anagrafica_id": "777"})
        self.assertFalse(TrainingEnrollment.objects.filter(legacy_anagrafica_id=777).exists())
        self.client.post(reverse("anagrafica:formazione_presenza_set", args=[self.sess.pk, self.lez.pk]),
                         {"legacy_anagrafica_id": "501", "stato_presenza": "PRESENTE"})
        self.assertFalse(TrainingLessonAttendance.objects.exists())
        self.client.post(reverse("anagrafica:formazione_sessione_edit", args=[self.sess.pk]),
                         {"corso": self.corso.pk, "codice_sessione": "X", "stato": "PIANIFICATA",
                          "modalita": "IN_SEDE", "data_inizio": IERI.isoformat()})
        self.sess.refresh_from_db()
        self.assertEqual(self.sess.stato, "COMPLETATA")

    def test_completata_lascia_chiudere_gli_esiti(self):
        self._chiudi()
        self.client.post(reverse("anagrafica:formazione_iscrizione_edit", args=[self.sess.pk, self.enr.pk]),
                         {"stato": "ASSENTE"})
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.stato, "ASSENTE")

    def test_approvata_blocca_anche_gli_esiti(self):
        self._chiudi()
        self.sess.approvata_il = timezone.now()
        self.sess.save()
        self.client.post(reverse("anagrafica:formazione_iscrizione_edit", args=[self.sess.pk, self.enr.pk]),
                         {"stato": "ASSENTE"})
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.stato, "ISCRITTO")

    def test_firme_da_scansione_rifiutate(self):
        from .services.formazione_presenze import applica_firme_lezione

        self._chiudi()
        with self.assertRaises(fi.EdizioneChiusa):
            applica_firme_lezione(self.lez, {501: (True, True)})


@override_settings(LEGACY_AUTH_ENABLED=False)
class PresenzeTests(_Base):
    def _post(self, lezione, dati):
        return self.client.post(reverse("anagrafica:formazione_presenza_set", args=[self.sess.pk, lezione.pk]), dati)

    def test_non_iscritto_rifiutato(self):
        self._post(self.lez, {"legacy_anagrafica_id": "999", "stato_presenza": "PRESENTE"})
        self.assertFalse(TrainingLessonAttendance.objects.exists())

    def test_giornata_futura_rifiutata(self):
        domani = OGGI + timedelta(days=1)
        self.sess.data_fine = domani
        self.sess.save()
        futura = TrainingLesson.objects.create(sessione=self.sess, numero=2, data=domani,
                                               ora_inizio=time(8, 0), ora_fine=time(12, 0), argomento="x")
        self._post(futura, {"legacy_anagrafica_id": "501", "stato_presenza": "PRESENTE"})
        self.assertFalse(TrainingLessonAttendance.objects.filter(lezione=futura).exists())

    def test_ore_oltre_la_durata_non_valide(self):
        p = TrainingLessonAttendance(lezione=self.lez, legacy_anagrafica_id=501)
        form = TrainingLessonAttendanceForm({"stato_presenza": "PRESENTE", "ore_effettive": "5"}, instance=p)
        self.assertFalse(form.is_valid())
        self.assertIn("ore_effettive", form.errors)

    def test_assenza_senza_ore(self):
        p = TrainingLessonAttendance(lezione=self.lez, legacy_anagrafica_id=501)
        form = TrainingLessonAttendanceForm({"stato_presenza": "ASSENTE_GIUST", "ore_effettive": "3"}, instance=p)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["ore_effettive"])


class IscrizioneFormTests(_Base):
    def test_ore_e_percentuale_calcolate_con_calendario(self):
        form = TrainingEnrollmentEditForm(instance=self.enr)
        self.assertTrue(form.fields["percentuale_presenza"].disabled)
        self.assertTrue(form.fields["ore_frequentate"].disabled)

    def test_soglia_proposta_e_quella_della_verifica(self):
        self.corso.quiz_punteggio_minimo = 65
        self.corso.save()
        form = TrainingEnrollmentEditForm(instance=self.enr)
        self.assertEqual(form.fields["punteggio_minimo"].initial, 65)

    def test_date_future_o_prima_dell_edizione(self):
        form = TrainingEnrollmentEditForm({"stato": "COMPLETATO",
                                           "data_completamento": (OGGI + timedelta(days=3)).isoformat()},
                                          instance=self.enr)
        self.assertIn("data_completamento", form.errors)
        form = TrainingEnrollmentEditForm({"stato": "COMPLETATO",
                                           "data_verifica": (IERI - timedelta(days=30)).isoformat()},
                                          instance=self.enr)
        self.assertIn("data_verifica", form.errors)

    def test_percentuale_oltre_100_senza_calendario(self):
        sess = TrainingSession.objects.create(corso=self.corso, codice_sessione="EXT-1",
                                              data_inizio=IERI, data_fine=IERI)
        enr = TrainingEnrollment.objects.create(sessione=sess, legacy_anagrafica_id=502)
        form = TrainingEnrollmentEditForm({"stato": "IN_CORSO", "percentuale_presenza": "150",
                                           "ore_frequentate": "2"}, instance=enr)
        self.assertIn("percentuale_presenza", form.errors)


@override_settings(LEGACY_AUTH_ENABLED=False)
class AnnullamentoTests(_Base):
    def test_ritorno_da_completato_bloccato_se_a_libretto(self):
        self.enr.stato = "COMPLETATO"
        self.enr.save()
        _record(self.enr)
        self.client.post(reverse("anagrafica:formazione_iscrizione_edit", args=[self.sess.pk, self.enr.pk]),
                         {"stato": "IN_CORSO"})
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.stato, "COMPLETATO")

    def test_annullamento_motivato(self):
        self.enr.stato = "COMPLETATO"
        self.enr.save()
        rec = _record(self.enr)
        url = reverse("anagrafica:formazione_record_annulla", args=[rec.pk])
        self.client.post(url, {"motivo": ""})
        self.assertTrue(TrainingEmployeeRecord.objects.filter(pk=rec.pk).exists(), "senza motivo non si annulla")

        self.client.post(url, {"motivo": "Persona sbagliata"})
        self.assertFalse(TrainingEmployeeRecord.objects.filter(pk=rec.pk).exists())
        rec = TrainingEmployeeRecord.tutti.get(pk=rec.pk)
        self.assertEqual(rec.annullato_motivo, "Persona sbagliata")
        self.assertIsNone(rec.enrollment_id)
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.stato, "IN_CORSO")
        self.assertTrue(self._voci("completamento_annullato").exists())

    def test_attestato_annullato_risulta_tale(self):
        from .services import attestato_verifica as av

        rec = _record(self.enr)
        codice = av.assegna_codice_verifica(rec)
        rec.refresh_from_db()
        fi.annulla_record(rec, self.user, "Errore di registrazione")
        self.assertEqual(av.verifica(codice).stato, av.ANNULLATO)

    def test_annullamento_bloccato_su_edizione_approvata(self):
        rec = _record(self.enr)
        self.sess.stato = "COMPLETATA"
        self.sess.approvata_il = timezone.now()
        self.sess.save()
        with self.assertRaises(fi.EdizioneChiusa):
            fi.annulla_record(rec, self.user, "x")


@override_settings(LEGACY_AUTH_ENABLED=False)
class ApprovazioneTests(_Base):
    def test_requisiti_mancanti(self):
        sess = TrainingSession.objects.create(corso=self.corso, codice_sessione="VUOTA", stato="IN_CORSO",
                                              data_inizio=IERI, data_fine=IERI)
        mancanti = fi.requisiti_approvazione(sess).mancanti
        self.assertTrue(any("Completata" in m for m in mancanti))
        self.assertTrue(any("partecipante" in m for m in mancanti))
        self.assertTrue(any("docente" in m for m in mancanti))
        self.assertTrue(any("argomento" in m for m in mancanti))

    def test_approvazione_valida_i_completamenti(self):
        self.enr.stato = "COMPLETATO"
        self.enr.save()
        rec = _record(self.enr)
        self.sess.stato = "COMPLETATA"
        self.sess.save()
        self.client.post(reverse("anagrafica:formazione_sessione_approva", args=[self.sess.pk]), {"note": "ok"})
        self.sess.refresh_from_db()
        rec.refresh_from_db()
        self.assertTrue(self.sess.is_approvata)
        self.assertEqual(self.sess.approvata_da, self.user)
        self.assertEqual(rec.validato_da, self.user)
        self.assertTrue(self._voci("edizione_approvata").exists())

    def test_approvazione_rifiutata_con_esiti_aperti(self):
        self.sess.stato = "COMPLETATA"
        self.sess.save()
        self.client.post(reverse("anagrafica:formazione_sessione_approva", args=[self.sess.pk]))
        self.sess.refresh_from_db()
        self.assertFalse(self.sess.is_approvata)

    def test_riapertura_motivata(self):
        self.sess.stato = "COMPLETATA"
        self.sess.approvata_il = timezone.now()
        self.sess.save()
        url = reverse("anagrafica:formazione_sessione_riapri", args=[self.sess.pk])
        self.client.post(url, {"motivo": ""})
        self.sess.refresh_from_db()
        self.assertTrue(self.sess.is_approvata)
        self.client.post(url, {"motivo": "Docente mancante"})
        self.sess.refresh_from_db()
        self.assertEqual(self.sess.stato, "IN_CORSO")
        self.assertFalse(self.sess.is_approvata)
        voce = self._voci("edizione_riaperta").first()
        self.assertEqual(voce.dettaglio.get("motivo"), "Docente mancante")

    def test_verifica_nc_no_richiede_note(self):
        self.sess.stato = "COMPLETATA"
        self.sess.approvata_il = timezone.now()
        self.sess.save()
        with self.assertRaises(ValueError):
            fi.registra_verifica_nc(self.sess, self.user, "NO", "")
        fi.registra_verifica_nc(self.sess, self.user, "SI")
        self.sess.refresh_from_db()
        self.assertEqual(self.sess.verifica_nc_esito, "SI")
        self.assertEqual(self.sess.verifica_nc_il, OGGI)

    def test_stampa_mod040(self):
        r = self.client.get(reverse("anagrafica:formazione_sessione_mod040", args=[self.sess.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(TrainingExportLog.objects.filter(tipo="MOD040").exists())

    def test_pannello_nel_dettaglio(self):
        r = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[self.sess.pk]))
        self.assertContains(r, "Chiusura e approvazione (MOD.040)")


class VincoliTests(TestCase):
    def setUp(self):
        self.corso = _corso("VIN-01")

    def test_date_edizione_invertite_rifiutate(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TrainingSession.objects.create(corso=self.corso, codice_sessione="INV",
                                           data_inizio=OGGI, data_fine=OGGI - timedelta(days=2))

    def test_doppioni_segnalati_non_bloccati(self):
        # I doppioni storici restano a pulisci_scadenze_hr: qui si segnalano soltanto.
        for _ in range(2):
            TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=1, data_completamento=IERI)
        conteggi = {c.codice: c.n for c in fi.controlli_integrita()}
        self.assertEqual(conteggi["record_doppi"], 1)

    def test_percentuale_fuori_limiti_rifiutata(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TrainingEmployeeRecord.objects.create(corso=self.corso, legacy_anagrafica_id=1, data_completamento=IERI,
                                                  percentuale_presenza=Decimal("120"))


@override_settings(LEGACY_AUTH_ENABLED=False)
class IntegritaTests(_Base):
    def test_controlli_e_correzioni_automatiche(self):
        TrainingLessonAttendance.objects.create(lezione=self.lez, legacy_anagrafica_id=501,
                                                stato_presenza="PRESENTE", ore_effettive=Decimal("9"))
        fuori = TrainingLesson.objects.create(sessione=self.sess, numero=2, data=IERI - timedelta(days=5),
                                              ora_inizio=time(8, 0), ora_fine=time(9, 0), argomento="x")
        conteggi = {c.codice: c.n for c in fi.controlli_integrita()}
        self.assertEqual(conteggi["presenze_oltre_durata"], 1)
        self.assertEqual(conteggi["lezioni_fuori_intervallo"], 1)

        self.client.post(reverse("anagrafica:formazione_integrita"), {"azione": "correggi"})
        conteggi = {c.codice: c.n for c in fi.controlli_integrita()}
        self.assertEqual(conteggi["presenze_oltre_durata"], 0)
        self.assertEqual(conteggi["lezioni_fuori_intervallo"], 0)
        self.sess.refresh_from_db()
        self.assertEqual(self.sess.data_inizio, fuori.data)
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.ore_frequentate, Decimal("4.00"))
        self.assertTrue(self._voci("integrita_correzioni_automatiche").exists())

    def test_piu_giornate_fuori_intervallo_stessa_edizione(self):
        prima = IERI - timedelta(days=4)
        dopo = IERI + timedelta(days=0)
        self.sess.data_inizio = self.sess.data_fine = IERI - timedelta(days=2)
        self.sess.save()
        TrainingLesson.objects.filter(pk=self.lez.pk).update(data=dopo)
        TrainingLesson.objects.create(sessione=self.sess, numero=2, data=prima,
                                      ora_inizio=time(8, 0), ora_fine=time(9, 0), argomento="x")
        fatti = fi.correggi()
        self.assertEqual(fatti["lezioni_fuori_intervallo"], 2)
        self.sess.refresh_from_db()
        self.assertEqual((self.sess.data_inizio, self.sess.data_fine), (prima, dopo))
        self.assertEqual({c.codice: c.n for c in fi.controlli_integrita()}["lezioni_fuori_intervallo"], 0)

    def test_pagine_integrita_e_guida(self):
        r = self.client.get(reverse("anagrafica:formazione_integrita"))
        self.assertContains(r, "Integrità dati")
        r = self.client.get(reverse("anagrafica:formazione_guida"))
        for ancora in ("ciclo", "chiusura", "verifica-nc", "correzioni", "annullare", "integrita"):
            self.assertContains(r, f'id="{ancora}"')

    def test_comando(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("verifica_integrita_formazione", "--json", stdout=out)
        self.assertIn("presenze_oltre_durata", out.getvalue())
