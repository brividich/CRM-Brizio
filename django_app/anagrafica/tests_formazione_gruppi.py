"""Formazione HR — gruppi logistici (edizione), divisione iscritti, denominatore corretto.

Copre il caso reale che ha motivato la feature: un corso con 4 lezioni da 8 ore e
10 iscritti che, per motivi logistici (l'aula non li contiene tutti), va diviso
in 2 gruppi da 5 — ciascuno con il proprio calendario. Ogni gruppo È una
`TrainingSession` (nessuna nuova entità nel modello dati); `edizione` è
l'etichetta opzionale che li tiene collegati.

Il pezzo critico: prima di questa feature, mettere due gruppi nella stessa
sessione (via i "turni" `TrainingEnrollmentLesson`) rompeva il calcolo della
percentuale di presenza — il denominatore contava TUTTE le lezioni della sessione,
non solo quelle del proprio gruppo, penalizzando chi frequenta regolarmente il suo
gruppo. Con "gruppo = sessione", il denominatore è scoped per costruzione: i test
`PercentualePresenzaPerGruppoTests` lo dimostrano end-to-end.

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi tutto
ai non-superuser (vedi memoria assets_test_legacy_auth_disabled).
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_formazione import (
    TrainingCourse,
    TrainingEnrollment,
    TrainingEnrollmentLesson,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingSession,
)
from .services.formazione_pianificazione import dividi_in_gruppi, genera_lezioni

User = get_user_model()


def _piano(codice="GRP") -> TrainingPlan:
    return TrainingPlan.objects.create(codice=codice, nome=f"Piano {codice}")


def _corso(piano=None, codice="GRP-1", durata="32.00") -> TrainingCourse:
    return TrainingCourse.objects.create(
        piano=piano or _piano(),
        codice=codice,
        titolo=f"Corso {codice}",
        durata_ore_teorica=Decimal(durata),
        validita_mesi=60,
        stato="ATTIVO",
    )


def _sessione_con_lezioni(corso, n_lezioni=4, n_iscritti=10) -> TrainingSession:
    """Sessione con `n_lezioni` giornate da 8h e `n_iscritti` iscritti — il
    corso "10 iscritti, 4 lezioni" prima di essere diviso in gruppi."""
    sess = TrainingSession.objects.create(
        corso=corso, codice_sessione=f"{corso.codice}-SRC",
        data_inizio=date(2026, 9, 1), data_fine=date(2026, 9, 4),
    )
    genera_lezioni(sess, time(8, 0), time(17, 0), pausa_minuti=60, salta_weekend=False)
    assert sess.lezioni.count() == n_lezioni
    for lid in range(1, n_iscritti + 1):
        TrainingEnrollment.objects.create(sessione=sess, legacy_anagrafica_id=100 + lid)
    return sess


class DividiInGruppiServiceTests(TestCase):
    def setUp(self):
        self.corso = _corso()
        self.sess = _sessione_con_lezioni(self.corso)

    def test_sorgente_diventa_primo_gruppo(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=2)
        self.assertEqual(len(gruppi), 2)
        self.assertEqual(gruppi[0].pk, self.sess.pk)

    def test_ogni_gruppo_ha_il_programma_clonato(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=2)
        secondo = gruppi[1]
        self.assertEqual(secondo.lezioni.count(), 4)
        self.assertEqual(secondo.ore_pianificate, 32.0)
        # Stesso orario/pausa/argomento della sorgente
        lz_src = self.sess.lezioni.order_by("numero").first()
        lz_new = secondo.lezioni.order_by("numero").first()
        self.assertEqual(lz_new.ora_inizio, lz_src.ora_inizio)
        self.assertEqual(lz_new.pausa_minuti, lz_src.pausa_minuti)
        self.assertEqual(lz_new.argomento, lz_src.argomento)

    def test_iscritti_divisi_5_e_5(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=2)
        self.assertEqual(TrainingEnrollment.objects.filter(sessione=gruppi[0]).count(), 5)
        self.assertEqual(TrainingEnrollment.objects.filter(sessione=gruppi[1]).count(), 5)
        # Nessuno duplicato o perso
        totale = TrainingEnrollment.objects.filter(sessione__in=gruppi).count()
        self.assertEqual(totale, 10)

    def test_tre_gruppi_round_robin(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=3)
        conteggi = sorted(TrainingEnrollment.objects.filter(sessione=g).count() for g in gruppi)
        self.assertEqual(conteggi, [3, 3, 4])

    def test_edizione_condivisa_e_autogenerata_se_vuota(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=2)
        self.assertTrue(gruppi[0].edizione)
        self.assertEqual(gruppi[0].edizione, gruppi[1].edizione)

    def test_edizione_esplicita_rispettata(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=2, edizione="2026 - 1 sem")
        self.assertEqual(gruppi[0].edizione, "2026 - 1 sem")
        self.assertEqual(gruppi[1].edizione, "2026 - 1 sem")

    def test_codici_sessione_univoci(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=3)
        codici = [g.codice_sessione for g in gruppi]
        self.assertEqual(len(codici), len(set(codici)))

    def test_sfasamento_giorni_sposta_date_e_lezioni(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=2, giorni_tra_gruppi=14)
        secondo = gruppi[1]
        self.assertEqual(secondo.data_inizio, date(2026, 9, 15))
        lz_src = self.sess.lezioni.order_by("numero").first()
        lz_new = secondo.lezioni.order_by("numero").first()
        self.assertEqual((lz_new.data - lz_src.data).days, 14)

    def test_sessioni_gemelle_si_vedono_a_vicenda(self):
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=3)
        gemelle_di_1 = set(gruppi[0].sessioni_gemelle().values_list("pk", flat=True))
        self.assertEqual(gemelle_di_1, {gruppi[1].pk, gruppi[2].pk})

    def test_blocca_se_gia_presenti_presenze(self):
        lz = self.sess.lezioni.first()
        TrainingLessonAttendance.objects.create(
            lezione=lz, legacy_anagrafica_id=101, stato_presenza="PRESENTE",
        )
        with self.assertRaises(ValueError):
            dividi_in_gruppi(self.sess, n_gruppi=2)
        # Nessuna sessione gemella creata dal tentativo fallito
        self.assertEqual(TrainingSession.objects.filter(corso=self.corso).count(), 1)

    def test_meno_di_due_gruppi_rifiutato(self):
        with self.assertRaises(ValueError):
            dividi_in_gruppi(self.sess, n_gruppi=1)

    def test_turni_preesistenti_rimossi_su_chi_si_sposta(self):
        """Un turno riferito a una lezione della sorgente non ha senso sul nuovo
        gruppo (invariante lezione.sessione_id == enrollment.sessione_id).
        Round-robin su 10 iscritti (101..110) e 2 gruppi: id pari finiscono nel
        bucket 1 (si spostano), id dispari nel bucket 0 (restano sulla sorgente)."""
        iscr = TrainingEnrollment.objects.get(sessione=self.sess, legacy_anagrafica_id=102)
        lz = self.sess.lezioni.first()
        TrainingEnrollmentLesson.objects.create(enrollment=iscr, lezione=lz)
        gruppi = dividi_in_gruppi(self.sess, n_gruppi=2)
        iscr.refresh_from_db()
        self.assertEqual(iscr.sessione_id, gruppi[1].pk)
        self.assertFalse(TrainingEnrollmentLesson.objects.filter(enrollment=iscr).exists())


class PercentualePresenzaPerGruppoTests(TestCase):
    """Il denominatore della percentuale di presenza deve essere le ore del
    PROPRIO gruppo, non quelle di tutta l'edizione. Con gruppo=sessione questo è
    vero per costruzione: qui lo si verifica end-to-end sul caso reale."""

    def setUp(self):
        self.corso = _corso(codice="PCT-1")
        self.sess = _sessione_con_lezioni(self.corso, n_iscritti=10)
        self.gruppi = dividi_in_gruppi(self.sess, n_gruppi=2)

    def test_frequenza_piena_nel_proprio_gruppo_e_100_per_cento(self):
        from .views import _calcola_percentuale_presenza

        gruppo2 = self.gruppi[1]
        iscritto = TrainingEnrollment.objects.filter(sessione=gruppo2).first()
        for lz in gruppo2.lezioni.all():
            TrainingLessonAttendance.objects.create(
                lezione=lz, legacy_anagrafica_id=iscritto.legacy_anagrafica_id,
                stato_presenza="PRESENTE",
            )
        perc = _calcola_percentuale_presenza(iscritto)
        # Se il denominatore includesse anche le 4 lezioni del gruppo 1 (bug delle
        # sessioni condivise coi turni) risulterebbe 50%, non 100%.
        self.assertEqual(perc, 100.0)

    def test_denominatore_non_conta_le_lezioni_dell_altro_gruppo(self):
        from .views import _calcola_percentuale_presenza

        gruppo1, gruppo2 = self.gruppi
        self.assertEqual(gruppo1.lezioni.count(), 4)
        self.assertEqual(gruppo2.lezioni.count(), 4)
        iscritto_g1 = TrainingEnrollment.objects.filter(sessione=gruppo1).first()
        # Nessuna presenza registrata: percentuale 0%, non None (le lezioni del
        # proprio gruppo esistono e contano).
        self.assertEqual(_calcola_percentuale_presenza(iscritto_g1), 0.0)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DividiInGruppiViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-fdg", "su-fdg@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso(codice="VDG-1")
        self.sess = _sessione_con_lezioni(self.corso)

    def _url(self, sessione=None):
        return reverse("anagrafica:formazione_sessione_dividi_gruppi", args=[(sessione or self.sess).pk])

    def test_divide_e_reindirizza_al_gruppo_sorgente(self):
        resp = self.client.post(self._url(), {"n_gruppi": "2", "giorni_tra_gruppi": "0"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"/sessioni/{self.sess.pk}/", resp["Location"])
        self.assertEqual(TrainingSession.objects.filter(corso=self.corso).count(), 2)

    def test_dettaglio_sessione_mostra_edizione_e_gemelle(self):
        self.client.post(self._url(), {"n_gruppi": "2", "giorni_tra_gruppi": "0", "edizione": "Edizione test"})
        body = self.client.get(
            reverse("anagrafica:formazione_sessione_detail", args=[self.sess.pk])
        ).content.decode()
        self.assertIn("Edizione test", body)
        gruppo2 = TrainingSession.objects.filter(corso=self.corso).exclude(pk=self.sess.pk).get()
        self.assertIn(gruppo2.codice_sessione, body)

    def test_presenze_gia_registrate_bloccano_con_messaggio(self):
        lz = self.sess.lezioni.first()
        TrainingLessonAttendance.objects.create(
            lezione=lz, legacy_anagrafica_id=101, stato_presenza="PRESENTE",
        )
        resp = self.client.post(self._url(), {"n_gruppi": "2"}, follow=True)
        self.assertEqual(TrainingSession.objects.filter(corso=self.corso).count(), 1)
        self.assertContains(resp, "presenze registrate")

    def test_form_non_valido_non_crea_nulla(self):
        self.client.post(self._url(), {"n_gruppi": "1"})  # sotto il minimo
        self.assertEqual(TrainingSession.objects.filter(corso=self.corso).count(), 1)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class WizardCorsoConGruppiTests(TestCase):
    """Il wizard «nuovo corso» può creare direttamente N gruppi paralleli."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-fwg", "su-fwg@test.local", "x")
        self.client.force_login(self.su)
        self.piano = _piano("WGR")

    def test_n_gruppi_maggiore_di_uno_crea_piu_sessioni(self):
        resp = self.client.post(reverse("anagrafica:formazione_corso_create"), {
            "piano": self.piano.pk, "codice": "WGR-01", "titolo": "Corso con gruppi",
            "durata_ore_teorica": "8", "validita_mesi": "60",
            "quiz_punteggio_minimo": "70", "stato": "ATTIVO", "versione": "1.0",
            "is_active": "on",
            "sess-pianifica": "on",
            "sess-data_inizio": "2026-09-10",
            "sess-ora_inizio": "08:00",
            "sess-ora_fine": "17:00",
            "sess-pausa_minuti": "60",
            "sess-modalita": "IN_SEDE",
            "sess-giorni_settimana": ["0", "1", "2", "3", "4"],
            "sess-n_gruppi": "3",
        })
        self.assertEqual(resp.status_code, 302)
        corso = TrainingCourse.objects.get(codice="WGR-01")
        self.assertEqual(corso.sessioni.count(), 3)
        for sess in corso.sessioni.all():
            self.assertEqual(sess.lezioni.count(), 1)
            self.assertTrue(sess.edizione)

    def test_n_gruppi_default_crea_una_sola_sessione(self):
        resp = self.client.post(reverse("anagrafica:formazione_corso_create"), {
            "piano": self.piano.pk, "codice": "WGR-02", "titolo": "Corso singolo",
            "durata_ore_teorica": "8", "validita_mesi": "60",
            "quiz_punteggio_minimo": "70", "stato": "ATTIVO", "versione": "1.0",
            "is_active": "on",
            "sess-pianifica": "on",
            "sess-data_inizio": "2026-09-10",
            "sess-ora_inizio": "08:00",
            "sess-ora_fine": "17:00",
            "sess-pausa_minuti": "60",
            "sess-modalita": "IN_SEDE",
            "sess-giorni_settimana": ["0", "1", "2", "3", "4"],
        })
        self.assertEqual(resp.status_code, 302)
        corso = TrainingCourse.objects.get(codice="WGR-02")
        self.assertEqual(corso.sessioni.count(), 1)
        self.assertEqual(corso.sessioni.get().edizione, "")
