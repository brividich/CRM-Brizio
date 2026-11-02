"""«OdL in ritardo»: una sola regola per tutte le pagine."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from assets.maintenance import odl_in_ritardo, q_odl_in_ritardo
from assets.models import Asset, WorkOrder


class OdlInRitardoTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="AST-KPI-RIT", name="Tornio KPI")
        self.now = timezone.now()

    def _odl(self, titolo, *, aperto_giorni, scadenza=None):
        return WorkOrder.objects.create(
            asset=self.asset, title=titolo, opened_at=self.now - timedelta(days=aperto_giorni), due_at=scadenza,
        )

    def test_scaduto_o_vecchio_e_in_ritardo_stessa_regola_su_queryset_e_riga(self):
        with patch("assets.maintenance.get_workorder_overdue_days", return_value=10):
            vecchio = self._odl("vecchio", aperto_giorni=11)
            scaduto = self._odl("scaduto", aperto_giorni=1, scadenza=self.now - timedelta(hours=2))
            fresco = self._odl("fresco", aperto_giorni=2, scadenza=self.now + timedelta(days=3))
            in_ritardo = set(WorkOrder.objects.filter(q_odl_in_ritardo(self.now)).values_list("pk", flat=True))
            self.assertEqual(in_ritardo, {vecchio.pk, scaduto.pk})
            for wo in (vecchio, scaduto, fresco):
                self.assertEqual(odl_in_ritardo(wo, self.now), wo.pk in in_ritardo)
