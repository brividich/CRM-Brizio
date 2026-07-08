from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner


class SuggestionCornerModelTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")

    def _base(self, **kw):
        defaults = dict(
            reparto_provenienza=self.reparto,
            opportunity="Migliorare l'illuminazione del reparto.",
        )
        defaults.update(kw)
        return SuggestionCorner.objects.create(**defaults)

    def test_stato_default_inserita(self):
        s = self._base()
        self.assertEqual(s.stato, "INSERITA")
        self.assertEqual(s.stato_sms, SuggestionCorner.StatoSMS.DA_GESTIRE)
        self.assertTrue(s.da_portale)
        self.assertFalse(s.anonima)

    def test_scaduto_do_true_quando_limite_passato_e_non_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_esecuzione=ieri, do_eseguito=False)
        self.assertTrue(s.scaduto_do)

    def test_scaduto_do_false_se_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_esecuzione=ieri, do_eseguito=True)
        self.assertFalse(s.scaduto_do)

    def test_scaduto_do_false_senza_limite(self):
        s = self._base()
        self.assertFalse(s.scaduto_do)

    def test_scaduto_check_true_quando_limite_passato_e_non_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_controllo=ieri, check_eseguito=False)
        self.assertTrue(s.scaduto_check)
