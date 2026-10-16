"""Comando proponi_mansioni_rischio: la mansione di rischio delle mansioni lavorative
ricavata dalle persone in lista. Dati sintetici."""
from __future__ import annotations

import io

from django.core.management import call_command
from django.test import TestCase

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente

from .models import CompetenzaSkm, Mansione
from .services import mansionario_struttura as svc
from .tests import _ensure_anagrafica_table


class ProponiMansioniRischioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.mu = Mansione.objects.create(nome="ADDETTO MACCHINE UTENSILI P7")
        self.mag = Mansione.objects.create(nome="ADDETTO MAGAZZINO P7")
        self.tornio = CompetenzaSkm.objects.create(
            competenza_key="P7-TC", display="Tornio P7", tipo=CompetenzaSkm.TIPO_MACCHINA,
            asset=Asset.objects.create(name="Tornio P7", asset_tag="P7-TC", reparto="TORNI"))
        self.pari = CompetenzaSkm.objects.create(
            competenza_key="P7-PARI", display="Pari P7", tipo=CompetenzaSkm.TIPO_MACCHINA,
            asset=Asset.objects.create(name="Pari P7", asset_tag="P7-PA", reparto="TORNI"))
        self.vuota = CompetenzaSkm.objects.create(
            competenza_key="P7-VUOTA", display="Vuota P7", tipo=CompetenzaSkm.TIPO_MACCHINA,
            asset=Asset.objects.create(name="Vuota P7", asset_tag="P7-VU", reparto="TORNI"))
        mansioni = ["ADDETTO MACCHINE UTENSILI P7", "addetto macchine utensili p7", "ADDETTO MAGAZZINO P7", ""]
        self.persone = [AnagraficaDipendente.objects.create(nome=f"N{i}", cognome="PROPOSTA",
                                                            aliasusername=f"proposta.{i}", mansione=m).pk
                        for i, m in enumerate(mansioni)]
        for lid in self.persone:
            svc.assegna(self.tornio, legacy_anagrafica_id=lid, livello="U")
        svc.assegna(self.pari, legacy_anagrafica_id=self.persone[0], livello="U")
        svc.assegna(self.pari, legacy_anagrafica_id=self.persone[2], livello="U")

    def _cmd(self, *args):
        out = io.StringIO()
        call_command("proponi_mansioni_rischio", *args, stdout=out)
        return out.getvalue()

    def test_prova_non_scrive_e_spiega(self):
        out = self._cmd()
        self.assertIn("[PROPOSTA] Tornio P7 · TORNI → ADDETTO MACCHINE UTENSILI P7 (67% di 3; "
                      "2 in lista con altra o nessuna mansione di rischio)", out)
        self.assertIn("[PARI] Pari P7", out)
        self.assertIn("[NESSUNO_IN_LISTA] Vuota P7", out)
        self.assertNotIn("PROPOSTA.", out)  # nessun nominativo nell'output
        self.assertFalse(self.tornio.mansioni_rischio.exists())

    def test_commit_collega_solo_le_proposte(self):
        self._cmd("--commit")
        self.assertEqual(list(self.tornio.mansioni_rischio.all()), [self.mu])
        self.assertFalse(self.pari.mansioni_rischio.exists())
        self.assertIn("[GIA_COLLEGATA]", self._cmd("--anche-collegate"))

    def test_soglia(self):
        self.assertIn("[SOTTO_SOGLIA] Tornio P7", self._cmd("--soglia", "70"))

    def test_mansione_gia_collegata_non_toccata(self):
        self.tornio.mansioni_rischio.add(self.mag)
        self._cmd("--commit")
        self.assertEqual(list(self.tornio.mansioni_rischio.all()), [self.mag])
