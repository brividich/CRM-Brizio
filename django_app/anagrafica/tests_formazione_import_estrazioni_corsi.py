"""Test per l'import 'N Estrazioni Corsi.xlsx' (services.formazione_import.import_estrazioni_corsi)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.test import TestCase

from anagrafica.models_formazione import (
    TrainingCourse,
    TrainingInstructor,
    TrainingPlan,
    TrainingSession,
)
from anagrafica.services import formazione_import as svc

ROWS_CORSI = [
    {
        "CODICE ATTIVITA'": 0, "DESCRIZIONE ATTIVITA'": "NOVICROM", "CODICE CORSO": 101,
        "DESCRIZIONE": "Corso sicurezza base", "DESCRIZIONE ESTESA": "Formazione generale",
        "ORE OBBLIGATORIE": 4, "DESCRIZIONE LUOGO": "Costruzioni Novicrom", "TIPO LUOGO": "INTERNO",
        "CODICE DOCENTE": None, "DESCRIZIONE DOCENTE": "Mario Rossi", "STATO CORSO": "CHIUSO",
        "DATA INIZIO": date(2026, 1, 10), "DATA FINE": date(2026, 1, 10),
    },
    {
        # riga senza CODICE CORSO — deve essere saltata
        "CODICE ATTIVITA'": 0, "DESCRIZIONE ATTIVITA'": "NOVICROM", "CODICE CORSO": 0,
        "DESCRIZIONE": None, "DESCRIZIONE ESTESA": None, "ORE OBBLIGATORIE": 0,
        "DESCRIZIONE LUOGO": None, "TIPO LUOGO": None, "CODICE DOCENTE": None,
        "DESCRIZIONE DOCENTE": "#N/A", "STATO CORSO": None, "DATA INIZIO": None, "DATA FINE": None,
    },
    {
        # senza data inizio — corso/docente creati, sessione no
        "CODICE ATTIVITA'": None, "DESCRIZIONE ATTIVITA'": "SISTEMI INFORMATICI", "CODICE CORSO": 102,
        "DESCRIZIONE": "Corso IT", "DESCRIZIONE ESTESA": None, "ORE OBBLIGATORIE": None,
        "DESCRIZIONE LUOGO": None, "TIPO LUOGO": "ESTERNO", "CODICE DOCENTE": None,
        "DESCRIZIONE DOCENTE": None, "STATO CORSO": "APERTO", "DATA INIZIO": None, "DATA FINE": None,
    },
]

ROWS_AGGIORNAMENTI = [
    {
        # stesso corso 101, sessione con la stessa data_inizio → deve aggiornare, non duplicare
        "CODICE ATTIVITA'": None, "DESCRIZIONE ATTIVITA'": "NOVICROM", "CODICE CORSO": 101,
        "DESCRIZIONE": "Corso sicurezza base", "DESCRIZIONE ESTESA": "Formazione generale",
        "ORE OBBLIGATORIE": 4, "DESCRIZIONE LUOGO": "Costruzioni Novicrom - Sala A", "TIPO LUOGO": "INTERNO",
        "CODICE DOCENTE": None, "DESCRIZIONE DOCENTE": "Mario Rossi", "STATO CORSO": "EROGATO",
        "DATA INIZIO": date(2026, 1, 10), "DATA FINE": date(2026, 1, 10), "NOTE": "aggiornata sede",
    },
]


def _fake_read_rows(xlsx_path, sheet_name=None):
    if sheet_name == "Corsi":
        return [dict(r) for r in ROWS_CORSI]
    if sheet_name == "Corsi AGGIORNAMENTI":
        return [dict(r) for r in ROWS_AGGIORNAMENTI]
    return []


class ImportEstrazioniCorsiTests(TestCase):
    def _run(self, commit: bool) -> dict:
        with patch.object(svc, "_read_rows", side_effect=_fake_read_rows):
            return svc.import_estrazioni_corsi("finto.xlsx", commit=commit)

    def test_dry_run_non_scrive_nulla(self):
        report = self._run(commit=False)
        self.assertEqual(report["righe_saltate"], 1)  # riga con CODICE CORSO=0 nel foglio "Corsi"
        self.assertFalse(TrainingCourse.objects.exists())
        self.assertFalse(TrainingInstructor.objects.exists())
        self.assertFalse(TrainingSession.objects.exists())
        self.assertEqual(report["errors"], [])

    def test_commit_crea_piano_corso_docente_sessione(self):
        report = self._run(commit=True)
        self.assertEqual(report["errors"], [])

        piano = TrainingPlan.objects.get(nome="NOVICROM")
        self.assertTrue(piano.pk)

        corso = TrainingCourse.objects.get(codice="101")
        self.assertEqual(corso.titolo, "Corso sicurezza base")
        self.assertEqual(corso.piano_id, piano.pk)

        docente = TrainingInstructor.objects.get(nome__iexact="Mario Rossi")
        self.assertEqual(docente.tipo, "ESTERNO")  # nessun match in anagrafica legacy (SQLite dev vuota)

        # Corso 102 creato ma senza sessione (niente DATA INIZIO)
        self.assertTrue(TrainingCourse.objects.filter(codice="102").exists())
        self.assertFalse(TrainingSession.objects.filter(corso__codice="102").exists())

        sessione = TrainingSession.objects.get(corso=corso, data_inizio=date(2026, 1, 10))
        # Il foglio "Corsi AGGIORNAMENTI" (letto dopo) ha aggiornato sede/stato/docente sulla stessa sessione
        self.assertEqual(sessione.sede, "Costruzioni Novicrom - Sala A")
        self.assertEqual(sessione.stato, "IN_CORSO")  # EROGATO → IN_CORSO
        self.assertEqual(sessione.docente_id, docente.pk)
        self.assertEqual(sessione.note, "aggiornata sede")

        self.assertEqual(TrainingSession.objects.filter(corso=corso).count(), 1)  # niente duplicati

    def test_commit_e_rilancio_e_idempotente(self):
        self._run(commit=True)
        report2 = self._run(commit=True)
        self.assertEqual(report2["errors"], [])
        self.assertEqual(TrainingCourse.objects.count(), 2)
        self.assertEqual(TrainingInstructor.objects.count(), 1)
        self.assertEqual(TrainingSession.objects.count(), 1)
