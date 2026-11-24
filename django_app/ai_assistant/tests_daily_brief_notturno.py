"""Brief del giorno preparato all'alba per chi lo usa."""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from ai_assistant import daily_brief_notturno as notturno
from ai_assistant import views


class PregeneraTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _persone(self, *ids):
        return [SimpleNamespace(pk=i) for i in ids]

    def test_prepara_e_mette_nella_cache_della_pagina(self):
        dati = {"message": "ciao", "model": "m", "generated_at": "06:10", "sources": []}
        with mock.patch.object(notturno, "persone_recenti", return_value=self._persone(7, 8)), \
                mock.patch.object(notturno, "_richiesta_per", side_effect=lambda u: u), \
                mock.patch.object(views, "genera_daily_brief", return_value=(dati, {})) as genera:
            esito = notturno.pregenera()
        self.assertEqual(esito["preparati"], 2)
        self.assertEqual(genera.call_count, 2)
        self.assertEqual(cache.get(views.daily_brief_cache_key(7)), dati)

    def test_non_rifa_quelli_gia_pronti_e_un_errore_non_ferma_gli_altri(self):
        cache.set(views.daily_brief_cache_key(7), {"message": "già"}, 60)
        dati = {"message": "ciao", "model": "", "generated_at": "06:10", "sources": []}
        with mock.patch.object(notturno, "persone_recenti", return_value=self._persone(7, 8, 9)), \
                mock.patch.object(notturno, "_richiesta_per", side_effect=lambda u: u), \
                mock.patch.object(views, "genera_daily_brief", side_effect=[RuntimeError("giù"), (dati, {})]):
            esito = notturno.pregenera()
        self.assertEqual((esito["gia_pronti"], esito["errori"], esito["preparati"]), (1, 1, 1))
        self.assertEqual(cache.get(views.daily_brief_cache_key(9)), dati)

    @override_settings(OLLAMA_DAILY_BRIEF_ENABLED=False)
    def test_brief_spento_non_fa_niente(self):
        with mock.patch.object(notturno, "persone_recenti", side_effect=AssertionError("letto")):
            self.assertIn("saltato", notturno.pregenera())
