"""Rinnovo dalla scadenza teorica e permesso «admin_assets» di Accessi. Dati sintetici."""

from __future__ import annotations

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from assets.models import Asset, AssetAdministrativeDeadline
from assets.views._helpers import _can_admin_assets

User = get_user_model()


class RinnovoTeoricoTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="DEC01", name="Muletto")

    def _deadline(self, due):
        return AssetAdministrativeDeadline.objects.create(
            asset=self.asset, title="Polizza", due_date=due, recurrence_months=12,
        )

    def test_fatta_prima_resta_alla_data_teorica(self):
        self.assertEqual(self._deadline(date(2026, 12, 31)).next_due_after(date(2026, 12, 15)), date(2027, 12, 31))

    def test_fatta_dopo_resta_alla_data_teorica(self):
        self.assertEqual(self._deadline(date(2026, 12, 31)).next_due_after(date(2027, 1, 10)), date(2027, 12, 31))

    def test_molto_in_ritardo_salta_alla_prima_data_non_passata(self):
        self.assertEqual(self._deadline(date(2024, 6, 30)).next_due_after(date(2026, 3, 1)), date(2026, 6, 30))

    def test_senza_periodicita_nessun_rinnovo(self):
        deadline = AssetAdministrativeDeadline.objects.create(asset=self.asset, title="Unica", due_date=date(2026, 1, 1))
        self.assertIsNone(deadline.next_due_after(date(2026, 1, 1)))


class PermessoAdminAssetsTests(TestCase):
    def _request(self):
        request = RequestFactory().get("/assets/")
        request.user = User.objects.create_user(username="dec-utente", password="x")
        request.session = {}
        return request

    def test_permesso_di_accessi_basta(self):
        request = self._request()
        with mock.patch("assets.views._helpers._is_assets_admin", return_value=False), \
                mock.patch("assets.views._helpers.user_can_modulo_action", return_value=True) as acl:
            self.assertTrue(_can_admin_assets(request))
        acl.assert_called_with(request, "assets", "admin_assets")

    def test_senza_permesso_negato(self):
        request = self._request()
        with mock.patch("assets.views._helpers._is_assets_admin", return_value=False), \
                mock.patch("assets.views._helpers.user_can_modulo_action", return_value=False):
            self.assertFalse(_can_admin_assets(request))
