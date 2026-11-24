"""Audit P15: il limite di richieste AI contemporanee vale per tutto il portale."""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from ai_assistant import services
from ai_assistant.services import OllamaChatError, _acquire_ai_slot


@override_settings(OLLAMA_MAX_CONCURRENT_REQUESTS=2)
class LimiteCondivisoTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_oltre_il_limite_assistente_occupato(self):
        primo, secondo = _acquire_ai_slot(), _acquire_ai_slot()
        with mock.patch.object(services, "_AI_SLOT_WAIT_SECONDS", 0):
            with self.assertRaises(OllamaChatError):
                _acquire_ai_slot()
        primo.release()
        terzo = _acquire_ai_slot()  # il posto liberato torna disponibile
        secondo.release()
        terzo.release()

    def test_posto_occupato_da_un_altro_processo_conta(self):
        # Un altro processo ha già preso i due posti (chiavi nella cache comune).
        cache.set("ai_assistant_slot_0", "altro-processo", 60)
        cache.set("ai_assistant_slot_1", "altro-processo", 60)
        with mock.patch.object(services, "_AI_SLOT_WAIT_SECONDS", 0):
            with self.assertRaises(OllamaChatError):
                _acquire_ai_slot()

    def test_release_due_volte_non_libera_il_posto_altrui(self):
        posto = _acquire_ai_slot()
        posto.release()
        altro = _acquire_ai_slot()
        posto.release()  # seconda volta: non deve togliere il posto di «altro»
        self.assertTrue(any(cache.get(f"ai_assistant_slot_{i}") for i in range(2)))
        altro.release()
