"""Test helper date lavorative per l'auto-approvazione umanizzata."""
from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from gestione_specifiche.date_utils import festivi_it, next_business_datetime


class FestiviItTest(TestCase):
    def test_pasquetta_2026(self):
        # Pasqua 2026 = 5 aprile → Pasquetta 6 aprile.
        self.assertIn(date(2026, 4, 6), festivi_it(2026))

    def test_pasquetta_2025(self):
        # Pasqua 2025 = 20 aprile → Pasquetta 21 aprile.
        self.assertIn(date(2025, 4, 21), festivi_it(2025))

    def test_fissi_presenti(self):
        f = festivi_it(2026)
        for d in (date(2026, 1, 1), date(2026, 1, 6), date(2026, 4, 25),
                  date(2026, 5, 1), date(2026, 6, 2), date(2026, 8, 15),
                  date(2026, 11, 1), date(2026, 12, 8), date(2026, 12, 25),
                  date(2026, 12, 26)):
            self.assertIn(d, f)


class NextBusinessDatetimeTest(TestCase):
    def _base(self, y, m, d):
        return timezone.make_aware(datetime(y, m, d, 12, 0))

    def test_salta_weekend(self):
        # venerdì 2026-07-03 → +1 = sabato → lunedì 2026-07-06.
        r = next_business_datetime(self._base(2026, 7, 3))
        self.assertEqual(r.date(), date(2026, 7, 6))

    def test_salta_festivo(self):
        # lunedì 2026-01-05 → +1 = martedì 06/01 (Epifania) → mercoledì 2026-01-07.
        r = next_business_datetime(self._base(2026, 1, 5))
        self.assertEqual(r.date(), date(2026, 1, 7))

    def test_ora_in_orario_ufficio(self):
        r = next_business_datetime(self._base(2026, 7, 3))
        self.assertGreaterEqual(r.hour, 9)
        self.assertLess(r.hour, 17)

    def test_risultato_aware(self):
        r = next_business_datetime(self._base(2026, 7, 3))
        self.assertIsNotNone(r.tzinfo)
