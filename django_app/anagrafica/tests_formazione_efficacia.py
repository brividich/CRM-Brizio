"""Formazione HR — evidenza della verifica e valutazione di efficacia.

Gli ultimi due anelli della catena, quelli in fondo:

- **anello 7**, la verifica: c'era solo un segno di spunta. Per l'e-learning il
  quiz conservava punteggio e risposte, per l'aula non restava nulla — e un
  flag non dimostra un apprendimento. Ora l'iscrizione porta modalità,
  punteggio e **la soglia applicata**, così l'esito resta rileggibile anni dopo
  con il criterio di allora e non con quello vigente al momento della lettura.
- **anello 8**, l'efficacia: il modulo raccontava benissimo *che* la formazione
  era stata erogata e nulla di *cosa avesse prodotto*. La valutazione nasce
  attesa al completamento, scade, e viene compilata dal preposto.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from .forms import TrainingEnrollmentEditForm
from .models_formazione import (
    TrainingCompletionRule,
    TrainingCourse,
    TrainingEfficacia,
    TrainingEmployeeRecord,
    TrainingEnrollment,
    TrainingPlan,
    TrainingSession,
)
from .services.formazione_efficacia import (
    aggiungi_mesi,
    mesi_efficacia_richiesti,
    pianifica_valutazione_efficacia,
    valutazioni_da_fare,
)


def _corso(codice="EFF-01", mesi_efficacia=0) -> TrainingCourse:
    corso = TrainingCourse.objects.create(
        piano=TrainingPlan.objects.create(codice=codice, nome=f"Piano {codice}"),
        codice=codice, titolo=f"Corso {codice}",
        durata_ore_teorica=Decimal("8.00"), stato="ATTIVO",
    )
    if mesi_efficacia:
        TrainingCompletionRule.objects.create(
            corso=corso, valutazione_efficacia_mesi=mesi_efficacia,
        )
    return corso


def _record(corso, quando=None, idoneo=True, legacy_id=777) -> TrainingEmployeeRecord:
    return TrainingEmployeeRecord.objects.create(
        corso=corso, legacy_anagrafica_id=legacy_id,
        data_completamento=quando or date(2026, 3, 10), idoneo=idoneo,
    )


# ---------------------------------------------------------------------------
# Anello 7 — evidenza della verifica
# ---------------------------------------------------------------------------

class VerificaApprendimentoTests(TestCase):
    def setUp(self):
        self.corso = _corso("VER-01")
        self.sess = TrainingSession.objects.create(
            corso=self.corso, codice_sessione="VER-01-E1",
            data_inizio=date(2026, 3, 9), data_fine=date(2026, 3, 10),
        )
        self.isc = TrainingEnrollment.objects.create(
            sessione=self.sess, legacy_anagrafica_id=777,
        )

    def _dati(self, **extra):
        dati = {"stato": "COMPLETATO", "ore_frequentate": "8"}
        dati.update(extra)
        return dati

    def test_punteggio_e_soglia_si_conservano(self):
        # Il campo è un input HTML di tipo number: il browser invia sempre il
        # punto decimale, quindi non serve tollerare la virgola qui.
        form = TrainingEnrollmentEditForm(
            data=self._dati(modalita_verifica="TEST", punteggio="82.50", punteggio_minimo="70"),
            instance=self.isc,
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())
        isc = form.save()
        self.assertEqual(isc.modalita_verifica, "TEST")
        self.assertEqual(isc.punteggio, Decimal("82.50"))
        self.assertEqual(isc.punteggio_minimo, 70)

    def test_esito_dedotto_dal_punteggio(self):
        """Lasciarlo a mano significa ritrovarsi «superata» con 40 su 60."""
        form = TrainingEnrollmentEditForm(
            data=self._dati(punteggio="40", punteggio_minimo="60"),
            instance=self.isc,
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertFalse(form.save().verifica_superata)

    def test_esito_dedotto_anche_al_pari_della_soglia(self):
        form = TrainingEnrollmentEditForm(
            data=self._dati(punteggio="70", punteggio_minimo="70"),
            instance=self.isc,
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertTrue(form.save().verifica_superata, "la soglia raggiunta è superamento")

    def test_senza_punteggio_l_esito_resta_manuale(self):
        form = TrainingEnrollmentEditForm(
            data=self._dati(verifica_superata="on"), instance=self.isc,
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertTrue(form.save().verifica_superata)

    def test_modalita_non_obbligatoria(self):
        form = TrainingEnrollmentEditForm(data=self._dati(), instance=self.isc)
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertEqual(form.save().modalita_verifica, "")


# ---------------------------------------------------------------------------
# Anello 8 — valutazione di efficacia
# ---------------------------------------------------------------------------

class AggiungiMesiTests(TestCase):
    def test_somma_semplice(self):
        self.assertEqual(aggiungi_mesi(date(2026, 3, 10), 6), date(2026, 9, 10))

    def test_cambio_anno(self):
        self.assertEqual(aggiungi_mesi(date(2026, 11, 5), 3), date(2027, 2, 5))

    def test_giorno_inesistente_arretra_a_fine_mese(self):
        """31 gennaio più un mese è il 28 febbraio, non un errore."""
        self.assertEqual(aggiungi_mesi(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_zero_mesi_non_sposta(self):
        self.assertEqual(aggiungi_mesi(date(2026, 3, 10), 0), date(2026, 3, 10))


class PianificaEfficaciaTests(TestCase):
    def test_corso_senza_regola_non_apre_niente(self):
        rec = _record(_corso("EFF-NO"))
        self.assertIsNone(pianifica_valutazione_efficacia(rec))
        self.assertEqual(TrainingEfficacia.objects.count(), 0)

    def test_corso_con_regola_apre_la_pendenza_datata(self):
        rec = _record(_corso("EFF-SI", mesi_efficacia=6), quando=date(2026, 3, 10))
        val = pianifica_valutazione_efficacia(rec)

        self.assertIsNotNone(val)
        self.assertEqual(val.attesa_dal, date(2026, 9, 10))
        self.assertEqual(val.legacy_anagrafica_id, rec.legacy_anagrafica_id)
        self.assertTrue(val.in_attesa)

    def test_idempotente(self):
        """Il completamento è uno, ma le strade che lo creano sono più d'una."""
        rec = _record(_corso("EFF-IDE", mesi_efficacia=3))
        pianifica_valutazione_efficacia(rec)
        pianifica_valutazione_efficacia(rec)
        self.assertEqual(rec.valutazioni_efficacia.count(), 1)

    def test_non_idoneo_non_si_valuta(self):
        """Non c'è efficacia da misurare su una formazione non superata."""
        rec = _record(_corso("EFF-KO", mesi_efficacia=6), idoneo=False)
        self.assertIsNone(pianifica_valutazione_efficacia(rec))

    def test_regola_disattivata_non_conta(self):
        corso = _corso("EFF-OFF", mesi_efficacia=6)
        regola = corso.regola_superamento
        regola.is_active = False
        regola.save()
        self.assertEqual(mesi_efficacia_richiesti(corso), 0)
        self.assertIsNone(pianifica_valutazione_efficacia(_record(corso)))


class ValutazioniDaFareTests(TestCase):
    def setUp(self):
        self.corso = _corso("EFF-LST", mesi_efficacia=6)
        self.oggi = timezone.localdate()

    def _pendenza(self, giorni_fa: int, legacy_id=777) -> TrainingEfficacia:
        rec = _record(self.corso, quando=self.oggi - timedelta(days=400), legacy_id=legacy_id)
        return TrainingEfficacia.objects.create(
            record=rec, legacy_anagrafica_id=legacy_id,
            attesa_dal=self.oggi - timedelta(days=giorni_fa),
        )

    def test_mostra_solo_cio_che_e_gia_dovuto(self):
        """Un elenco che anticipa le scadenze future si ignora in fretta."""
        dovuta = self._pendenza(10, legacy_id=1)
        futura = TrainingEfficacia.objects.create(
            record=_record(self.corso, legacy_id=2), legacy_anagrafica_id=2,
            attesa_dal=self.oggi + timedelta(days=30),
        )
        pendenti = list(valutazioni_da_fare())
        self.assertIn(dovuta, pendenti)
        self.assertNotIn(futura, pendenti)

    def test_le_piu_vecchie_per_prime(self):
        recente = self._pendenza(5, legacy_id=1)
        vecchia = self._pendenza(90, legacy_id=2)
        self.assertEqual(list(valutazioni_da_fare())[0], vecchia)
        self.assertIn(recente, list(valutazioni_da_fare()))

    def test_compilata_esce_dall_elenco(self):
        val = self._pendenza(10)
        val.valutata_il = self.oggi
        val.esito = "EFFICACE"
        val.save()
        self.assertNotIn(val, list(valutazioni_da_fare()))

    def test_filtro_per_persona(self):
        mia = self._pendenza(10, legacy_id=111)
        altrui = self._pendenza(10, legacy_id=222)
        pendenti = list(valutazioni_da_fare(legacy_anagrafica_id=111))
        self.assertIn(mia, pendenti)
        self.assertNotIn(altrui, pendenti)

    def test_scaduta_e_in_attesa(self):
        val = self._pendenza(10)
        self.assertTrue(val.in_attesa)
        self.assertTrue(val.scaduta)
        val.valutata_il = self.oggi
        self.assertFalse(val.in_attesa)
        self.assertFalse(val.scaduta)

    def test_rivalutazione_dopo_esito_non_pieno(self):
        """Dopo un «non efficace» si concorda un'azione e si rivaluta: le due
        valutazioni restano entrambe, perché entrambe sono storia."""
        val = self._pendenza(30)
        val.valutata_il = self.oggi - timedelta(days=20)
        val.esito = "NON_EFFICACE"
        val.azione = "Affiancamento per due settimane"
        val.save()
        TrainingEfficacia.objects.create(
            record=val.record, legacy_anagrafica_id=val.legacy_anagrafica_id,
            attesa_dal=self.oggi - timedelta(days=1),
        )
        self.assertEqual(val.record.valutazioni_efficacia.count(), 2)
        self.assertEqual(len(list(valutazioni_da_fare())), 1)


class FascicoloEfficaciaTests(TestCase):
    def _testo(self, sessione) -> str:
        import fitz

        from .services.attestato_pdf import build_fascicolo_sessione_pdf_bytes

        doc = fitz.open(stream=build_fascicolo_sessione_pdf_bytes(sessione), filetype="pdf")
        try:
            return " ".join(" ".join(p.get_text().split()) for p in doc)
        finally:
            doc.close()

    def test_verifica_col_punteggio_compare_nel_fascicolo(self):
        corso = _corso("FEF-01")
        sess = TrainingSession.objects.create(
            corso=corso, codice_sessione="FEF-01-E1",
            data_inizio=date(2026, 3, 9), data_fine=date(2026, 3, 9),
        )
        TrainingEnrollment.objects.create(
            sessione=sess, legacy_anagrafica_id=777, verifica_superata=True,
            punteggio=Decimal("82.00"), punteggio_minimo=70, modalita_verifica="TEST",
        )
        testo = self._testo(sess)
        self.assertIn("Superata", testo)
        self.assertIn("82", testo)
        self.assertIn("Test scritto", testo)

    def test_riga_efficacia_solo_se_il_corso_la_prevede(self):
        senza = _corso("FEF-NO")
        sess_senza = TrainingSession.objects.create(
            corso=senza, codice_sessione="FEF-NO-E1",
            data_inizio=date(2026, 3, 9), data_fine=date(2026, 3, 9),
        )
        self.assertNotIn("Valutazione di efficacia", self._testo(sess_senza))

        con = _corso("FEF-SI", mesi_efficacia=6)
        sess_con = TrainingSession.objects.create(
            corso=con, codice_sessione="FEF-SI-E1",
            data_inizio=date(2026, 3, 9), data_fine=date(2026, 3, 9),
        )
        self.assertIn("Valutazione di efficacia", self._testo(sess_con))
