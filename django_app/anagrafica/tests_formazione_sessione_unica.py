"""Formazione HR — sessione unica, ore al netto della pausa, completamento senza sessione.

Copre le tre novità del flusso corso→sessione:
- la **pausa** che scala le ore formative (08:00–17:00 con 60′ = 8h, non 9);
- la **sessione unica** creata insieme al corso, con le giornate già a calendario;
- il **completamento diretto**, per il corso frequentato altrove che non deve
  inventarsi una sessione e un registro presenze.

Nota ambiente: `LEGACY_AUTH_ENABLED=False` evita che il middleware ACL neghi tutto
ai non-superuser (vedi memoria assets_test_legacy_auth_disabled).
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import TrainingLessonForm, TrainingSessionForm
from .models_formazione import (
    TrainingCourse,
    TrainingEmployeeRecord,
    TrainingLesson,
    TrainingPlan,
    TrainingSession,
)
from .services.formazione_pianificazione import (
    crea_sessione_unica,
    genera_codice_sessione,
    genera_lezioni,
    giorni_pianificabili,
    ore_nette,
)

User = get_user_model()


def _piano(codice="SIC") -> TrainingPlan:
    return TrainingPlan.objects.create(codice=codice, nome=f"Piano {codice}")


def _corso(piano=None, codice="SIC-1", durata="8.00") -> TrainingCourse:
    return TrainingCourse.objects.create(
        piano=piano or _piano(),
        codice=codice,
        titolo=f"Corso {codice}",
        durata_ore_teorica=Decimal(durata),
        validita_mesi=60,
        stato="ATTIVO",
    )


class DurataNettaTests(TestCase):
    """La pausa è tempo non formativo: va scalata ovunque si contino le ore."""

    def test_pausa_scalata_dalla_durata(self):
        corso = _corso()
        sess = TrainingSession.objects.create(
            corso=corso, codice_sessione="X-1",
            data_inizio=date(2026, 9, 1), data_fine=date(2026, 9, 1),
        )
        lez = TrainingLesson.objects.create(
            sessione=sess, numero=1, data=date(2026, 9, 1),
            ora_inizio=time(8, 0), ora_fine=time(17, 0), pausa_minuti=60,
            argomento="Giornata unica",
        )
        self.assertEqual(lez.durata_ore_lorde, 9.0)
        self.assertEqual(lez.durata_ore, 8.0)

    def test_senza_pausa_durata_invariata(self):
        """Retro-compatibilità: i dati storici hanno pausa_minuti=0."""
        corso = _corso(codice="SIC-2")
        sess = TrainingSession.objects.create(
            corso=corso, codice_sessione="X-2",
            data_inizio=date(2026, 9, 1), data_fine=date(2026, 9, 1),
        )
        lez = TrainingLesson.objects.create(
            sessione=sess, numero=1, data=date(2026, 9, 1),
            ora_inizio=time(9, 0), ora_fine=time(13, 0), argomento="Mattina",
        )
        self.assertEqual(lez.pausa_minuti, 0)
        self.assertEqual(lez.durata_ore, 4.0)

    def test_ore_nette_helper(self):
        self.assertEqual(ore_nette(time(8, 0), time(17, 0), 60), 8.0)
        self.assertEqual(ore_nette(time(8, 0), time(17, 0), 0), 9.0)
        self.assertEqual(ore_nette(time(8, 0), time(12, 30), 15), 4.25)
        # La pausa non genera mai ore negative
        self.assertEqual(ore_nette(time(8, 0), time(9, 0), 120), 0.0)

    def test_ore_pianificate_sessione(self):
        corso = _corso(codice="SIC-3")
        sess = TrainingSession.objects.create(
            corso=corso, codice_sessione="X-3",
            data_inizio=date(2026, 9, 1), data_fine=date(2026, 9, 2),
        )
        for i, giorno in enumerate([date(2026, 9, 1), date(2026, 9, 2)], start=1):
            TrainingLesson.objects.create(
                sessione=sess, numero=i, data=giorno,
                ora_inizio=time(8, 0), ora_fine=time(17, 0), pausa_minuti=60,
                argomento="G",
            )
        self.assertEqual(sess.ore_pianificate, 16.0)

    def test_form_rifiuta_pausa_piu_lunga_della_lezione(self):
        corso = _corso(codice="SIC-4")
        sess = TrainingSession.objects.create(
            corso=corso, codice_sessione="X-4",
            data_inizio=date(2026, 9, 1), data_fine=date(2026, 9, 1),
        )
        form = TrainingLessonForm(
            data={
                "numero": 1, "data": "2026-09-01",
                "ora_inizio": "09:00", "ora_fine": "10:00",
                "pausa_minuti": 60, "argomento": "Troppa pausa",
            },
            sessione=sess,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("pausa_minuti", form.errors)


class CodiceSessioneTests(TestCase):
    """Il codice edizione si deriva dal corso: un campo in meno da compilare."""

    def test_progressivo_per_corso(self):
        corso = _corso(codice="ANT-01")
        self.assertEqual(genera_codice_sessione(corso), "ANT-01-E1")
        TrainingSession.objects.create(
            corso=corso, codice_sessione="ANT-01-E1",
            data_inizio=date(2026, 9, 1), data_fine=date(2026, 9, 1),
        )
        self.assertEqual(genera_codice_sessione(corso), "ANT-01-E2")

    def test_form_sessione_completa_codice_e_data_fine(self):
        corso = _corso(codice="PRE-01")
        form = TrainingSessionForm(data={
            "corso": corso.pk, "stato": "PIANIFICATA", "modalita": "IN_SEDE",
            "data_inizio": "2026-09-10",
            # codice_sessione e data_fine volutamente omessi
        })
        self.assertTrue(form.is_valid(), form.errors)
        sessione = form.save()
        self.assertEqual(sessione.codice_sessione, "PRE-01-E1")
        self.assertEqual(sessione.data_fine, date(2026, 9, 10))


class GeneraLezioniTests(TestCase):
    def setUp(self):
        self.corso = _corso(codice="GEN-01")
        # 2026-09-03 = giovedì, 2026-09-08 = martedì (in mezzo sabato e domenica)
        self.sess = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="GEN-01-E1",
            data_inizio=date(2026, 9, 3), data_fine=date(2026, 9, 8),
        )

    def test_giorni_pianificabili_salta_weekend(self):
        giorni = giorni_pianificabili(date(2026, 9, 3), date(2026, 9, 8))
        self.assertEqual(giorni, [date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 7), date(2026, 9, 8)])
        tutti = giorni_pianificabili(date(2026, 9, 3), date(2026, 9, 8), salta_weekend=False)
        self.assertEqual(len(tutti), 6)

    def test_giorni_pianificabili_con_giorni_settimana_specifici(self):
        # 2026-09-03=giovedì(3) .. 2026-09-08=martedì(1): solo Mar+Gio nell'intervallo.
        giorni = giorni_pianificabili(date(2026, 9, 3), date(2026, 9, 8), giorni_settimana={1, 3})
        self.assertEqual(giorni, [date(2026, 9, 3), date(2026, 9, 8)])

    def test_genera_una_lezione_per_giorno_feriale(self):
        creati = genera_lezioni(self.sess, time(8, 0), time(17, 0), pausa_minuti=60)
        self.assertEqual(len(creati), 4)
        self.assertEqual([lz.numero for lz in creati], [1, 2, 3, 4])
        self.assertEqual(self.sess.ore_pianificate, 32.0)
        # L'argomento ricade sul titolo del corso quando non specificato
        self.assertEqual(creati[0].argomento, self.corso.titolo)

    def test_rilancio_idempotente_sui_giorni_gia_coperti(self):
        genera_lezioni(self.sess, time(8, 0), time(17, 0), pausa_minuti=60)
        di_nuovo = genera_lezioni(self.sess, time(8, 0), time(17, 0), pausa_minuti=60)
        self.assertEqual(di_nuovo, [])
        self.assertEqual(self.sess.lezioni.count(), 4)

    def test_rilancio_aggiunge_solo_i_giorni_nuovi(self):
        genera_lezioni(self.sess, time(8, 0), time(17, 0), pausa_minuti=60)
        self.sess.data_fine = date(2026, 9, 9)
        self.sess.save(update_fields=["data_fine"])
        nuovi = genera_lezioni(self.sess, time(8, 0), time(17, 0), pausa_minuti=60)
        self.assertEqual(len(nuovi), 1)
        self.assertEqual(nuovi[0].data, date(2026, 9, 9))
        self.assertEqual(nuovi[0].numero, 5)

    def test_genera_lezioni_con_giorni_settimana_specifici(self):
        # Solo Gio(3): nell'intervallo 3-8/9 c'è solo il 3.
        creati = genera_lezioni(self.sess, time(8, 0), time(17, 0), pausa_minuti=60, giorni_settimana={3})
        self.assertEqual(len(creati), 1)
        self.assertEqual(creati[0].data, date(2026, 9, 3))

    def test_genera_lezioni_con_date_puntuali_ignora_intervallo_e_settimana(self):
        # Le date puntuali possono anche cadere fuori dall'intervallo data_inizio/data_fine
        # della sessione (qui si estende oltre l'8/9): genera_lezioni non lo impedisce.
        date_scelte = [date(2026, 9, 3), date(2026, 9, 20)]
        creati = genera_lezioni(
            self.sess, time(8, 0), time(17, 0), pausa_minuti=60, date_puntuali=date_scelte,
        )
        self.assertEqual([lz.data for lz in creati], date_scelte)

    def test_genera_lezioni_con_date_puntuali_resta_idempotente(self):
        date_scelte = [date(2026, 9, 3), date(2026, 9, 20)]
        genera_lezioni(self.sess, time(8, 0), time(17, 0), pausa_minuti=60, date_puntuali=date_scelte)
        di_nuovo = genera_lezioni(
            self.sess, time(8, 0), time(17, 0), pausa_minuti=60, date_puntuali=date_scelte,
        )
        self.assertEqual(di_nuovo, [])
        self.assertEqual(self.sess.lezioni.count(), 2)


class CreaSessioneUnicaTests(TestCase):
    def test_sessione_unica_di_un_giorno(self):
        corso = _corso(codice="UNI-01")
        sess = crea_sessione_unica(
            corso, data_inizio=date(2026, 9, 10),
            ora_inizio=time(8, 0), ora_fine=time(17, 0), pausa_minuti=60,
            sede="Aula A",
        )
        self.assertEqual(sess.codice_sessione, "UNI-01-E1")
        self.assertEqual(sess.data_fine, date(2026, 9, 10))
        self.assertEqual(sess.lezioni.count(), 1)
        self.assertEqual(sess.ore_pianificate, 8.0)

    def test_senza_orari_nessuna_giornata(self):
        corso = _corso(codice="UNI-02")
        sess = crea_sessione_unica(corso, data_inizio=date(2026, 9, 10))
        self.assertEqual(sess.lezioni.count(), 0)

    def test_sessione_con_date_puntuali_deriva_intervallo_dal_min_max(self):
        corso = _corso(codice="UNI-03")
        date_scelte = [date(2026, 9, 20), date(2026, 9, 6), date(2026, 9, 13)]
        sess = crea_sessione_unica(
            corso, data_inizio=None,
            ora_inizio=time(8, 0), ora_fine=time(17, 0), pausa_minuti=60,
            date_puntuali=date_scelte,
        )
        self.assertEqual(sess.data_inizio, date(2026, 9, 6))
        self.assertEqual(sess.data_fine, date(2026, 9, 20))
        self.assertEqual(sess.lezioni.count(), 3)
        self.assertEqual([lz.data for lz in sess.lezioni.order_by("data")], sorted(date_scelte))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CorsoCreateConSessioneUnicaTests(TestCase):
    """Il wizard «nuovo corso» può chiudere in un colpo solo anche la programmazione."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-fsu", "su-fsu@test.local", "x")
        self.client.force_login(self.su)
        self.piano = _piano("WIZ")

    def _post_corso(self, **extra):
        data = {
            "piano": self.piano.pk, "codice": "WIZ-01", "titolo": "Corso wizard",
            "durata_ore_teorica": "8", "validita_mesi": "60",
            "quiz_punteggio_minimo": "70", "stato": "ATTIVO", "versione": "1.0",
            "is_active": "on",
        }
        data.update(extra)
        return self.client.post(reverse("anagrafica:formazione_corso_create"), data)

    def test_corso_senza_programmazione_non_crea_sessioni(self):
        resp = self._post_corso()
        self.assertEqual(resp.status_code, 302)
        corso = TrainingCourse.objects.get(codice="WIZ-01")
        self.assertEqual(corso.sessioni.count(), 0)
        self.assertIn(f"/corsi/{corso.pk}/", resp["Location"])

    def test_corso_con_sessione_unica(self):
        resp = self._post_corso(**{
            "sess-pianifica": "on",
            "sess-data_inizio": "2026-09-10",
            "sess-ora_inizio": "08:00",
            "sess-ora_fine": "17:00",
            "sess-pausa_minuti": "60",
            "sess-modalita": "IN_SEDE",
            "sess-sede": "Aula A",
            "sess-giorni_settimana": ["0", "1", "2", "3", "4"],
        })
        self.assertEqual(resp.status_code, 302)
        corso = TrainingCourse.objects.get(codice="WIZ-01")
        sess = corso.sessioni.get()
        self.assertEqual(sess.codice_sessione, "WIZ-01-E1")
        self.assertEqual(sess.sede, "Aula A")
        self.assertEqual(sess.lezioni.count(), 1)
        self.assertEqual(sess.ore_pianificate, 8.0)
        # Si atterra sulla sessione appena creata, non sul corso
        self.assertIn(f"/sessioni/{sess.pk}/", resp["Location"])

    def test_corso_con_giorni_settimana_ristretti(self):
        # 2026-09-01 (Mar) .. 2026-09-14 (Lun), solo Mar+Gio: 4 lezioni (1,3,8,10 sett.).
        resp = self._post_corso(**{
            "sess-pianifica": "on",
            "sess-data_inizio": "2026-09-01",
            "sess-data_fine": "2026-09-14",
            "sess-ora_inizio": "08:00",
            "sess-ora_fine": "17:00",
            "sess-pausa_minuti": "60",
            "sess-modalita": "IN_SEDE",
            "sess-giorni_settimana": ["1", "3"],
        })
        self.assertEqual(resp.status_code, 302)
        sess = TrainingCourse.objects.get(codice="WIZ-01").sessioni.get()
        self.assertEqual(sess.lezioni.count(), 4)
        self.assertEqual(sess.ore_pianificate, 32.0)

    def test_corso_senza_giorni_settimana_ne_date_puntuali_blocca_il_salvataggio(self):
        resp = self._post_corso(**{
            "sess-pianifica": "on",
            "sess-data_inizio": "2026-09-10",
            "sess-ora_inizio": "08:00",
            "sess-ora_fine": "17:00",
            "sess-giorni_settimana": [],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TrainingCourse.objects.filter(codice="WIZ-01").exists())

    def test_corso_con_date_puntuali_deriva_intervallo_e_ignora_giorni_settimana(self):
        resp = self._post_corso(**{
            "sess-pianifica": "on",
            "sess-ora_inizio": "08:00",
            "sess-ora_fine": "17:00",
            "sess-pausa_minuti": "60",
            "sess-giorni_settimana": [],
            "sess-date_puntuali": "06/09/2026\n13/09/2026\n20/09/2026",
        })
        self.assertEqual(resp.status_code, 302)
        corso = TrainingCourse.objects.get(codice="WIZ-01")
        sess = corso.sessioni.get()
        self.assertEqual(sess.data_inizio, date(2026, 9, 6))
        self.assertEqual(sess.data_fine, date(2026, 9, 20))
        self.assertEqual(sess.lezioni.count(), 3)

    def test_programmazione_senza_data_blocca_il_salvataggio(self):
        resp = self._post_corso(**{
            "sess-pianifica": "on",
            "sess-ora_inizio": "08:00",
            "sess-ora_fine": "17:00",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TrainingCourse.objects.filter(codice="WIZ-01").exists())

    def test_form_creazione_espone_la_tappa_programmazione(self):
        body = self.client.get(reverse("anagrafica:formazione_corso_create")).content.decode()
        self.assertIn('name="sess-pianifica"', body)
        self.assertIn('name="sess-pausa_minuti"', body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GeneraLezioniViewTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-fgl", "su-fgl@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso(codice="VGL-01")
        self.sess = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="VGL-01-E1",
            data_inizio=date(2026, 9, 3), data_fine=date(2026, 9, 4),
        )

    def test_genera_dalle_view(self):
        resp = self.client.post(
            reverse("anagrafica:formazione_lezioni_genera", args=[self.sess.pk]),
            {"ora_inizio": "08:00", "ora_fine": "17:00", "pausa_minuti": "60",
             "giorni_settimana": ["0", "1", "2", "3", "4"]},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.sess.lezioni.count(), 2)
        self.assertEqual(self.sess.ore_pianificate, 16.0)

    def test_orario_incoerente_non_crea_nulla(self):
        self.client.post(
            reverse("anagrafica:formazione_lezioni_genera", args=[self.sess.pk]),
            {"ora_inizio": "17:00", "ora_fine": "08:00", "pausa_minuti": "0"},
        )
        self.assertEqual(self.sess.lezioni.count(), 0)

    def test_genera_con_date_puntuali_fuori_intervallo_allarga_la_sessione(self):
        # La sessione nasce 3-4/9; una data puntuale al 20/9 è fuori range: la vista
        # deve allargare sessione.data_fine per restare coerente con le lezioni create.
        resp = self.client.post(
            reverse("anagrafica:formazione_lezioni_genera", args=[self.sess.pk]),
            {"ora_inizio": "08:00", "ora_fine": "17:00", "pausa_minuti": "60",
             "date_puntuali": "20/09/2026"},
        )
        self.assertEqual(resp.status_code, 302)
        self.sess.refresh_from_db()
        self.assertEqual(self.sess.lezioni.count(), 1)
        self.assertEqual(self.sess.data_inizio, date(2026, 9, 3))
        self.assertEqual(self.sess.data_fine, date(2026, 9, 20))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CompletamentoDirettoTests(TestCase):
    """Corso frequentato altrove: il record va a libretto senza sessione."""

    def setUp(self):
        self.su = User.objects.create_superuser("su-fcd", "su-fcd@test.local", "x")
        self.client.force_login(self.su)
        self.corso = _corso(codice="EXT-01")

    def _url(self):
        return reverse("anagrafica:formazione_corso_completamento_diretto", args=[self.corso.pk])

    def test_record_creato_senza_sessione(self):
        resp = self.client.post(self._url(), {
            "dipendenti_selezionati": ["101", "102"],
            "data_completamento": "2026-06-01",
            "erogato_da": "Ente esterno S.r.l.",
            "idoneo": "on",
        })
        self.assertEqual(resp.status_code, 302)
        records = TrainingEmployeeRecord.objects.filter(corso=self.corso)
        self.assertEqual(records.count(), 2)
        rec = records.get(legacy_anagrafica_id=101)
        self.assertIsNone(rec.sessione_id)
        self.assertIsNone(rec.enrollment_id)
        self.assertTrue(rec.idoneo)
        self.assertEqual(rec.teacher_name_snapshot, "Ente esterno S.r.l.")
        self.assertEqual(rec.session_code_snapshot, "")
        # Ore vuote = durata teorica del corso
        self.assertEqual(rec.ore_frequentate, Decimal("8.00"))
        # Validità 60 mesi → scadenza calcolata
        self.assertEqual(rec.data_scadenza, date(2031, 6, 1))

    def test_idempotente_sulla_stessa_data(self):
        payload = {
            "dipendenti_selezionati": ["101"],
            "data_completamento": "2026-06-01",
            "idoneo": "on",
        }
        self.client.post(self._url(), payload)
        self.client.post(self._url(), payload)
        self.assertEqual(TrainingEmployeeRecord.objects.filter(corso=self.corso).count(), 1)

    def test_data_futura_rifiutata(self):
        self.client.post(self._url(), {
            "dipendenti_selezionati": ["101"],
            "data_completamento": "2099-01-01",
            "idoneo": "on",
        })
        self.assertEqual(TrainingEmployeeRecord.objects.filter(corso=self.corso).count(), 0)

    def test_nessun_dipendente_selezionato(self):
        self.client.post(self._url(), {"data_completamento": "2026-06-01", "idoneo": "on"})
        self.assertEqual(TrainingEmployeeRecord.objects.filter(corso=self.corso).count(), 0)
