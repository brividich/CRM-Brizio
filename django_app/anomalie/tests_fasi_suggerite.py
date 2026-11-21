"""Fasi proposte in «Fase del controllo»: OP, Configurazione, più usate. Dati sintetici."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from anomalie.controllo_views import fasi_suggerite
from anomalie.quality_models import AnomaliaControllo

User = get_user_model()


class FasiSuggeriteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ctl-fasi", password="pass12345")

    def crea(self, op, fase):
        AnomaliaControllo.objects.create(op_id=op, fase=fase, operatore=self.user)

    def test_ordine_op_poi_configurate_poi_piu_usate_senza_doppioni(self):
        self.crea("OP/2026/0001", "Visivo  finale")
        self.crea("OP/2026/0001", "collaudo FINALE")
        self.crea("OP/2026/0002", "Controllo dimensionale")
        self.crea("OP/2026/0003", "controllo dimensionale")
        self.crea("OP/2026/0004", "Una tantum")  # usata una volta sola: non proposta
        with patch("anomalie.views._load_anomalie_lists",
                   return_value={"fasi_controllo": ["Accettazione materiale", "Collaudo finale", "Visivo finale"]}):
            fasi = fasi_suggerite("op/2026/0001")
        self.assertEqual(fasi, ["collaudo FINALE", "Visivo finale", "Accettazione materiale", "controllo dimensionale"])

    def test_configurazione_vuota_restano_op_e_piu_usate(self):
        self.crea("OP/2026/0009", "Collaudo finale")
        with patch("anomalie.views._load_anomalie_lists", return_value={"fasi_controllo": []}):
            self.assertEqual(fasi_suggerite("OP/2026/0009"), ["Collaudo finale"])

    def test_elenco_predefinito_nella_configurazione(self):
        from anomalie.views import ANOMALIE_LIST_DEFAULTS, ANOMALIE_LIST_KEYS

        self.assertIn("fasi_controllo", ANOMALIE_LIST_KEYS)
        self.assertIn("Collaudo finale", ANOMALIE_LIST_DEFAULTS["fasi_controllo"])
