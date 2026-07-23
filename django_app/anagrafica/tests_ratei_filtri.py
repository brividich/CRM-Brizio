"""1.10 — Ratei: filtri con operatori di confronto (`<`, `>`, `=`) sui saldi."""
from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase, TestCase

from .models import SaldoCedolino
from .ratei_alert import saldo_filter_q


class SaldoFilterQTests(SimpleTestCase):
    def test_operatore_maggiore(self):
        q = saldo_filter_q("ferie_residui", "gt", "40")
        self.assertIn("ferie_residui__gt", str(q))

    def test_operatore_minore(self):
        q = saldo_filter_q("rol_residui", "lt", "5")
        self.assertIn("rol_residui__lt", str(q))

    def test_operatore_uguale(self):
        q = saldo_filter_q("ex_fest_residui", "eq", "0")
        self.assertIn("ex_fest_residui", str(q))
        self.assertNotIn("__lt", str(q))
        self.assertNotIn("__gt", str(q))

    def test_campo_fuori_whitelist_none(self):
        self.assertIsNone(saldo_filter_q("importazione_id", "gt", "1"))

    def test_operatore_non_valido_none(self):
        self.assertIsNone(saldo_filter_q("ferie_residui", "like", "1"))

    def test_valore_non_numerico_none(self):
        self.assertIsNone(saldo_filter_q("ferie_residui", "gt", "abc"))

    def test_valore_con_virgola(self):
        q = saldo_filter_q("ferie_residui", "gt", "1,5")
        self.assertIsNotNone(q)


class SaldoFilterQuerysetTests(TestCase):
    def test_filtro_applicato_al_queryset(self):
        SaldoCedolino.objects.create(
            tax_code="AAA", data_competenza=date(2026, 5, 31), ferie_residui=10
        )
        SaldoCedolino.objects.create(
            tax_code="BBB", data_competenza=date(2026, 5, 31), ferie_residui=50
        )
        q = saldo_filter_q("ferie_residui", "gt", "40")
        self.assertEqual(SaldoCedolino.objects.filter(q).count(), 1)
        q2 = saldo_filter_q("ferie_residui", "eq", "10")
        self.assertEqual(SaldoCedolino.objects.filter(q2).count(), 1)
