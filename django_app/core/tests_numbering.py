"""Servizio di numerazione condiviso (§5.3): funzioni pure."""
from __future__ import annotations

from django.test import SimpleTestCase

from core.numbering import (
    max_numeric,
    next_code,
    next_numeric,
    next_prefixed,
    next_suffix,
)


class NumberingTests(SimpleTestCase):
    def test_max_numeric_ignora_alfanumerici(self):
        self.assertEqual(max_numeric(["1", "007", "ABC", "12", "", None]), 12)
        self.assertEqual(max_numeric([]), 0)

    def test_next_numeric(self):
        self.assertEqual(next_numeric(["5", "10"]), 11)
        self.assertEqual(next_numeric([]), 1)

    def test_next_suffix(self):
        self.assertEqual(next_suffix(["SIC-1", "SIC-3", "ALTRO-9"], "SIC"), 4)
        self.assertEqual(next_suffix([], "SIC"), 1)
        # separatore configurabile (retro-compatibile col default "-")
        self.assertEqual(next_suffix(["Int.5", "Int.12"], "Int", sep="."), 13)

    def test_next_code(self):
        self.assertEqual(next_code(["SIC-1"], "SIC"), "SIC-2")
        self.assertEqual(next_code([], "QUAL"), "QUAL-1")
        # separatore e padding configurabili
        self.assertEqual(next_code(["Int.001"], "Int", sep=".", pad=3), "Int.002")


class NextPrefixedTests(SimpleTestCase):
    """``next_prefixed`` per la convenzione asset ``Int.NNN`` (punto: bottone
    'Assegna progressivo' prefix-aware)."""

    def test_lista_vuota_parte_da_uno(self):
        self.assertEqual(next_prefixed([], prefix="Int", sep=".", pad=3), "Int.001")

    def test_conta_le_code_numeriche_dei_codici_prefissati(self):
        self.assertEqual(
            next_prefixed(["Int.002", "Int.262", "Int.055"], prefix="Int", sep=".", pad=3),
            "Int.263",
        )

    def test_ignora_code_non_numeriche(self):
        # 'Int.188A' e 'Int.55/B' non hanno coda interamente numerica: si ignorano
        self.assertEqual(
            next_prefixed(["Int.262", "Int.188A", "Int.55/B"], prefix="Int", sep=".", pad=3),
            "Int.263",
        )

    def test_assorbe_i_valori_nudi_numerici_legacy(self):
        # I due anomali '196'/'197' (senza prefisso) entrano nella stessa sequenza:
        # con Int.262 presente restano sotto il massimo -> next resta Int.263
        self.assertEqual(
            next_prefixed(["196", "197", "Int.262"], prefix="Int", sep=".", pad=3),
            "Int.263",
        )
        # ...ma se un valore nudo supera il massimo prefissato, vince lui (no collisioni)
        self.assertEqual(
            next_prefixed(["300", "Int.262"], prefix="Int", sep=".", pad=3),
            "Int.301",
        )

    def test_prefisso_emesso_sempre_anche_da_soli_valori_nudi(self):
        self.assertEqual(
            next_prefixed(["196", "197", "", None], prefix="Int", sep=".", pad=3),
            "Int.198",
        )
