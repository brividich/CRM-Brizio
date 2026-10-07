"""Le scadenze HR salvate restano giuste a ogni modifica, senza attendere la notte.

Ogni test cambia UN dato (della persona o di un catalogo) e verifica subito,
a transazione conclusa, la scadenza salvata: nessuno chiama il ricalcolo a mano.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from anagrafica.models import (
    DipendenteQualifica, DipendenteRuoloOperativo, Mansione, RuoloOperativo, TipoQualifica, TipoVisitaMedica,
    TrainingCourse, TrainingDeadline, TrainingEmployeeRecord, TrainingPlan, TrainingRequirementRule, VisitaMedica,
)
from anagrafica.models import _add_months
from anagrafica.tests_reportistica_dati_corretti import _persone

OGGI = timezone.localdate()


class _Base(TestCase):
    def setUp(self):
        super().setUp()
        p = patch("anagrafica.reportistica.dati.carica_dipendenti", side_effect=_persone)
        p.start()
        self.addCleanup(p.stop)

    def dopo_commit(self, fn):
        """Esegue ``fn`` e poi i callback di fine transazione (il ricalcolo)."""
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            risultato = fn()
        return risultato, callbacks


class VisiteEventiTest(_Base):
    def setUp(self):
        super().setUp()
        self.annuale = TipoVisitaMedica.objects.create(nome="Visita medica annuale", durata_mesi=12,
                                                       categoria="Visita medica")
        self.biennale = TipoVisitaMedica.objects.create(nome="Visita medica biennale", durata_mesi=24,
                                                        categoria="Visita medica")
        self.fatta = OGGI - timedelta(days=200)
        self.visita, _ = self.dopo_commit(lambda: VisitaMedica.objects.create(
            legacy_anagrafica_id=902, tipo=self.biennale, data_svolgimento=self.fatta))

    def scadenza(self):
        self.visita.refresh_from_db()
        return self.visita.data_scadenza

    def test_ruolo_assegnato_e_tolto(self):
        ruolo = RuoloOperativo.objects.create(nome="Saldatore")
        self.dopo_commit(lambda: self.annuale.ruoli_operativi.add(ruolo))
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 24))  # nessuno ha ancora il ruolo

        assegnazione, _ = self.dopo_commit(lambda: DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=902, ruolo=ruolo))
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 12))
        self.assertIn("Saldatore", self.visita.scadenza_nota)

        def chiudi():
            assegnazione.data_fine = OGGI - timedelta(days=1)
            assegnazione.save()
        self.dopo_commit(chiudi)
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 24))
        self.assertEqual(self.visita.scadenza_nota, "")

    def test_mansione_richiede_visita(self):
        mansione = Mansione.objects.create(nome="Operaio")  # 902 e' «Operaio»
        self.dopo_commit(lambda: mansione.visite_richieste.add(self.annuale))
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 12))
        self.dopo_commit(lambda: mansione.visite_richieste.remove(self.annuale))
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 24))

    def test_durata_del_tipo_cambiata(self):
        def allunga():
            self.biennale.durata_mesi = 36
            self.biennale.save()
        self.dopo_commit(allunga)
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 36))

    def test_campo_descrittivo_non_ricalcola(self):
        def rinomina():
            self.biennale.nome = "Visita medica ogni due anni"
            self.biennale.save()
        _r, callbacks = self.dopo_commit(rinomina)
        self.assertEqual(len(callbacks), 0)

    def test_visita_superata_torna_alla_scadenza_del_tipo(self):
        ruolo = RuoloOperativo.objects.create(nome="Saldatore")
        self.annuale.ruoli_operativi.add(ruolo)
        self.dopo_commit(lambda: DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=ruolo))
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 12))  # anticipata

        nuova, _ = self.dopo_commit(lambda: VisitaMedica.objects.create(
            legacy_anagrafica_id=902, tipo=self.annuale, data_svolgimento=OGGI - timedelta(days=5)))
        # La vecchia non e' piu' corrente: torna alla sua scadenza, senza nota.
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 24))
        self.assertEqual(self.visita.scadenza_nota, "")

        # Cancellata la nuova, la vecchia torna corrente e di nuovo anticipata.
        self.dopo_commit(nuova.delete)
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 12))

    def test_visita_spostata_su_altra_persona(self):
        ruolo = RuoloOperativo.objects.create(nome="Saldatore")
        self.annuale.ruoli_operativi.add(ruolo)
        self.dopo_commit(lambda: DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=ruolo))

        def sposta():
            self.visita.legacy_anagrafica_id = 901  # registrata sulla persona sbagliata
            self.visita.save()
        self.dopo_commit(sposta)
        self.assertEqual(self.scadenza(), _add_months(self.fatta, 24))  # 901 non ha il ruolo


class FormazioneEventiTest(_Base):
    def setUp(self):
        super().setUp()
        piano = TrainingPlan.objects.create(codice="PT", nome="Piano test", stato="ATTIVO")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="SIC", titolo="Sicurezza",
                                                   durata_ore_teorica=4, validita_mesi=12)

    def riga(self):
        return TrainingDeadline.objects.filter(legacy_anagrafica_id=902, corso=self.corso).first()

    def test_regola_attestato_e_cancellazione(self):
        self.dopo_commit(lambda: TrainingRequirementRule.objects.create(corso=self.corso, legacy_anagrafica_id=902))
        self.assertEqual(self.riga().stato_scadenza, "MAI_FREQUENTATO")

        fatto = OGGI - timedelta(days=30)
        record, _ = self.dopo_commit(lambda: TrainingEmployeeRecord.objects.create(
            corso=self.corso, legacy_anagrafica_id=902, idoneo=True,
            data_completamento=fatto, data_scadenza=_add_months(fatto, 12)))
        self.assertEqual(self.riga().stato_scadenza, "VALIDO")

        self.dopo_commit(record.delete)  # attestato registrato per errore
        self.assertEqual(self.riga().stato_scadenza, "MAI_FREQUENTATO")

    def test_regola_di_ruolo(self):
        ruolo = RuoloOperativo.objects.create(nome="Carrellista")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=902, ruolo=ruolo)
        regola, _ = self.dopo_commit(lambda: TrainingRequirementRule.objects.create(
            corso=self.corso, ruolo_operativo=ruolo))
        self.assertIsNotNone(self.riga())

        def disattiva():
            regola.is_active = False
            regola.save()
        self.dopo_commit(disattiva)
        self.assertIsNone(self.riga())

    def test_corso_disattivato(self):
        self.dopo_commit(lambda: TrainingRequirementRule.objects.create(corso=self.corso, legacy_anagrafica_id=902))
        self.assertIsNotNone(self.riga())

        def disattiva():
            self.corso.is_active = False
            self.corso.save()
        self.dopo_commit(disattiva)
        self.assertIsNone(self.riga())  # corso dismesso e mai frequentato: non e' un obbligo


class QualificheDpiEventiTest(_Base):
    def test_durata_tipo_qualifica(self):
        tipo = TipoQualifica.objects.create(nome="Patentino", durata_mesi=24)
        presa = OGGI - timedelta(days=100)
        auto = DipendenteQualifica.objects.create(legacy_anagrafica_id=902, tipo=tipo, data_conseguimento=presa,
                                                  data_scadenza=_add_months(presa, 24))
        a_mano = DipendenteQualifica.objects.create(legacy_anagrafica_id=901, tipo=tipo, data_conseguimento=presa,
                                                    data_scadenza=OGGI + timedelta(days=10))
        tipo.durata_mesi = 36
        tipo.save()
        auto.refresh_from_db()
        a_mano.refresh_from_db()
        self.assertEqual(auto.data_scadenza, _add_months(presa, 36))
        self.assertEqual(a_mano.data_scadenza, OGGI + timedelta(days=10))  # inserita a mano: resta

    def test_vita_utile_dpi(self):
        from dpi.models import CategoriaDPI, ConsegnaDPI, RichiestaDPI

        cat = CategoriaDPI.objects.create(nome="Guanti", vita_utile_giorni=180)
        consegnato = OGGI - timedelta(days=20)

        def consegna(scadenza, sostituita=None):
            r = RichiestaDPI.objects.create(categoria=cat, richiedente_legacy_id=902, richiedente_nome="X",
                                            stato="CONSEGNATA")
            return ConsegnaDPI.objects.create(richiesta=r, data_consegna=consegnato,
                                              data_scadenza_stimata=scadenza, sostituita_da=sostituita)

        auto = consegna(consegnato + timedelta(days=180))
        a_mano = consegna(consegnato + timedelta(days=30))
        vecchia = consegna(consegnato + timedelta(days=180), sostituita=auto)
        cat.vita_utile_giorni = 90
        cat.save()
        for c in (auto, a_mano, vecchia):
            c.refresh_from_db()
        self.assertEqual(auto.data_scadenza_stimata, consegnato + timedelta(days=90))
        self.assertEqual(a_mano.data_scadenza_stimata, consegnato + timedelta(days=30))
        self.assertEqual(vecchia.data_scadenza_stimata, consegnato + timedelta(days=180))  # gia' sostituita


class TransazioneTest(_Base):
    def test_un_solo_ricalcolo_per_transazione_e_tutti_vince(self):
        from anagrafica.services import scadenze

        with patch.object(scadenze, "ricalcola_tutto") as ricalcola:
            with self.captureOnCommitCallbacks(execute=True):
                scadenze.ricalcola_dopo_commit([901])
                scadenze.ricalcola_dopo_commit(None)
                scadenze.ricalcola_dopo_commit([902])
        ricalcola.assert_called_once_with(None)

    def test_persone_accumulate(self):
        from anagrafica.services import scadenze

        with patch.object(scadenze, "ricalcola_tutto") as ricalcola:
            with self.captureOnCommitCallbacks(execute=True):
                scadenze.ricalcola_dopo_commit([902])
                scadenze.ricalcola_dopo_commit([901, 902])
        ricalcola.assert_called_once_with([901, 902])

    def test_errore_nel_ricalcolo_non_blocca_il_salvataggio(self):
        tipo = TipoVisitaMedica.objects.create(nome="Visita", durata_mesi=12)
        with patch("anagrafica.services.scadenze.ricalcola_tutto", side_effect=RuntimeError("giu'")):
            v, _ = self.dopo_commit(lambda: VisitaMedica.objects.create(
                legacy_anagrafica_id=902, tipo=tipo, data_svolgimento=OGGI))
        self.assertTrue(VisitaMedica.objects.filter(pk=v.pk).exists())
