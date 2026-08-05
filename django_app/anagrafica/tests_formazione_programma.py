"""Formazione HR — programma didattico su due livelli: corso e edizione.

Per la formazione dei lavoratori i contenuti minimi sono normati: senza un
programma dichiarato non si dimostra di averli coperti. Il programma vive su
due livelli, e la scelta che questi test presidiano è che l'edizione ne riceva
una **copia** e non un collegamento:

- se il corso cambia programma mesi dopo, l'edizione già erogata continua a
  documentare com'era allora (stessa logica degli snapshot di docente/titolo);
- l'edizione può **integrare** argomenti non previsti, e quelle integrazioni
  sono lavoro umano: non vengono mai buttate da una ricopiatura.

Il confronto fra previsto ed erogato passa dal collegamento giornata↔argomento.
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from .models_formazione import (
    TrainingCourse,
    TrainingCourseArgomento,
    TrainingLesson,
    TrainingPlan,
    TrainingSession,
    TrainingSessionArgomento,
)
from .services.formazione_pianificazione import (
    copia_programma_dal_corso,
    crea_sessione_unica,
    dividi_in_gruppi,
)


def _corso(codice="PRG-01", con_programma=True) -> TrainingCourse:
    corso = TrainingCourse.objects.create(
        piano=TrainingPlan.objects.create(codice=codice, nome=f"Piano {codice}"),
        codice=codice, titolo=f"Corso {codice}",
        durata_ore_teorica=Decimal("8.00"), stato="ATTIVO",
    )
    if con_programma:
        TrainingCourseArgomento.objects.create(
            corso=corso, ordine=1, argomento="Rischi specifici", ore_previste=Decimal("4.00"),
            riferimento="Allegato A, punto 3",
        )
        TrainingCourseArgomento.objects.create(
            corso=corso, ordine=2, argomento="Misure di prevenzione", ore_previste=Decimal("4.00"),
        )
    return corso


def _sessione(corso, codice=None) -> TrainingSession:
    return TrainingSession.objects.create(
        corso=corso, codice_sessione=codice or f"{corso.codice}-E1",
        data_inizio=date(2026, 5, 4), data_fine=date(2026, 5, 5),
    )


class CopiaProgrammaTests(TestCase):
    def test_copia_porta_le_voci_nell_edizione(self):
        corso = _corso()
        sess = _sessione(corso)
        creati = copia_programma_dal_corso(sess)

        self.assertEqual(creati, 2)
        voci = list(sess.programma.all())
        self.assertEqual([v.argomento for v in voci], ["Rischi specifici", "Misure di prevenzione"])
        self.assertEqual(voci[0].ore_previste, Decimal("4.00"))
        self.assertEqual(voci[0].riferimento, "Allegato A, punto 3")
        self.assertFalse(voci[0].aggiunto)

    def test_e_una_copia_non_un_collegamento(self):
        """Se il corso cambia dopo, l'edizione erogata resta com'era."""
        corso = _corso()
        sess = _sessione(corso)
        copia_programma_dal_corso(sess)

        voce_corso = corso.programma.first()
        voce_corso.argomento = "Rischi specifici — revisione 2027"
        voce_corso.save()

        self.assertEqual(sess.programma.first().argomento, "Rischi specifici")

    def test_cancellare_l_argomento_del_corso_non_svuota_l_edizione(self):
        corso = _corso()
        sess = _sessione(corso)
        copia_programma_dal_corso(sess)
        corso.programma.first().delete()

        sess.refresh_from_db()
        self.assertEqual(sess.programma.count(), 2)
        self.assertIsNone(sess.programma.first().origine_id)

    def test_idempotente(self):
        corso = _corso()
        sess = _sessione(corso)
        copia_programma_dal_corso(sess)
        self.assertEqual(copia_programma_dal_corso(sess), 0)
        self.assertEqual(sess.programma.count(), 2)

    def test_ricopiatura_forzata_conserva_le_integrazioni(self):
        """Le voci aggiunte a mano dall'edizione sono lavoro umano: non si buttano."""
        corso = _corso()
        sess = _sessione(corso)
        copia_programma_dal_corso(sess)
        TrainingSessionArgomento.objects.create(
            sessione=sess, ordine=99, argomento="Prova pratica su estintore", aggiunto=True,
        )

        copia_programma_dal_corso(sess, forza=True)

        argomenti = set(sess.programma.values_list("argomento", flat=True))
        self.assertIn("Prova pratica su estintore", argomenti)
        self.assertIn("Rischi specifici", argomenti)
        self.assertEqual(sess.programma.count(), 3)

    def test_corso_senza_programma_non_rompe(self):
        sess = _sessione(_corso("PRG-VUOTO", con_programma=False))
        self.assertEqual(copia_programma_dal_corso(sess), 0)
        self.assertEqual(sess.programma.count(), 0)


class ProgrammaNeiFlussiTests(TestCase):
    def test_sessione_unica_nasce_col_programma(self):
        corso = _corso("PRG-UNI")
        sess = crea_sessione_unica(
            corso, data_inizio=date(2026, 5, 4),
            ora_inizio=time(8, 0), ora_fine=time(17, 0),
        )
        self.assertEqual(sess.programma.count(), 2)

    def test_i_gruppi_ereditano_il_programma_della_sorgente(self):
        """I gruppi sono la stessa erogazione divisa: stesso programma, anche
        se la sorgente l'aveva integrato."""
        corso = _corso("PRG-GRP")
        sorgente = _sessione(corso)
        copia_programma_dal_corso(sorgente)
        TrainingSessionArgomento.objects.create(
            sessione=sorgente, ordine=50, argomento="Integrazione d'aula", aggiunto=True,
        )
        TrainingLesson.objects.create(
            sessione=sorgente, numero=1, data=date(2026, 5, 4),
            ora_inizio=time(8, 0), ora_fine=time(17, 0), argomento="Teoria",
        )

        gruppi = dividi_in_gruppi(sorgente, 2)

        nuovo = gruppi[1]
        self.assertEqual(nuovo.programma.count(), 3)
        self.assertIn("Integrazione d'aula", set(nuovo.programma.values_list("argomento", flat=True)))
        self.assertTrue(nuovo.programma.get(argomento="Integrazione d'aula").aggiunto)


class CoperturaProgrammaTests(TestCase):
    """Il collegamento giornata↔argomento è ciò che rende confrontabili
    previsto ed erogato."""

    def setUp(self):
        self.corso = _corso("PRG-COV")
        self.sess = _sessione(self.corso)
        copia_programma_dal_corso(self.sess)
        self.lez = TrainingLesson.objects.create(
            sessione=self.sess, numero=1, data=date(2026, 5, 4),
            ora_inizio=time(8, 0), ora_fine=time(12, 0), argomento="Prima giornata",
        )

    def test_argomento_svolto_risulta_coperto(self):
        voce = self.sess.programma.first()
        self.lez.argomenti_svolti.add(voce)

        self.assertEqual(list(voce.lezioni.all()), [self.lez])
        self.assertEqual(self.lez.argomenti_svolti.count(), 1)

    def test_argomento_non_svolto_resta_scoperto(self):
        voce = self.sess.programma.first()
        self.lez.argomenti_svolti.add(voce)

        scoperti = [v for v in self.sess.programma.all() if not v.lezioni.exists()]
        self.assertEqual(len(scoperti), 1)
        self.assertEqual(scoperti[0].argomento, "Misure di prevenzione")

    def test_fascicolo_dichiara_gli_argomenti_non_svolti(self):
        from .services.attestato_pdf import build_fascicolo_sessione_pdf_bytes
        import fitz

        self.lez.argomenti_svolti.add(self.sess.programma.first())
        doc = fitz.open(stream=build_fascicolo_sessione_pdf_bytes(self.sess), filetype="pdf")
        try:
            testo = " ".join(" ".join(p.get_text().split()) for p in doc)
        finally:
            doc.close()

        self.assertIn("Programma dichiarato e copertura", testo)
        self.assertIn("NON svolto", testo)
        self.assertIn("1 argomenti su 2 non svolti", testo)

    def test_fascicolo_senza_programma_lo_segnala(self):
        from .services.attestato_pdf import build_fascicolo_sessione_pdf_bytes
        import fitz

        self.sess.programma.all().delete()
        doc = fitz.open(stream=build_fascicolo_sessione_pdf_bytes(self.sess), filetype="pdf")
        try:
            testo = " ".join(" ".join(p.get_text().split()) for p in doc)
        finally:
            doc.close()

        self.assertIn("Programma didattico dichiarato", testo)
        self.assertIn("Mancante", testo)
