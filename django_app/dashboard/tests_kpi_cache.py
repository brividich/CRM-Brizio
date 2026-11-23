"""Cache per persona dei contatori dei riquadri della home."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from dashboard import views_home_portale as home


def _request(user_pk: int):
    return SimpleNamespace(user=SimpleNamespace(pk=user_pk))


class TileKpiCacheTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @override_settings(HOME_KPI_CACHE_SECONDS=90)
    def test_seconda_apertura_non_ricalcola(self):
        legacy = SimpleNamespace(id=7)
        with mock.patch.object(home, "_tile_kpi_counts", return_value={"ticket": [{"value": 3}]}) as calcolo:
            primo = home._tile_kpi_counts_cached(legacy, False, _request(1))
            secondo = home._tile_kpi_counts_cached(legacy, False, _request(1))
        self.assertEqual(primo, secondo)
        self.assertEqual(calcolo.call_count, 1)

    @override_settings(HOME_KPI_CACHE_SECONDS=90)
    def test_persone_e_impersonazione_separate(self):
        with mock.patch.object(home, "_tile_kpi_counts", side_effect=[{"a": 1}, {"b": 2}, {"c": 3}]) as calcolo:
            home._tile_kpi_counts_cached(SimpleNamespace(id=7), False, _request(1))
            home._tile_kpi_counts_cached(SimpleNamespace(id=8), False, _request(1))  # impersona un altro
            altro = home._tile_kpi_counts_cached(SimpleNamespace(id=7), False, _request(2))
        self.assertEqual(calcolo.call_count, 3)
        self.assertEqual(altro, {"c": 3})

    @override_settings(HOME_KPI_CACHE_SECONDS=0)
    def test_zero_spegne_la_cache(self):
        with mock.patch.object(home, "_tile_kpi_counts", return_value={}) as calcolo:
            home._tile_kpi_counts_cached(SimpleNamespace(id=7), False, _request(1))
            home._tile_kpi_counts_cached(SimpleNamespace(id=7), False, _request(1))
        self.assertEqual(calcolo.call_count, 2)
