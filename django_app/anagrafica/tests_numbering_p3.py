"""Numerazione formazione: codice corso ``YYNNN``, edizione ``-<YY>E<N>``, lezioni.

Il codice non si digita piu': lo alloca il portale. Qui si verifica che i tre
livelli siano coerenti e che il cambio d'anno faccia la cosa giusta — il corso
tiene la sua identita', l'edizione riparte.
"""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import TrainingCourseForm, TrainingLessonForm
from .models_formazione import TrainingCourse, TrainingPlan, TrainingSession
from .services.formazione_numerazione import (
    alloca_codice_corso,
    anteprima_codice_corso,
    genera_codice_sessione,
    prossimo_numero_lezione,
)

User = get_user_model()


class CodiceCorsoTests(TestCase):
    """``YYNNN``: due cifre d'anno + progressivo dell'anno."""

    def test_primo_corso_dell_anno(self):
        self.assertEqual(alloca_codice_corso(2026), "26001")

    def test_progressivo_nell_anno(self):
        self.assertEqual(alloca_codice_corso(2026), "26001")
        self.assertEqual(alloca_codice_corso(2026), "26002")
        self.assertEqual(alloca_codice_corso(2026), "26003")

    def test_contatore_indipendente_per_anno(self):
        alloca_codice_corso(2026)
        alloca_codice_corso(2026)
        self.assertEqual(alloca_codice_corso(2027), "27001")
        self.assertEqual(alloca_codice_corso(2026), "26003")

    def test_salta_i_codici_gia_occupati(self):
        # Un codice importato a mano non deve generare un IntegrityError.
        piano = TrainingPlan.objects.create(codice="SIC", nome="Sicurezza")
        TrainingCourse.objects.create(
            piano=piano, codice="26001", titolo="Importato", durata_ore_teorica=1,
        )
        self.assertEqual(alloca_codice_corso(2026), "26002")

    def test_anteprima_non_consuma(self):
        self.assertEqual(anteprima_codice_corso(2026), "26001")
        self.assertEqual(anteprima_codice_corso(2026), "26001")
        self.assertEqual(alloca_codice_corso(2026), "26001")

    def test_form_corso_alloca_il_codice(self):
        piano = TrainingPlan.objects.create(codice="SIC", nome="Sicurezza")
        form = TrainingCourseForm(data={
            "piano": piano.pk, "titolo": "Antincendio base",
            "durata_ore_teorica": "8", "validita_mesi": "60",
            "quiz_punteggio_minimo": "70", "stato": "BOZZA", "versione": "1.0",
            "is_active": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        corso = form.save()
        self.assertRegex(corso.codice, r"^\d{5}$")

    def test_form_corso_non_ricodifica_uno_storico(self):
        # Il codice di un corso gia' nato non cambia: attestati ed export lo citano.
        piano = TrainingPlan.objects.create(codice="SIC", nome="Sicurezza")
        corso = TrainingCourse.objects.create(
            piano=piano, codice="SIC-1", titolo="Storico", durata_ore_teorica=4,
        )
        form = TrainingCourseForm(instance=corso, data={
            "piano": piano.pk, "titolo": "Storico rinominato",
            "durata_ore_teorica": "4", "validita_mesi": "0",
            "quiz_punteggio_minimo": "70", "stato": "ATTIVO", "versione": "1.0",
            "is_active": "on",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().codice, "SIC-1")


class CodiceEdizioneTests(TestCase):
    """``<codice corso>-<YY>E<N>``, con N che riparte a ogni anno."""

    def setUp(self):
        piano = TrainingPlan.objects.create(codice="SIC", nome="Sicurezza")
        self.corso = TrainingCourse.objects.create(
            piano=piano, codice="26066", titolo="Antincendio", durata_ore_teorica=8,
        )

    def _edizione(self, codice, anno):
        return TrainingSession.objects.create(
            corso=self.corso, codice_sessione=codice,
            data_inizio=date(anno, 6, 1), data_fine=date(anno, 6, 1),
        )

    def test_prima_edizione(self):
        self.assertEqual(genera_codice_sessione(self.corso, 2026), "26066-26E1")

    def test_progressivo_nello_stesso_anno(self):
        self._edizione("26066-26E1", 2026)
        self.assertEqual(genera_codice_sessione(self.corso, 2026), "26066-26E2")

    def test_riparte_col_nuovo_anno_ma_il_corso_resta_lo_stesso(self):
        self._edizione("26066-26E1", 2026)
        self._edizione("26066-26E2", 2026)
        nuovo = genera_codice_sessione(self.corso, 2027)
        self.assertEqual(nuovo, "26066-27E1")
        self.assertTrue(nuovo.startswith(self.corso.codice))

    def test_convive_coi_codici_storici(self):
        # Le edizioni vecchio formato non spostano il progressivo del nuovo.
        self._edizione("26066-E7", 2026)
        self.assertEqual(genera_codice_sessione(self.corso, 2026), "26066-26E1")

    def test_accetta_una_data_al_posto_dell_anno(self):
        self.assertEqual(
            genera_codice_sessione(self.corso, date(2028, 3, 4)), "26066-28E1"
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NumeroLezioneTests(TestCase):
    """La lezione ha il suo numero, progressivo dentro l'edizione."""

    def setUp(self):
        piano = TrainingPlan.objects.create(codice="SIC", nome="Sicurezza")
        self.corso = TrainingCourse.objects.create(
            piano=piano, codice="26001", titolo="Corso", durata_ore_teorica=8,
        )
        self.sessione = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="26001-26E1",
            data_inizio=date(2026, 6, 1), data_fine=date(2026, 6, 5),
        )

    def _crea_lezione(self, giorno):
        form = TrainingLessonForm(
            data={
                "data": f"2026-06-{giorno:02d}", "ora_inizio": "09:00",
                "ora_fine": "13:00", "pausa_minuti": "0", "argomento": "Teoria",
            },
            sessione=self.sessione,
        )
        self.assertTrue(form.is_valid(), form.errors)
        lezione = form.save(commit=False)
        lezione.sessione = self.sessione
        lezione.save()
        return lezione

    def test_numerazione_automatica(self):
        self.assertEqual(self._crea_lezione(1).numero, 1)
        self.assertEqual(self._crea_lezione(2).numero, 2)
        self.assertEqual(self._crea_lezione(3).numero, 3)

    def test_non_riusa_il_numero_di_una_lezione_cancellata(self):
        # Il numero 2 e' gia' finito su un registro firme stampato: cancellare
        # quella giornata non lo fa rinascere sulla prossima.
        self._crea_lezione(1)
        seconda = self._crea_lezione(2)
        self._crea_lezione(3)
        seconda.delete()
        self.assertEqual(prossimo_numero_lezione(self.sessione), 4)

    def test_edizione_senza_lezioni_parte_da_uno(self):
        self.assertEqual(prossimo_numero_lezione(self.sessione), 1)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CodiceSuggestEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="cod_p3", email="cod_p3@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_anteprima_a_cinque_cifre(self):
        r = self.client.get(reverse("anagrafica:formazione_corso_codice_suggest"))
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertRegex(data["codice"], r"^\d{5}$")
        self.assertTrue(data["anteprima"])
