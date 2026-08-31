"""Test per l'import 'N Estrazioni Corsi.xlsx' (services.formazione_import.import_estrazioni_corsi)."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.test import TestCase

from anagrafica.models_formazione import (
    TrainingCourse,
    TrainingInstructor,
    TrainingPlan,
    TrainingProvider,
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

    def test_dry_run_non_conta_doppio_tra_fogli(self):
        # Il corso 101 e la sua sessione (2026-01-10) compaiono sia in "Corsi"
        # che in "Corsi AGGIORNAMENTI" e non esistono ancora in DB: in dry-run
        # vanno contati come "creati" una volta sola, non una per foglio.
        report = self._run(commit=False)
        self.assertEqual(report["corsi_created"], 2)  # 101 (nuovo) + 102 (nuovo)
        self.assertEqual(report["corsi_updated"], 1)  # 101 ri-processato nel 2° foglio
        self.assertEqual(report["sessioni_created"], 1)  # sessione di 101 il 2026-01-10

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

    def test_solo_docenti_non_tocca_piani_corsi_sessioni(self):
        with patch.object(svc, "_read_rows", side_effect=_fake_read_rows):
            report = svc.import_estrazioni_corsi("finto.xlsx", commit=True, solo_docenti=True)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["docenti_created"], 1)
        self.assertEqual(TrainingInstructor.objects.count(), 1)
        self.assertFalse(TrainingPlan.objects.exists())
        self.assertFalse(TrainingCourse.objects.exists())
        self.assertFalse(TrainingSession.objects.exists())


ROWS_CORSI_ENTE = [
    {
        # DESCRIZIONE DOCENTE combacia con un TrainingProvider a catalogo:
        # è l'ente che eroga, non una persona — niente TrainingInstructor fittizio.
        "CODICE ATTIVITA'": 0, "DESCRIZIONE ATTIVITA'": "NOVICROM", "CODICE CORSO": 201,
        "DESCRIZIONE": "Corso qualità esterno", "DESCRIZIONE ESTESA": None,
        "ORE OBBLIGATORIE": 8, "DESCRIZIONE LUOGO": "Sede TÜV", "TIPO LUOGO": "ESTERNO",
        "CODICE DOCENTE": None, "DESCRIZIONE DOCENTE": "TÜV SUD", "STATO CORSO": "CHIUSO",
        "DATA INIZIO": date(2026, 2, 5), "DATA FINE": date(2026, 2, 5),
    },
]


def _fake_read_rows_ente(xlsx_path, sheet_name=None):
    if sheet_name == "Corsi":
        return [dict(r) for r in ROWS_CORSI_ENTE]
    return []


class ImportEstrazioniCorsiEnteComeDocenteTests(TestCase):
    """DESCRIZIONE DOCENTE è testo libero: quando combacia con un ente già a
    catalogo va trattato come tale (`docente_ente`), non come una persona —
    e il corso guadagna il suo `ente_formativo` dal primo caso incontrato.
    """

    def setUp(self):
        self.ente = TrainingProvider.objects.create(nome="TÜV SUD")

    def _run(self, commit: bool) -> dict:
        with patch.object(svc, "_read_rows", side_effect=_fake_read_rows_ente):
            return svc.import_estrazioni_corsi("finto.xlsx", commit=commit, sheets=["Corsi"])

    def test_dry_run_non_crea_istruttore_fittizio_e_conta_ente(self):
        report = self._run(commit=False)
        self.assertEqual(report["docenti_riconosciuti_come_ente"], 1)
        self.assertEqual(report["corsi_ente_formativo_impostato"], 1)
        self.assertFalse(TrainingInstructor.objects.exists())

    def test_commit_imposta_docente_ente_su_sessione_e_ente_formativo_su_corso(self):
        report = self._run(commit=True)
        self.assertEqual(report["errors"], [])
        self.assertFalse(TrainingInstructor.objects.exists())

        corso = TrainingCourse.objects.get(codice="201")
        self.assertEqual(corso.ente_formativo_id, self.ente.pk)

        sessione = TrainingSession.objects.get(corso=corso, data_inizio=date(2026, 2, 5))
        self.assertIsNone(sessione.docente_id)
        self.assertEqual(sessione.docente_ente_id, self.ente.pk)
        self.assertEqual(sessione.docente_nome, "TÜV SUD")
        self.assertEqual(sessione.erogatore_display, "TÜV SUD")

    def test_non_sovrascrive_ente_formativo_gia_impostato_a_mano(self):
        altro_ente = TrainingProvider.objects.create(nome="Altro ente")
        # Simula un corso già presente con ente_formativo impostato a mano
        # da un import precedente: il nuovo giro non deve toccarlo.
        piano = TrainingPlan.objects.create(nome="NOVICROM", codice="P-NOVICROM")
        TrainingCourse.objects.create(
            piano=piano, codice="201", titolo="Corso qualità esterno",
            durata_ore_teorica=8, stato="ATTIVO", is_active=True,
            ente_formativo=altro_ente,
        )
        self._run(commit=True)
        corso = TrainingCourse.objects.get(codice="201")
        self.assertEqual(corso.ente_formativo_id, altro_ente.pk)
