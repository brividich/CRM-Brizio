"""Formazione HR — robustezza della pianificazione lezioni.

Il calendario multi-data del wizard è un **miglioramento progressivo**: la
regola vive sul server, e questi test la esercitano come la esercita una POST
costruita a mano — date duplicate o disordinate, weekday fuori catalogo, date
non parsabili, elenchi spropositati. Coprono inoltre le due proprietà su cui si
regge la rigenerazione: è idempotente e **non cancella mai** ciò che è già stato
compilato (argomenti, presenze, firme).

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi
tutto ai non-superuser (vedi memoria assets_test_legacy_auth_disabled).
"""
from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import MAX_DATE_PUNTUALI, TrainingSessionForm
from .models_formazione import (
    TrainingCourse,
    TrainingEnrollment,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingSession,
)
from .services.formazione_pianificazione import (
    crea_sessione_unica,
    genera_lezioni,
    giorni_da_pianificare,
    giorni_pianificabili,
)

User = get_user_model()


def _corso(codice="PIA-01") -> TrainingCourse:
    return TrainingCourse.objects.create(
        piano=TrainingPlan.objects.create(codice=codice, nome=f"Piano {codice}"),
        codice=codice,
        titolo=f"Corso {codice}",
        durata_ore_teorica=Decimal("8.00"),
        validita_mesi=60,
        stato="ATTIVO",
    )


def _sessione(corso, inizio=date(2026, 9, 3), fine=date(2026, 9, 8)) -> TrainingSession:
    return TrainingSession.objects.create(
        corso=corso, codice_sessione=f"{corso.codice}-E1", data_inizio=inizio, data_fine=fine,
    )


# ---------------------------------------------------------------------------
# Date puntuali: normalizzate, ordinate, deduplicate, prioritarie
# ---------------------------------------------------------------------------

class DatePuntualiTests(TestCase):
    def setUp(self):
        self.corso = _corso("PIA-DP")
        self.sess = _sessione(self.corso)

    def test_duplicate_e_disordinate_producono_una_lezione_per_data(self):
        scelte = [date(2026, 9, 20), date(2026, 9, 6), date(2026, 9, 20), date(2026, 9, 13)]
        creati = genera_lezioni(self.sess, time(8, 0), time(17, 0), date_puntuali=scelte)

        self.assertEqual(
            [lz.data for lz in creati],
            [date(2026, 9, 6), date(2026, 9, 13), date(2026, 9, 20)],
        )
        self.assertEqual(self.sess.lezioni.count(), 3)

    def test_ordine_di_arrivo_irrilevante(self):
        altra = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="PIA-DP-E2",
            data_inizio=date(2026, 9, 3), data_fine=date(2026, 9, 8),
        )
        avanti = [date(2026, 9, 6), date(2026, 9, 13)]
        indietro = [date(2026, 9, 13), date(2026, 9, 6)]

        genera_lezioni(self.sess, time(8, 0), time(17, 0), date_puntuali=avanti)
        genera_lezioni(altra, time(8, 0), time(17, 0), date_puntuali=indietro)

        self.assertEqual(
            list(self.sess.lezioni.order_by("numero").values_list("data", "numero")),
            list(altra.lezioni.order_by("numero").values_list("data", "numero")),
        )

    def test_priorita_sui_giorni_della_settimana(self):
        """Una data puntuale di sabato entra anche con «solo lunedì» spuntato."""
        sabato = date(2026, 9, 5)
        self.assertEqual(sabato.weekday(), 5)
        creati = genera_lezioni(
            self.sess, time(8, 0), time(17, 0),
            giorni_settimana={0}, date_puntuali=[sabato],
        )
        self.assertEqual([lz.data for lz in creati], [sabato])

    def test_giorni_da_pianificare_rispecchia_la_gerarchia(self):
        # date puntuali > giorni settimana > intervallo
        self.assertEqual(
            giorni_da_pianificare(self.sess, date_puntuali=[date(2026, 9, 20), date(2026, 9, 6)]),
            [date(2026, 9, 6), date(2026, 9, 20)],
        )
        self.assertEqual(
            giorni_da_pianificare(self.sess, giorni_settimana={3}), [date(2026, 9, 3)],
        )
        self.assertEqual(len(giorni_da_pianificare(self.sess)), 4)

    def test_weekend_coerente(self):
        # 3/9/2026 = giovedì … 8/9 = martedì: in mezzo sabato 5 e domenica 6.
        feriali = giorni_pianificabili(date(2026, 9, 3), date(2026, 9, 8))
        self.assertNotIn(date(2026, 9, 5), feriali)
        self.assertNotIn(date(2026, 9, 6), feriali)

        solo_weekend = giorni_pianificabili(
            date(2026, 9, 3), date(2026, 9, 8), giorni_settimana={5, 6},
        )
        self.assertEqual(solo_weekend, [date(2026, 9, 5), date(2026, 9, 6)])


# ---------------------------------------------------------------------------
# Integrità della sessione
# ---------------------------------------------------------------------------

class IntegritaSessioneTests(TestCase):
    def setUp(self):
        self.corso = _corso("PIA-INT")

    def test_sessione_senza_data_rifiutata_dal_servizio(self):
        with self.assertRaises(ValueError):
            crea_sessione_unica(self.corso, data_inizio=None)
        self.assertEqual(self.corso.sessioni.count(), 0)

    def test_intervallo_rovesciato_rifiutato_dal_servizio(self):
        with self.assertRaises(ValueError):
            crea_sessione_unica(
                self.corso, data_inizio=date(2026, 9, 10), data_fine=date(2026, 9, 1),
            )
        self.assertEqual(self.corso.sessioni.count(), 0)

    def test_intervallo_rovesciato_non_pianifica_giorni(self):
        self.assertEqual(giorni_pianificabili(date(2026, 9, 10), date(2026, 9, 1)), [])

    def test_form_sessione_rifiuta_data_fine_precedente(self):
        form = TrainingSessionForm(data={
            "corso": self.corso.pk, "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": "2026-09-10", "data_fine": "2026-09-01",
        })
        self.assertFalse(form.is_valid())

    def test_rigenerazione_non_duplica_ne_cancella(self):
        sess = _sessione(self.corso)
        genera_lezioni(sess, time(8, 0), time(17, 0), pausa_minuti=60)
        prima = set(sess.lezioni.values_list("data", flat=True))

        # Rilancio con parametri diversi: aggiunge solo il nuovo, non tocca il resto.
        genera_lezioni(sess, time(9, 0), time(13, 0), date_puntuali=[date(2026, 9, 20)])

        dopo = set(sess.lezioni.values_list("data", flat=True))
        self.assertTrue(prima.issubset(dopo))
        self.assertEqual(dopo - prima, {date(2026, 9, 20)})

    def test_rigenerazione_preserva_quanto_gia_compilato(self):
        sess = _sessione(self.corso)
        lezione = TrainingLesson.objects.create(
            sessione=sess, numero=1, data=date(2026, 9, 3),
            ora_inizio=time(14, 0), ora_fine=time(18, 0),
            argomento="Modulo pratico deciso a mano", note="Aula officina",
        )
        iscrizione = TrainingEnrollment.objects.create(sessione=sess, legacy_anagrafica_id=101)
        presenza = TrainingLessonAttendance.objects.create(
            lezione=lezione, legacy_anagrafica_id=101, enrollment=iscrizione,
            stato_presenza="PRESENTE", ore_effettive=Decimal("4.00"),
            firma_ingresso=True, signature_status="FIRMATO",
        )

        genera_lezioni(sess, time(8, 0), time(17, 0), pausa_minuti=60, argomento="Generico")

        lezione.refresh_from_db()
        presenza.refresh_from_db()
        self.assertEqual(lezione.argomento, "Modulo pratico deciso a mano")
        self.assertEqual(lezione.note, "Aula officina")
        self.assertEqual(lezione.ora_inizio, time(14, 0))
        self.assertEqual(presenza.stato_presenza, "PRESENTE")
        self.assertEqual(presenza.ore_effettive, Decimal("4.00"))
        self.assertTrue(presenza.firma_ingresso)
        self.assertEqual(TrainingLessonAttendance.objects.count(), 1)

    def test_errore_a_meta_generazione_non_lascia_giornate_orfane(self):
        sess = _sessione(self.corso)
        originale = TrainingLesson.objects.create
        chiamate = {"n": 0}

        def _create(*args, **kwargs):
            chiamate["n"] += 1
            if chiamate["n"] == 3:
                raise RuntimeError("scrittura fallita")
            return originale(*args, **kwargs)

        with mock.patch.object(TrainingLesson.objects, "create", side_effect=_create):
            with self.assertRaises(RuntimeError):
                genera_lezioni(sess, time(8, 0), time(17, 0), pausa_minuti=60)

        self.assertEqual(sess.lezioni.count(), 0, "La generazione e' tutto-o-niente.")

    def test_data_odierna_dal_fuso_del_progetto(self):
        """Le date di servizio nascono da timezone.localdate(), non da date.today()."""
        sess = crea_sessione_unica(
            self.corso, data_inizio=timezone.localdate(),
            ora_inizio=time(8, 0), ora_fine=time(17, 0), pausa_minuti=60,
        )
        self.assertEqual(sess.data_inizio, timezone.localdate())
        self.assertEqual(sess.lezioni.count(), 1)


# ---------------------------------------------------------------------------
# Validazione lato server: la POST arriva anche senza JavaScript
# ---------------------------------------------------------------------------

@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ValidazioneServerSideTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-pia", "su-pia@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso("PIA-SRV")
        self.sess = _sessione(self.corso, date(2026, 9, 1), date(2026, 9, 30))

    def _post(self, **extra):
        payload = {"ora_inizio": "08:00", "ora_fine": "17:00", "pausa_minuti": "60"}
        payload.update(extra)
        return self.client.post(
            reverse("anagrafica:formazione_lezioni_genera", args=[self.sess.pk]), payload,
        )

    def _messaggi(self, response) -> list[str]:
        return [str(m) for m in get_messages(response.wsgi_request)]

    def test_post_senza_javascript_con_formati_data_misti(self):
        """Il textarea resta compilabile a mano: gg/mm/aaaa, aaaa-mm-gg, gg-mm-aaaa."""
        resp = self._post(date_puntuali="06/09/2026\n2026-09-13\n20-09-2026")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            list(self.sess.lezioni.order_by("data").values_list("data", flat=True)),
            [date(2026, 9, 6), date(2026, 9, 13), date(2026, 9, 20)],
        )

    def test_date_duplicate_nel_post_creano_una_sola_lezione(self):
        resp = self._post(date_puntuali="06/09/2026\n06/09/2026\n06/09/2026")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.sess.lezioni.count(), 1)

    def test_riga_vuota_e_spazi_ignorati(self):
        self._post(date_puntuali="  06/09/2026  \n\n   \n13/09/2026")
        self.assertEqual(self.sess.lezioni.count(), 2)

    def test_data_non_parsabile_messaggio_chiaro_e_nessuna_lezione(self):
        resp = self._post(date_puntuali="06/09/2026\n32/13/2026")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.sess.lezioni.count(), 0)
        self.assertTrue(
            any("32/13/2026" in m and "Data non valida" in m for m in self._messaggi(resp)),
            self._messaggi(resp),
        )

    def test_weekday_fuori_catalogo_rifiutato(self):
        resp = self._post(giorni_settimana=["9"])
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.sess.lezioni.count(), 0)
        self.assertTrue(self._messaggi(resp))

    def test_weekday_non_numerico_rifiutato(self):
        resp = self._post(giorni_settimana=["lunedì"])
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.sess.lezioni.count(), 0)

    def test_nessun_giorno_ne_data_puntuale_rifiutato(self):
        resp = self._post(giorni_settimana=[])
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.sess.lezioni.count(), 0)

    def test_troppe_date_puntuali_rifiutate(self):
        base = date(2026, 1, 1)
        righe = "\n".join(
            (base + timedelta(days=i)).strftime("%d/%m/%Y") for i in range(MAX_DATE_PUNTUALI + 1)
        )
        resp = self._post(date_puntuali=righe)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.sess.lezioni.count(), 0)
        self.assertTrue(
            any("Troppe date" in m for m in self._messaggi(resp)), self._messaggi(resp),
        )

    def test_orario_incoerente_non_crea_nulla(self):
        self._post(ora_inizio="17:00", ora_fine="08:00", giorni_settimana=["0", "1", "2", "3", "4"])
        self.assertEqual(self.sess.lezioni.count(), 0)

    def test_generazione_parziale_dichiara_le_giornate_gia_presenti(self):
        self._post(date_puntuali="06/09/2026")
        resp = self._post(date_puntuali="06/09/2026\n13/09/2026")

        self.assertEqual(self.sess.lezioni.count(), 2)
        self.assertTrue(
            any("erano già a calendario" in m for m in self._messaggi(resp)),
            self._messaggi(resp),
        )
