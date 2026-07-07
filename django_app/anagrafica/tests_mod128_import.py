"""MOD.128 MPQ — parser di import (funzioni pure).

Test del parsing delle celle del modulo MOD.128 con **nomi/dati fittizi** che
riproducono i formati reali (scadenze eterogenee, certificati inline, ruoli
posizionali SI/NO, celle organizzative, multi-cliente, multi-reparto). Nessun
dato reale: la PII del PDF entra solo a runtime, mai nei test/commit.
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase

from .models_mpq import ProcessoQualificato
from .services import mod128_import as mi


class ParseScadenzaTests(TestCase):
    def test_illimitata(self):
        r = mi.parse_scadenza("Illimitata a meno di revoca o sospensione")
        self.assertEqual(r["tipo_validita"], ProcessoQualificato.VALIDITA_ILLIMITATA)
        self.assertEqual(r["stato"], ProcessoQualificato.STATO_ATTIVO)

    def test_validita_anni_con_data(self):
        r = mi.parse_scadenza("Validità 3 anni (Scad. 01.06.2028)")
        self.assertEqual(r["tipo_validita"], ProcessoQualificato.VALIDITA_DATA)
        self.assertEqual(r["data_scadenza"], date(2028, 6, 1))
        self.assertEqual(r["durata_mesi"], 36)

    def test_validita_mesi(self):
        r = mi.parse_scadenza("Validità 24 mesi (Scad. 31.05.2027)")
        self.assertEqual(r["data_scadenza"], date(2027, 5, 31))
        self.assertEqual(r["durata_mesi"], 24)

    def test_data_secca(self):
        r = mi.parse_scadenza("31.10.2029")
        self.assertEqual(r["data_scadenza"], date(2029, 10, 31))

    def test_non_piu_rinnovato(self):
        r = mi.parse_scadenza("Non più rinnovato: NON Processo Speciale (mail X 25.05.19)")
        self.assertEqual(r["stato"], ProcessoQualificato.STATO_NON_RINNOVATO)
        self.assertTrue(r["motivo"])
        self.assertIsNone(r["data_scadenza"])

    def test_vuoto(self):
        r = mi.parse_scadenza("")
        self.assertEqual(r["stato"], ProcessoQualificato.STATO_ATTIVO)
        self.assertIsNone(r["data_scadenza"])


class ParsePersonaleTests(TestCase):
    def test_nomi_con_certificati_inline(self):
        persone = mi.split_personale(
            "Rossi Mario (ITA – 938/2 – Scad. 31.10.2028) "
            "Bianchi Luca (ITA – 1063/2 - Scad. 31.01.2031)"
        )
        self.assertEqual(len(persone), 2)
        self.assertEqual(persone[0]["nome"], "Rossi Mario")
        self.assertEqual(persone[0]["certs"][0]["schema"], "ITA")
        self.assertEqual(persone[0]["certs"][0]["numero"], "938/2")
        self.assertEqual(persone[0]["certs"][0]["data_scadenza"], date(2028, 10, 31))
        self.assertEqual(persone[1]["nome"], "Bianchi Luca")

    def test_nomi_separati_da_virgola(self):
        persone = mi.split_personale("Rossi Mario, Bianchi Luca, Verdi Anna.")
        self.assertEqual([p["nome"] for p in persone], ["Rossi Mario", "Bianchi Luca", "Verdi Anna"])

    def test_nomi_separati_da_spazio_a_coppie(self):
        persone = mi.split_personale("Rossi Mario Bianchi Luca Verdi Anna")
        self.assertEqual([p["nome"] for p in persone], ["Rossi Mario", "Bianchi Luca", "Verdi Anna"])


class AllineaRuoliTests(TestCase):
    def test_ruoli_posizionali(self):
        persone = [{"nome": "A A"}, {"nome": "B B"}, {"nome": "C C"}]
        out = mi.allinea_ruoli(persone, addetto="SI SI NO", controllore="NO NO SI", part145="SI NO SI")
        self.assertTrue(out[0]["is_addetto"])
        self.assertFalse(out[2]["is_addetto"])
        self.assertTrue(out[2]["is_controllore"])
        self.assertTrue(out[0]["is_part145"])
        # tutti restano qualificati
        self.assertTrue(all(p["is_qualificato"] for p in out))

    def test_ruoli_assenti_solo_qualificato(self):
        persone = [{"nome": "A A"}]
        out = mi.allinea_ruoli(persone, addetto="", controllore="", part145="")
        self.assertTrue(out[0]["is_qualificato"])
        self.assertFalse(out[0]["is_addetto"])


class OrganizzativoTests(TestCase):
    def test_riferimento_organizzativo(self):
        self.assertTrue(mi.is_organizzativo("Elenco Personale Azienda S.r.l. Rif. MO-ID-009.24"))
        self.assertTrue(mi.is_organizzativo("Attestato di Riconoscimento n° 2026/038"))
        self.assertTrue(mi.is_organizzativo("Rif. Dichiarazione Approvazione LH/1354 del 22.10.2024"))

    def test_nomi_non_organizzativo(self):
        self.assertFalse(mi.is_organizzativo("Rossi Mario Bianchi Luca"))


class ClientiRepartiRegimeTests(TestCase):
    def test_split_clienti_multi(self):
        princ, addiz = mi.split_clienti("NADCAP Leonardo Helicopter GE Avio Piaggio Aerospace")
        self.assertEqual(princ, "NADCAP")
        self.assertIn("Leonardo Helicopter", addiz)
        self.assertIn("GE Avio", addiz)

    def test_split_clienti_singolo(self):
        princ, addiz = mi.split_clienti("Leonardo Helicopter")
        self.assertEqual(princ, "Leonardo Helicopter")
        self.assertEqual(addiz, [])

    def test_split_reparti_multi(self):
        self.assertEqual(mi.split_reparti("Aggiustaggio CND PT"), ["Aggiustaggio", "CND PT"])

    def test_split_reparti_vuoto(self):
        self.assertEqual(mi.split_reparti(""), [])

    def test_infer_regime_part145(self):
        self.assertEqual(
            mi.infer_regime("Leonardo Helicopter", "Riparazione Componenti (Part 145)"),
            ProcessoQualificato.REGIME_PART145,
        )

    def test_infer_regime_nadcap(self):
        self.assertEqual(
            mi.infer_regime("NADCAP", "Ispezione Liquidi Penetranti"),
            ProcessoQualificato.REGIME_NADCAP,
        )
