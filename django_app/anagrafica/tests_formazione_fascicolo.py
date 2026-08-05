"""Formazione HR — fascicolo dell'edizione: la catena dal piano alla firma.

Il fascicolo esisteva già (progettazione · programma · partecipanti · relazione)
ma rispondeva al «cosa» senza rispondere al «perché» né al «come lo dimostri».
Questi test presidiano le tre aggiunte:

- la testata parte dal **piano formativo** e dichiara l'**origine dell'obbligo**;
- una sezione mostra l'**evidenza della presenza giornata per giornata**, con
  quante firme ci sono e se il registro firmato è allegato;
- una sezione dichiara **cosa manca** perché il fascicolo regga a una verifica —
  è l'unica parte del documento che parla di ciò che non c'è, e serve a
  scoprirlo prima che lo chieda un ispettore.

Il PDF si verifica sul **testo estratto** (pymupdf, già in requirements): non si
asserisce sull'impaginazione, che è libera di cambiare.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from .models_formazione import (
    TrainingCourse,
    TrainingEnrollment,
    TrainingLesson,
    TrainingLessonAttendance,
    TrainingPlan,
    TrainingSession,
)
from .services.attestato_pdf import build_fascicolo_sessione_pdf_bytes


def _testo_pdf(blob: bytes) -> str:
    """Testo del PDF, senza a capo, per asserzioni robuste all'impaginazione."""
    import fitz

    doc = fitz.open(stream=blob, filetype="pdf")
    try:
        testo = " ".join(p.get_text() for p in doc)
    finally:
        doc.close()
    return " ".join(testo.split())


class FascicoloSessioneTests(TestCase):
    def setUp(self):
        self.piano = TrainingPlan.objects.create(codice="FAS", nome="Piano Sicurezza")
        self.corso = TrainingCourse.objects.create(
            piano=self.piano, codice="FAS-01", titolo="Antincendio rischio medio",
            durata_ore_teorica=Decimal("8.00"), stato="ATTIVO",
            fonte_obbligo="ACCORDO",
            riferimento_fonte="Accordo Stato-Regioni 21/12/2011",
            articolo_fonte="art. 37 c. 2",
        )
        self.sess = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="FAS-01-E1",
            data_inizio=date(2026, 4, 14), data_fine=date(2026, 4, 15),
            sede="Aula corsi", docente_nome="Ente accreditato",
        )
        self.lez1 = TrainingLesson.objects.create(
            sessione=self.sess, numero=1, data=date(2026, 4, 14),
            ora_inizio=time(8, 0), ora_fine=time(13, 0), argomento="Parte teorica",
        )
        self.lez2 = TrainingLesson.objects.create(
            sessione=self.sess, numero=2, data=date(2026, 4, 15),
            ora_inizio=time(8, 0), ora_fine=time(12, 0),
        )
        TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=101)
        TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=102)

    # ── testata: il perché, non solo il cosa ────────────────────────────────

    def test_testata_parte_dal_piano_e_dichiara_la_fonte(self):
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("Piano formativo", testo)
        self.assertIn("Piano Sicurezza", testo)
        self.assertIn("Origine dell'obbligo", testo)
        self.assertIn("Accordo Stato-Regioni", testo)
        self.assertIn("art. 37 c. 2", testo)

    def test_senza_fonte_il_fascicolo_si_genera_lo_stesso(self):
        """I corsi storici non hanno la fonte: il documento deve uscire comunque."""
        self.corso.fonte_obbligo = ""
        self.corso.riferimento_fonte = ""
        self.corso.articolo_fonte = ""
        self.corso.save()
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("Origine dell'obbligo", testo)
        self.assertIn("Mancante", testo)

    # ── evidenza delle presenze ─────────────────────────────────────────────

    def test_evidenza_presenze_conta_presenti_e_firme(self):
        TrainingLessonAttendance.objects.create(
            lezione=self.lez1, legacy_anagrafica_id=101,
            stato_presenza="PRESENTE", signature_status="FIRMATO",
        )
        TrainingLessonAttendance.objects.create(
            lezione=self.lez1, legacy_anagrafica_id=102,
            stato_presenza="ASSENTE_GIUST",
        )
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("Evidenza delle presenze", testo)
        self.assertIn("Registro firmato", testo)

    def test_registro_non_allegato_e_detto_esplicitamente(self):
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("NON allegato", testo)

    # ── completezza: cosa manca ─────────────────────────────────────────────

    def test_sezione_completezza_presente(self):
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("Completezza del fascicolo", testo)

    def test_argomento_mancante_segnalato_col_conteggio(self):
        """lez2 è senza argomento: il fascicolo deve dirlo, non tacerlo."""
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("Argomento indicato su ogni giornata", testo)
        self.assertIn("Mancante su 1 di 2", testo)

    def test_tutto_compilato_niente_mancante_sugli_argomenti(self):
        self.lez2.argomento = "Prova pratica"
        self.lez2.save()
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertNotIn("Mancante su 1 di 2", testo)

    def test_esito_mancante_sugli_iscritti_segnalato(self):
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("Esito registrato per ogni iscritto", testo)
        self.assertIn("Mancante su 2 di 2", testo)

    def test_docente_indicato_risulta_completo(self):
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("Docente indicato", testo)

    # ── robustezza ──────────────────────────────────────────────────────────

    def test_sessione_senza_giornate_ne_iscritti_non_rompe(self):
        vuota = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="FAS-01-E9",
            data_inizio=date(2026, 6, 1), data_fine=date(2026, 6, 1),
        )
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(vuota))
        self.assertIn("Nessuna giornata pianificata.", testo)
        self.assertIn("Completezza del fascicolo", testo)

    def test_qualifica_rilasciata_esposta_quando_presente(self):
        from .models import TipoQualifica

        self.corso.qualifica = TipoQualifica.objects.create(
            nome="Addetto antincendio", categoria="SICUREZZA",
        )
        self.corso.save()
        testo = _testo_pdf(build_fascicolo_sessione_pdf_bytes(self.sess))
        self.assertIn("Qualifica rilasciata", testo)
