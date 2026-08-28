"""Test per l'import courses-person.xlsx (services.formazione_import.import_courses_person).

Copre in particolare l'accoppiamento per titolo: nel gestionale il "Codice
corso" e' per-edizione (cambia di anno in anno anche per un corso ricorrente),
quindi un titolo gia' a catalogo con un codice diverso deve accoppiarsi al
TrainingCourse esistente invece di duplicarlo.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.test import TestCase

from anagrafica.models_formazione import TrainingCourse, TrainingPlan
from anagrafica.services import formazione_import as svc

LEGACY_ID_ROSSI = 501


def _fake_indexes():
    return ({"ROSSI MARIO": LEGACY_ID_ROSSI}, {})


def _row(codice_corso, corso, piano="NOVICROM", inizio=date(2026, 3, 1), fine=date(2026, 3, 1)):
    return {
        "Iscritto": "ROSSI MARIO",
        "Codice fiscale": "RSSMRA80A01H501Z",
        "Piano formativo": piano,
        "Codice corso": codice_corso,
        "Corso": corso,
        "Modalità di erogazione": "AULA",
        "Luogo del corso": "Sede centrale",
        "Sede": "",
        "Durata (ore)": 4,
        "Frequenza": 4,
        "Ore partecipate (%)": 100,
        "Inizio corso": inizio,
        "Fine corso": fine,
        "Ha partecipato al corso ?": "Si",
        "Ha superato il corso ?": "Si",
    }


class ImportCoursesPersonAccoppiamentoTitoloTests(TestCase):
    def setUp(self):
        self.piano = TrainingPlan.objects.create(
            nome="NOVICROM", codice="P-NOVICROM", categoria="CONSIGLIATA",
            stato="ATTIVO", is_active=True,
        )
        self.corso_esistente = TrainingCourse.objects.create(
            piano=self.piano, codice="888", titolo="Corso Ricorrente",
            durata_ore_teorica=4, stato="ATTIVO", is_active=True,
        )

    def _run(self, rows, commit: bool) -> dict:
        with patch.object(svc, "_read_rows", return_value=rows), \
             patch.object(svc, "_build_lookup_indexes", side_effect=_fake_indexes):
            return svc.import_courses_person("finto.xlsx", commit=commit)

    def test_codice_nuovo_stesso_titolo_si_accoppia_non_duplica(self):
        rows = [_row("999", "Corso Ricorrente")]

        report = self._run(rows, commit=True)

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["corsi_created"], 0)
        self.assertEqual(report["corsi_accoppiati_per_titolo"], 1)
        self.assertEqual(TrainingCourse.objects.count(), 1)  # nessun corso nuovo

        sessione = self.corso_esistente.sessioni.get(data_inizio=date(2026, 3, 1))
        self.assertEqual(sessione.corso_id, self.corso_esistente.pk)

    def test_titolo_ripetuto_nella_stessa_run_si_accoppia_al_primo(self):
        rows = [
            _row("777", "Corso Mai Visto"),
            _row("776", "Corso Mai Visto", inizio=date(2026, 4, 1), fine=date(2026, 4, 1)),
        ]

        report = self._run(rows, commit=True)

        self.assertEqual(report["errors"], [])
        self.assertEqual(report["corsi_created"], 1)
        self.assertEqual(report["corsi_accoppiati_per_titolo"], 1)
        self.assertEqual(
            TrainingCourse.objects.filter(titolo="Corso Mai Visto").count(), 1
        )

    def test_titolo_diverso_crea_corso_nuovo(self):
        rows = [_row("999", "Corso Del Tutto Diverso")]

        report = self._run(rows, commit=True)

        self.assertEqual(report["corsi_created"], 1)
        self.assertEqual(report["corsi_accoppiati_per_titolo"], 0)
        self.assertEqual(TrainingCourse.objects.count(), 2)

    def test_dry_run_non_scrive_nulla_ma_conta_accoppiamento(self):
        rows = [_row("999", "Corso Ricorrente")]

        report = self._run(rows, commit=False)

        self.assertEqual(report["corsi_accoppiati_per_titolo"], 1)
        self.assertEqual(report["corsi_created"], 0)
        self.assertEqual(TrainingCourse.objects.count(), 1)  # invariato, era gia' 1 dal setUp
