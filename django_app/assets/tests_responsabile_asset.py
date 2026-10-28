"""Responsabile delle macchine di produzione = caporeparto, salvo persona assegnata. Dati sintetici."""
from __future__ import annotations

from unittest import mock

from django.test import TestCase

from .models import Asset
from .registro_permessi import proprietario_asset
from .services import responsabile_asset

CAPI = {"cn5": (7, "Mario Sintetico")}


class ResponsabileAssetTests(TestCase):
    def _asset(self, **campi):
        dati = {"asset_tag": "SYN-CNC-1", "name": "Fresa sintetica", "asset_type": Asset.TYPE_CNC, "reparto": "CN5"}
        dati.update(campi)
        return Asset(**dati)

    def test_cnc_senza_persona_va_al_caporeparto(self):
        resp = responsabile_asset.responsabile(self._asset(), CAPI)
        self.assertEqual((resp.nome, resp.sotto, resp.da_caporeparto, resp.anagrafica_id),
                         ("Mario Sintetico", "Caporeparto CN5", True, 7))

    def test_assegnata_al_reparto_va_al_caporeparto(self):
        asset = self._asset(reparto="", assignment_to="Reparto CN5", assignment_reparto="CN5")
        self.assertTrue(responsabile_asset.responsabile(asset, CAPI).da_caporeparto)

    def test_persona_assegnata_vince(self):
        asset = self._asset(assignment_to="Luigi Sintetico", assignment_reparto="CN5", assigned_legacy_user_id=3)
        resp = responsabile_asset.responsabile(asset, CAPI)
        self.assertEqual((resp.nome, resp.da_caporeparto), ("Luigi Sintetico", False))
        self.assertEqual(proprietario_asset(asset), 3)

    def test_asset_it_non_prende_il_caporeparto(self):
        self.assertIsNone(responsabile_asset.responsabile(self._asset(asset_type=Asset.TYPE_PC), CAPI))

    def test_reparto_senza_capo(self):
        self.assertIsNone(responsabile_asset.responsabile(self._asset(reparto="CN9"), CAPI))

    def test_proprietario_e_il_caporeparto(self):
        # Capo e co-capi del reparto: un insieme di utenti.
        with mock.patch.object(responsabile_asset, "persone_per_reparto", return_value={"cn5": {7, 8}}):
            from core.legacy_models import AnagraficaDipendente
            with mock.patch.object(AnagraficaDipendente.objects, "filter") as filtro:
                filtro.return_value.values_list.return_value = [42, 43, None]
                self.assertEqual(proprietario_asset(self._asset()), {42, 43})
                filtro.assert_called_once_with(id__in={7, 8})
