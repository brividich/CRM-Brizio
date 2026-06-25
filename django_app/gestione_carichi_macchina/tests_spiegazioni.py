"""Test dello strato LLM di spiegazione (Fase 5): fail-safe e riuso del gateway."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .spiegazioni import contesto_suggerimento_macchina, spiega


class SpiegaTest(SimpleTestCase):
    @override_settings(OLLAMA_CHAT_ENABLED=False)
    def test_disabilitato_ritorna_none(self):
        self.assertIsNone(spiega("prompt", "contesto"))

    @override_settings(OLLAMA_CHAT_ENABLED=True)
    def test_usa_gateway_quando_attivo(self):
        fake = SimpleNamespace(content="Consiglio: DM3 (62%).")
        with patch("ai_assistant.services.chat_with_ollama", return_value=fake) as m:
            out = spiega("prompt", "contesto", timeout=5)
        self.assertEqual(out, "Consiglio: DM3 (62%).")
        m.assert_called_once()

    @override_settings(OLLAMA_CHAT_ENABLED=True)
    def test_errore_gateway_ritorna_none(self):
        with patch("ai_assistant.services.chat_with_ollama", side_effect=RuntimeError("giu")):
            self.assertIsNone(spiega("prompt", "contesto"))

    def test_pulisce_marker_fonte(self):
        from .spiegazioni import _pulisci

        self.assertEqual(
            _pulisci("Consiglio: DM5 (26%). Tool:* Famiglia pezzo: gimbal."),
            "Consiglio: DM5 (26%).",
        )
        self.assertEqual(_pulisci("Solo testo."), "Solo testo.")

    def test_contesto_cita_i_numeri(self):
        prompt, ctx = contesto_suggerimento_macchina(
            "gimbal", [{"codice": "DM3", "prob": 0.62, "occorrenze": 7, "macchina_id": 1}]
        )
        self.assertIn("gimbal", ctx)
        self.assertIn("62%", ctx)
        self.assertIn("DM3", ctx)
        self.assertIn("gimbal", prompt)
