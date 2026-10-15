"""Integrita' delle letture: niente numeri non attribuibili alla macchina o al trimestre.

Dati sintetici.
"""
from datetime import date, datetime
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from . import services
from .models import Fattura, LetturaContatori, LetturaMensileContatori, Macchina, RigaFattura, StatoSNMP
from .snmp import SNMPError, verifica_lettura_mfc

VALORI = {"a4_bn": 1000, "a3_bn": 100, "a4_col": 500, "a3_col": 50}


def _aware(*args):
    return timezone.make_aware(datetime(*args))


class VerificaLetturaMfcTests(SimpleTestCase):
    def _m(self, matricola="SYN-12345"):
        return Macchina(reparto="QA", matricola=matricola, host="192.0.2.50")

    def test_matricola_uguale_o_con_separatori_ok(self):
        verifica_lettura_mfc(self._m(), VALORI, seriale=b"SYN12345", pagine_totali=1650)
        verifica_lettura_mfc(self._m(), VALORI, seriale="syn-12345 ", pagine_totali=None)

    def test_matricola_diversa_scartata(self):
        with self.assertRaisesMessage(SNMPError, "matricola ALTRA999, non SYN-12345"):
            verifica_lettura_mfc(self._m(), VALORI, seriale="ALTRA999")

    def test_senza_oid_di_controllo_nessun_blocco(self):
        verifica_lettura_mfc(self._m(), VALORI, seriale=None, pagine_totali=None)
        verifica_lettura_mfc(self._m(), VALORI, seriale="", pagine_totali="n/d")

    def test_somma_oltre_pagine_totali_scartata(self):
        with self.assertRaisesMessage(SNMPError, "supera le pagine totali"):
            verifica_lettura_mfc(self._m(), VALORI, pagine_totali=1000)

    def test_tolleranza_pagine_stampate_durante_la_lettura(self):
        verifica_lettura_mfc(self._m(), VALORI, pagine_totali=1650 - 50)


class ProgressioneTests(TestCase):
    def setUp(self):
        self.m = Macchina.objects.create(reparto="QA", matricola="SYN-P1", host="192.0.2.51")

    def test_nessuna_lettura_nessuna_incoerenza(self):
        self.assertEqual(services.incoerenze_lettura(self.m, VALORI), [])

    def test_confronta_con_la_lettura_piu_recente(self):
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q2", data=date(2026, 6, 30),
                                        **{**VALORI, "a4_bn": 5000})
        # Mensile piu' recente con azzeramento confermato: vale quella.
        LetturaMensileContatori.objects.create(macchina=self.m, mese=date(2026, 7, 1),
                                               rilevata_il=_aware(2026, 7, 1, 0, 5), **VALORI)
        self.assertEqual(services.incoerenze_lettura(self.m, VALORI), [])
        testi = services.incoerenze_lettura(self.m, {**VALORI, "a3_col": 49})
        self.assertEqual(len(testi), 1)
        self.assertIn("A3 COL 49", testi[0])
        self.assertIn("lettura mensile del 01/07/2026", testi[0])

    @mock.patch("contatori.services.interroga_macchina")
    def test_mensile_piu_bassa_non_salvata_e_segnalata(self, interroga):
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q2", data=date(2026, 6, 30), **VALORI)
        interroga.return_value = {**VALORI, "a4_col": 400}
        with self.assertRaisesMessage(SNMPError, "più bassi dell'ultima lettura"):
            services.leggi_mensile_macchina(self.m)
        self.assertFalse(LetturaMensileContatori.objects.exists())
        self.m.refresh_from_db()
        self.assertEqual(self.m.snmp_stato, StatoSNMP.ERROR)
        self.assertIn("A4 COL 400", self.m.snmp_ultimo_errore)

    @mock.patch("contatori.services.interroga_macchina")
    def test_leggi_mfc_ora_non_salva_valori_piu_bassi(self, interroga):
        oggi = date(2026, 10, 20)
        LetturaMensileContatori.objects.create(macchina=self.m, mese=date(2026, 10, 1),
                                               rilevata_il=_aware(2026, 10, 1, 0, 5), **VALORI)
        interroga.return_value = {**VALORI, "a4_bn": 999}
        esito = services.salva_letture_trimestrali_snmp(oggi)
        self.assertEqual(esito["incoerenti"], ["QA"])
        self.assertFalse(LetturaContatori.objects.exists())


class ProposteChiusuraTests(TestCase):
    def setUp(self):
        self.m = Macchina.objects.create(reparto="QA", matricola="SYN-P2", host="192.0.2.52")

    def _mensile(self, mese, quando):
        return LetturaMensileContatori.objects.create(macchina=self.m, mese=mese, rilevata_il=quando, **VALORI)

    def test_solo_la_lettura_di_chiusura_entro_il_giorno_7(self):
        # Lettura di inizio trimestre (= chiusura del precedente) e del mese dopo: mai proposte.
        self._mensile(date(2026, 7, 1), _aware(2026, 7, 1, 0, 5))
        self._mensile(date(2026, 11, 1), _aware(2026, 11, 1, 0, 5))
        self.assertEqual(services.proposte_letture_trimestrali("2026-Q3"), [])
        self._mensile(date(2026, 10, 1), _aware(2026, 10, 3, 9, 0))
        proposte = services.proposte_letture_trimestrali("2026-Q3")
        self.assertEqual([p["mensile"].mese for p in proposte], [date(2026, 10, 1)])

    def test_lettura_di_ottobre_troppo_tardi_non_proposta(self):
        self._mensile(date(2026, 10, 1), _aware(2026, 10, 20, 9, 0))
        self.assertEqual(services.proposte_letture_trimestrali("2026-Q3"), [])

    def test_piu_alta_del_trimestre_successivo_incoerente(self):
        self._mensile(date(2026, 10, 1), _aware(2026, 10, 1, 0, 5))
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q4", data=date(2026, 12, 31),
                                        **{**VALORI, "a4_bn": 900})
        proposta, = services.proposte_letture_trimestrali("2026-Q3")
        self.assertTrue(proposta["incoerente"])
        self.assertEqual(proposta["motivo"], "Più alta del 2026-Q4")


class ConsumoLacuneTests(TestCase):
    def setUp(self):
        self.a = Macchina.objects.create(reparto="A", matricola="SYN-A")
        self.b = Macchina.objects.create(reparto="B", matricola="SYN-B")
        for m in (self.a, self.b):
            LetturaContatori.objects.create(macchina=m, trimestre="2025-Q1", data=date(2025, 3, 31), **VALORI)
        # A letta ogni trimestre, B salta il Q2.
        LetturaContatori.objects.create(macchina=self.a, trimestre="2025-Q2", data=date(2025, 6, 30),
                                        **{**VALORI, "a4_bn": 1100})
        for m in (self.a, self.b):
            LetturaContatori.objects.create(macchina=m, trimestre="2025-Q3", data=date(2025, 9, 30),
                                            **{**VALORI, "a4_bn": 1300})

    def test_trimestre_mancante_non_attribuito_a_quello_dopo(self):
        consumo, anomalie = services.consumo_per_trimestre()
        per = {c["trimestre"]: c for c in consumo}
        self.assertEqual(anomalie, 0)
        self.assertEqual(per["2025-Q2"]["totale"], 100)
        self.assertTrue(per["2025-Q2"]["parziale"])
        # Prima: B portava 300 copie di due trimestri nel Q3.
        self.assertEqual(per["2025-Q3"]["totale"], 200)
        self.assertEqual((per["2025-Q3"]["macchine"], per["2025-Q3"]["attese"]), (1, 2))
        self.assertFalse(per["2025-Q3"]["in_corso"])

    def test_produzione_macchina_segnala_la_lacuna(self):
        righe = services.produzione_macchina(self.b)
        self.assertEqual(righe[-1]["manca"], "2025-Q2")
        self.assertEqual(righe[-1]["totale"], 0)

    def test_andamento_segnala_il_trimestre_parziale(self):
        per = {a["trimestre"]: a for a in services.andamento_trimestri()}
        self.assertTrue(per["2025-Q2"]["parziale"])
        self.assertFalse(per["2025-Q3"]["parziale"])

    def test_ripartizione_usa_l_ultima_lettura_di_ogni_mfc(self):
        LetturaContatori.objects.create(macchina=self.a, trimestre="2025-Q4", data=date(2025, 12, 31),
                                        **{**VALORI, "a4_bn": 1400})
        r = services.ripartizione()
        self.assertEqual(r["macchine"], 2)
        self.assertEqual(r["totale"], (1400 + 650) + (1300 + 650))


class RiconciliaDismesseTests(TestCase):
    def test_dismessa_senza_lettura_non_e_lettura_mancante(self):
        attiva = Macchina.objects.create(reparto="A", matricola="SYN-R1", contratto="K1")
        Macchina.objects.create(reparto="Vecchia", matricola="SYN-R0", contratto="K1", attiva=False)
        LetturaContatori.objects.create(macchina=attiva, trimestre="2026-Q2", data=date(2026, 7, 2), **VALORI)
        f = Fattura.objects.create(numero="F1", trimestre="2026-Q2", data=date(2026, 7, 10),
                                   periodo_dal=date(2026, 4, 1), periodo_al=date(2026, 6, 30))
        RigaFattura.objects.create(fattura=f, contratto="K1", **VALORI)
        _righe, riepilogo = services.riconcilia("2026-Q2")
        self.assertEqual(riepilogo["letture_mancanti"], 0)
        self.assertEqual(riepilogo["anomalie"], 0)


class RobustezzaTests(TestCase):
    def setUp(self):
        self.m = Macchina.objects.create(reparto="QA", matricola="SYN-R1", host="192.0.2.60")

    def test_contatore_fuori_scala_o_negativo_scartato(self):
        for valore in (-1, 2_147_483_648, "12"):
            with self.subTest(valore=valore), self.assertRaisesMessage(SNMPError, "non valido"):
                verifica_lettura_mfc(self.m, {**VALORI, "a4_bn": valore})

    def test_trimestre_lettura_snmp_chiusura_nei_primi_giorni(self):
        self.assertEqual(services.trimestre_lettura_snmp(date(2026, 10, 3)), "2026-Q3")
        self.assertEqual(services.trimestre_lettura_snmp(date(2027, 1, 7)), "2026-Q4")
        self.assertEqual(services.trimestre_lettura_snmp(date(2026, 10, 8)), "2026-Q4")
        self.assertEqual(services.trimestre_lettura_snmp(date(2026, 11, 2)), "2026-Q4")

    @mock.patch("contatori.services.interroga_macchina")
    def test_leggi_mfc_ora_inizio_trimestre_salva_la_chiusura(self, interroga):
        interroga.return_value = dict(VALORI)
        esito = services.salva_letture_trimestrali_snmp(date(2026, 10, 3))
        self.assertEqual(esito["trimestre"], "2026-Q3")
        lettura = LetturaContatori.objects.get()
        self.assertEqual((lettura.trimestre, lettura.data), ("2026-Q3", date(2026, 10, 3)))

    def test_manuale_salvata_durante_la_lettura_non_sovrascritta(self):
        def lettura_lenta(macchina):
            LetturaContatori.objects.create(macchina=macchina, trimestre="2026-Q4", data=date(2026, 11, 2),
                                            fonte=LetturaContatori.Fonte.MANUALE, **VALORI)
            return {**VALORI, "a4_bn": 2000}

        with mock.patch("contatori.services.interroga_macchina", side_effect=lettura_lenta):
            esito = services.salva_letture_trimestrali_snmp(date(2026, 11, 3))
        self.assertEqual((esito["lette"], esito["manuali"]), (0, ["QA"]))
        self.assertEqual(LetturaContatori.objects.get().a4_bn, 1000)


class SeedDemoTests(TestCase):
    def test_non_cancella_dati_esistenti_senza_conferma(self):
        from django.core.management import CommandError, call_command
        Macchina.objects.create(reparto="QA", matricola="SYN-KEEP")
        with self.assertRaisesMessage(CommandError, "--sostituisci"):
            call_command("seed_demo")
        self.assertTrue(Macchina.objects.filter(matricola="SYN-KEEP").exists())
