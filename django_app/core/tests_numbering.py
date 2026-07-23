"""Servizio di numerazione condiviso (§5.3): funzioni pure."""
from __future__ import annotations

from django.test import SimpleTestCase

from core.numbering import max_numeric, next_code, next_numeric, next_suffix


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

    def test_next_code(self):
        self.assertEqual(next_code(["SIC-1"], "SIC"), "SIC-2")
        self.assertEqual(next_code([], "QUAL"), "QUAL-1")
