"""Storico conversazioni dell'assistente: salvataggio, isolamento per utente, conservazione."""
from __future__ import annotations

import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import conversazioni
from .models import AiConversation, AiConversationMessage
from .services import OllamaChatResult


class _Base(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        # Superuser: la middleware ACL li lascia passare (come negli altri test della chat).
        # L'isolamento non dipende dal ruolo: le API filtrano sempre per request.user.
        User = get_user_model()
        self.user = User.objects.create_superuser("conv.utente", email="conv.utente@example.local", password="x")
        self.altro = User.objects.create_superuser("conv.altro", email="conv.altro@example.local", password="x")
        self.client.force_login(self.user)

    def _chat(self, message, risposta="Risposta sintetica.", **extra):
        payload = {"message": message, **extra}
        with patch("ai_assistant.views.build_runtime_context") as ctx, patch(
            "ai_assistant.views.chat_with_ollama"
        ) as chat:
            ctx.return_value.text = ""
            ctx.return_value.sources = ()
            ctx.return_value.audit = {}
            chat.return_value = OllamaChatResult(
                content=risposta, model="qwen-test", done=True, sources=("guida:timbri#3 > Guida",)
            )
            response = self.client.post(
                reverse("ai_assistant:api_chat"),
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        return response, chat


class ConversazioniChatTests(_Base):
    def test_la_prima_risposta_crea_la_conversazione(self):
        response, _ = self._chat("Come inserisco un nuovo timbro?")
        self.assertEqual(response.status_code, 200)
        conv_id = response.json()["conversation_id"]
        conv = AiConversation.objects.get(pk=conv_id)
        self.assertEqual(conv.utente, self.user)
        self.assertEqual(conv.titolo, "Come inserisco un nuovo timbro?")
        messaggi = list(conv.messaggi.values_list("ruolo", "contenuto"))
        self.assertEqual(messaggi, [("user", "Come inserisco un nuovo timbro?"), ("assistant", "Risposta sintetica.")])
        self.assertEqual(conv.messaggi.last().fonti, ["guida:timbri#3 > Guida"])

    def test_storico_al_modello_letto_dal_db_e_non_dal_browser(self):
        conv_id = self._chat("Prima domanda")[0].json()["conversation_id"]
        response, chat = self._chat(
            "Seconda domanda",
            conversation_id=conv_id,
            history=[{"role": "assistant", "content": "storico manomesso dal browser"}],
        )
        self.assertEqual(response.json()["conversation_id"], conv_id)
        self.assertEqual(
            chat.call_args.kwargs["history"],
            [{"role": "user", "content": "Prima domanda"}, {"role": "assistant", "content": "Risposta sintetica."}],
        )
        self.assertEqual(AiConversationMessage.objects.filter(conversazione_id=conv_id).count(), 4)

    def test_rigenera_sostituisce_l_ultima_risposta(self):
        conv_id = self._chat("Domanda")[0].json()["conversation_id"]
        _, chat = self._chat("Domanda", risposta="Risposta nuova.", conversation_id=conv_id, regenerate=True)
        self.assertEqual(chat.call_args.kwargs["history"], [])
        messaggi = list(AiConversationMessage.objects.filter(conversazione_id=conv_id).values_list("ruolo", "contenuto"))
        self.assertEqual(messaggi, [("user", "Domanda"), ("assistant", "Risposta nuova.")])

    def test_conversazione_di_un_altro_non_viene_usata(self):
        altrui = AiConversation.objects.create(utente=self.altro, titolo="Privata")
        response, chat = self._chat("Ciao", conversation_id=altrui.pk)
        self.assertNotEqual(response.json()["conversation_id"], altrui.pk)
        self.assertEqual(altrui.messaggi.count(), 0)
        self.assertIsNone(chat.call_args.kwargs["history"])

    def test_stream_salva_il_turno(self):
        with patch("ai_assistant.views.build_runtime_context") as ctx, patch(
            "ai_assistant.views.open_ollama_stream"
        ) as mocked_open, patch("ai_assistant.views.iter_ollama_stream") as mocked_iter:
            ctx.return_value.text = ""
            ctx.return_value.sources = ()
            ctx.return_value.audit = {}
            mocked_open.return_value = (object(), {"model": "qwen-test", "provider": "ollama", "sources": ()})
            mocked_iter.return_value = iter(["Ciao", " mondo"])
            response = self.client.post(
                reverse("ai_assistant:api_chat_stream"),
                data='{"message":"ciao"}',
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            body = b"".join(response.streaming_content).decode("utf-8")
        done = [json.loads(line) for line in body.splitlines() if line.strip()][-1]
        conv = AiConversation.objects.get(pk=done["conversation_id"])
        self.assertEqual(conv.messaggi.last().contenuto, "Ciao mondo")

    @override_settings(AI_CHAT_HISTORY_ENABLED=False)
    def test_storico_spento_non_salva(self):
        response, _ = self._chat("Ciao")
        self.assertIsNone(response.json()["conversation_id"])
        self.assertFalse(AiConversation.objects.exists())
        self.assertEqual(self.client.get(reverse("ai_assistant:api_conversazioni")).status_code, 404)
        page = self.client.get(reverse("ai_assistant:chat"))
        self.assertNotContains(page, "ai-config ai-history")


class ConversazioniApiTests(_Base):
    def setUp(self):
        super().setUp()
        self.mia = AiConversation.objects.create(utente=self.user, titolo="Mia")
        AiConversationMessage.objects.create(conversazione=self.mia, ruolo="user", contenuto="D")
        AiConversationMessage.objects.create(conversazione=self.mia, ruolo="assistant", contenuto="R", fonti=["x"])
        self.altrui = AiConversation.objects.create(utente=self.altro, titolo="Altrui")

    def test_elenco_solo_le_proprie(self):
        data = self.client.get(reverse("ai_assistant:api_conversazioni")).json()
        self.assertEqual([c["id"] for c in data["conversazioni"]], [self.mia.pk])
        self.assertEqual(data["giorni_conservazione"], 90)

    def test_dettaglio(self):
        data = self.client.get(reverse("ai_assistant:api_conversazione", args=[self.mia.pk])).json()
        self.assertEqual([m["role"] for m in data["messaggi"]], ["user", "assistant"])
        self.assertEqual(data["messaggi"][1]["sources"], ["x"])

    def test_conversazione_altrui_404_su_lettura_e_cancellazione(self):
        self.assertEqual(self.client.get(reverse("ai_assistant:api_conversazione", args=[self.altrui.pk])).status_code, 404)
        response = self.client.post(reverse("ai_assistant:api_conversazione_elimina", args=[self.altrui.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(AiConversation.objects.filter(pk=self.altrui.pk).exists())

    def test_elimina_e_elimina_tutte_toccano_solo_le_proprie(self):
        seconda = AiConversation.objects.create(utente=self.user, titolo="Seconda")
        self.assertEqual(self.client.post(reverse("ai_assistant:api_conversazione_elimina", args=[seconda.pk])).status_code, 200)
        self.assertFalse(AiConversation.objects.filter(pk=seconda.pk).exists())
        data = self.client.post(reverse("ai_assistant:api_conversazioni_elimina_tutte")).json()
        self.assertEqual(data["eliminate"], 1)
        self.assertFalse(AiConversation.objects.filter(utente=self.user).exists())
        self.assertTrue(AiConversation.objects.filter(pk=self.altrui.pk).exists())
        self.assertFalse(AiConversationMessage.objects.filter(conversazione__utente=self.user).exists())

    def test_cancellazione_solo_in_post(self):
        response = self.client.get(reverse("ai_assistant:api_conversazione_elimina", args=[self.mia.pk]))
        self.assertEqual(response.status_code, 405)

    def test_route_condivise_nel_middleware_acl(self):
        from core.middleware import _ACL_SHARED_ROUTE_NAMES

        for nome in ("api_conversazioni", "api_conversazione", "api_conversazione_elimina",
                     "api_conversazioni_elimina_tutte", "guida"):
            self.assertIn(f"ai_assistant:{nome}", _ACL_SHARED_ROUTE_NAMES)


class ConservazioneTests(_Base):
    def test_pulisci_scadute_e_comando(self):
        vecchia = AiConversation.objects.create(utente=self.user, titolo="Vecchia")
        AiConversationMessage.objects.create(conversazione=vecchia, ruolo="user", contenuto="D")
        recente = AiConversation.objects.create(utente=self.user, titolo="Recente")
        AiConversation.objects.filter(pk=vecchia.pk).update(updated_at=timezone.now() - timedelta(days=91))
        AiConversation.objects.filter(pk=recente.pk).update(updated_at=timezone.now() - timedelta(days=89))

        self.assertEqual(conversazioni.pulisci_scadute(), 1)
        self.assertFalse(AiConversation.objects.filter(pk=vecchia.pk).exists())
        self.assertTrue(AiConversation.objects.filter(pk=recente.pk).exists())

        out = StringIO()
        call_command("ai_pulisci_conversazioni", "--giorni", "30", stdout=out)
        self.assertIn("Conversazioni cancellate: 1", out.getvalue())
        self.assertFalse(AiConversation.objects.exists())

    def test_task_schedulato(self):
        from ai_assistant.tasks import run_pulisci_conversazioni
        from automazioni.schedules import SCHEDULES

        self.assertIn("ai_pulisci_conversazioni", {s["name"] for s in SCHEDULES})
        self.assertEqual(run_pulisci_conversazioni()["ok"], True)

    def test_un_nuovo_messaggio_rinnova_la_scadenza(self):
        conv = conversazioni.registra_turno(self._request(), conversation_id=None, domanda="D", risposta="R")
        AiConversation.objects.filter(pk=conv.pk).update(updated_at=timezone.now() - timedelta(days=91))
        conversazioni.registra_turno(self._request(), conversation_id=conv.pk, domanda="D2", risposta="R2")
        self.assertEqual(conversazioni.pulisci_scadute(), 0)

    def _request(self):
        from types import SimpleNamespace

        return SimpleNamespace(user=self.user)


class PagineTests(_Base):
    def test_chat_mostra_storico_e_link_guida(self):
        page = self.client.get(reverse("ai_assistant:chat"))
        self.assertContains(page, "Le tue conversazioni")
        self.assertContains(page, reverse("ai_assistant:guida"))
        self.assertNotContains(page, "{#")

    def test_guida(self):
        page = self.client.get(reverse("ai_assistant:guida"))
        self.assertContains(page, "Le tue conversazioni")
        self.assertContains(page, "dopo 90 giorni")

    def test_guida_assistente_nel_rag(self):
        from ai_assistant import guide_portale

        slugs = {s.slug for s in guide_portale.sezioni()}
        self.assertIn("assistente-ai", slugs)
