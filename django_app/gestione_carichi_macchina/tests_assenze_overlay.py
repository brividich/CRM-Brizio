"""Test overlay "abilitati assenti" (Skill Matrix MOD.187 × assenze) nel Gantt.

- logica di aggregazione e severità: pura, senza DB;
- ``assenze_overlay_for_assets``: pool reale (AbilitazioneMacchina) + assenze mockate;
- vista Gantt: il marker ``.gabs`` e il riepilogo compaiono quando c'è un'assenza.
"""
from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from assets.models import Asset

from . import integrations
from .models import Macchina


class SeveritaTests(SimpleTestCase):
    def test_soglie(self):
        self.assertEqual(integrations._severita_assenze(0, 5), "bassa")
        self.assertEqual(integrations._severita_assenze(1, 5), "bassa")  # 0.2
        self.assertEqual(integrations._severita_assenze(2, 5), "media")  # n==2
        self.assertEqual(integrations._severita_assenze(3, 5), "alta")   # n>=3
        self.assertEqual(integrations._severita_assenze(1, 1), "alta")   # 100% del pool
        self.assertEqual(integrations._severita_assenze(2, 3), "alta")   # 2/3 del pool
        self.assertEqual(integrations._severita_assenze(2, 10), "media")  # n==2, quota bassa


class AggregaAssenzeGiorniTests(SimpleTestCase):
    def test_conteggio_per_giorno_e_nomi(self):
        giorni = [date(2026, 6, 23), date(2026, 6, 24), date(2026, 6, 25), date(2026, 6, 26)]
        pool = {100: [42, 43]}
        assenze = {
            42: [{"data_inizio": date(2026, 6, 24), "data_fine": date(2026, 6, 25),
                  "tipo": "Ferie", "nome": "Rossi Mario"}],
            43: [{"data_inizio": date(2026, 6, 25), "data_fine": date(2026, 6, 25),
                  "tipo": "Permesso", "nome": "Bianchi Luca"}],
        }
        out = integrations._aggrega_assenze_giorni(pool, assenze, giorni)
        giorni_info = out[100]
        self.assertEqual(giorni_info[date(2026, 6, 24)]["n"], 1)
        self.assertEqual(giorni_info[date(2026, 6, 24)]["tot"], 2)
        self.assertEqual(giorni_info[date(2026, 6, 24)]["sev"], "media")  # 1/2
        self.assertEqual(giorni_info[date(2026, 6, 25)]["n"], 2)
        self.assertEqual(giorni_info[date(2026, 6, 25)]["sev"], "alta")   # 2/2
        nomi_25 = {n for n, _t in giorni_info[date(2026, 6, 25)]["nomi"]}
        self.assertEqual(nomi_25, {"Rossi Mario", "Bianchi Luca"})

    def test_operatore_non_doppio_se_assenze_sovrapposte(self):
        giorni = [date(2026, 6, 24)]
        pool = {100: [42]}
        assenze = {42: [
            {"data_inizio": date(2026, 6, 24), "data_fine": date(2026, 6, 24), "tipo": "A", "nome": "X"},
            {"data_inizio": date(2026, 6, 23), "data_fine": date(2026, 6, 25), "tipo": "B", "nome": "X"},
        ]}
        out = integrations._aggrega_assenze_giorni(pool, assenze, giorni)
        self.assertEqual(out[100][date(2026, 6, 24)]["n"], 1)

    def test_input_vuoti(self):
        self.assertEqual(integrations._aggrega_assenze_giorni({}, {}, []), {})


class OverlayForAssetsTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(
            asset_tag="CNC-OVL-1", name="Macchina overlay", asset_type=Asset.TYPE_WORK_MACHINE
        )

    def _abilita(self, legacy_id, livello="U"):
        from anagrafica.models import AbilitazioneMacchina
        return AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=legacy_id, asset=self.asset, livello=livello,
        )

    def test_overlay_incrocia_pool_e_assenze(self):
        self._abilita(42)  # Autonomo → nel pool operativo di default
        giorni = [date(2026, 6, 23), date(2026, 6, 24)]
        fake = {42: [{"data_inizio": date(2026, 6, 24), "data_fine": date(2026, 6, 24),
                      "tipo": "Ferie", "nome": "Rossi Mario"}]}
        with mock.patch("assenze.availability.assenze_per_anagrafica", return_value=fake):
            out = integrations.assenze_overlay_for_assets([self.asset.id], giorni)
        self.assertIn(self.asset.id, out)
        self.assertEqual(out[self.asset.id][date(2026, 6, 24)]["n"], 1)

    def test_vuoto_senza_baseline_skillmatrix(self):
        # Nessuna AbilitazioneMacchina → pool vuoto → overlay vuoto (additivo).
        giorni = [date(2026, 6, 23), date(2026, 6, 24)]
        with mock.patch("assenze.availability.assenze_per_anagrafica", return_value={}) as m:
            out = integrations.assenze_overlay_for_assets([self.asset.id], giorni)
        self.assertEqual(out, {})
        m.assert_not_called()  # short-circuit: niente pool → niente query assenze


class GanttOverlayViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("op2", "op2@example.com", "x")
        self.asset = Asset.objects.create(
            asset_tag="CNC-OVL-2", name="DM5 overlay", asset_type=Asset.TYPE_WORK_MACHINE
        )
        self.m = Macchina.objects.create(asset=self.asset, categoria=Macchina.CAT_5AXIS)
        from anagrafica.models import AbilitazioneMacchina
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=42, asset=self.asset, livello="U",
        )

    def test_marker_e_riepilogo_in_pagina(self):
        self.client.force_login(self.user)
        fake = {42: [{"data_inizio": date(2026, 6, 24), "data_fine": date(2026, 6, 24),
                      "tipo": "Ferie", "nome": "Rossi Mario"}]}
        with mock.patch("assenze.availability.assenze_per_anagrafica", return_value=fake):
            r = self.client.get(reverse("gestione_carichi_macchina:gantt"),
                                {"start": "2026-06-22", "giorni": 7})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="gabs gabs-alta')  # 1/1 del pool → severità alta
        self.assertContains(r, "Rossi Mario (Ferie)")
        self.assertContains(r, "abilitati assenti")

    def test_nessun_marker_senza_assenze(self):
        self.client.force_login(self.user)
        with mock.patch("assenze.availability.assenze_per_anagrafica", return_value={}):
            r = self.client.get(reverse("gestione_carichi_macchina:gantt"),
                                {"start": "2026-06-22", "giorni": 7})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'class="gabs')
