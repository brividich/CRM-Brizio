"""Fase 4: FAQ suggerite dai 👎 (bozza AI, approvazione admin, scarto)."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import faq_suggerite
from .models import AiChatFeedback, AiKnowledgeEntry
from .services import OllamaChatResult, build_knowledge_context, clear_knowledge_cache


class _Base(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.admin = get_user_model().objects.create_superuser("faq.admin", password="x")

    def _fb(self, prompt, rating="down", correction="", reviewed=False, entry=None):
        return AiChatFeedback.objects.create(
            user=self.admin, prompt=prompt, response="risposta sbagliata", rating=rating,
            correction=correction, is_reviewed=reviewed, knowledge_entry=entry,
        )

    def _request(self):
        from types import SimpleNamespace

        return SimpleNamespace(user=self.admin, path="/admin-portale/ai/")


class GruppiTests(_Base):
    def test_raggruppa_le_domande_simili_e_ignora_up_e_rivisti(self):
        a = self._fb("come inserisco un nuovo timbro nel registro?")
        b = self._fb("come inserisco nuovo timbro registro")
        c = self._fb("quanti giorni di ferie residui ho?")
        self._fb("come inserisco un nuovo timbro?", rating="up")
        self._fb("come inserisco un nuovo timbro?", reviewed=True)

        gruppi = faq_suggerite.gruppi_da_rivedere()
        self.assertEqual([g.numero for g in gruppi], [2, 1])
        self.assertEqual(set(gruppi[0].feedback_ids), {a.pk, b.pk})
        self.assertEqual(gruppi[1].feedback_ids, [c.pk])

    def test_parse_ids(self):
        self.assertEqual(faq_suggerite.parse_ids("3, 5,x,,7"), [3, 5, 7])


class BozzaTests(_Base):
    def test_genera_bozza_spenta_e_toglie_la_bozza_utente_orfana(self):
        bozza_utente = AiKnowledgeEntry.objects.create(question="q", answer="correzione", is_active=False,
                                                       source_label="Feedback chat")
        a = self._fb("come inserisco un nuovo timbro?", correction="Da Registro Timbri, Nuovo record", entry=bozza_utente)
        b = self._fb("come inserisco nuovo timbro")
        with patch("ai_assistant.services.chat_with_ollama") as chat:
            chat.return_value = OllamaChatResult(content="Apri la scheda e premi «Nuovo record».\nFonti: guida timbri",
                                                 model="m", done=True)
            bozza, _ = faq_suggerite.genera_bozza(self._request(), [a.pk, b.pk])

        self.assertIsNotNone(bozza)
        self.assertFalse(bozza.is_active)
        self.assertEqual(bozza.source_label, faq_suggerite.SOURCE_LABEL_BOZZA)
        self.assertEqual(set(bozza.feedback_entries.values_list("pk", flat=True)), {a.pk, b.pk})
        self.assertFalse(AiKnowledgeEntry.objects.filter(pk=bozza_utente.pk).exists())
        kwargs = chat.call_args.kwargs
        self.assertEqual(kwargs["runtime_sources"], ("tool:faq:bozza",))
        self.assertIn("RISPOSTE PROPOSTE DAGLI UTENTI", kwargs["runtime_context"])

    def test_bozza_senza_procedure_e_specifiche(self):
        a = self._fb("come inserisco un nuovo timbro?")
        with patch("ai_assistant.services.build_knowledge_context") as knowledge, patch(
            "ai_assistant.services.chat_with_ollama"
        ) as chat:
            knowledge.return_value.text = ""
            knowledge.return_value.sources = ()
            chat.return_value = OllamaChatResult(content="testo", model="m", done=True)
            faq_suggerite.genera_bozza(self._request(), [a.pk])
        self.assertFalse(knowledge.call_args.kwargs["allow_specifiche"])
        self.assertFalse(knowledge.call_args.kwargs["allow_procedure"])

    def test_contesto_insufficiente_nessuna_bozza(self):
        a = self._fb("domanda strana")
        with patch("ai_assistant.services.chat_with_ollama") as chat:
            chat.return_value = OllamaChatResult(content=faq_suggerite.NON_DISPONIBILE, model="m", done=True)
            bozza, messaggio = faq_suggerite.genera_bozza(self._request(), [a.pk])
        self.assertIsNone(bozza)
        self.assertIn("non contengono la risposta", messaggio)
        self.assertFalse(AiKnowledgeEntry.objects.exists())


@override_settings(OLLAMA_EMBED_ENABLED=False, OLLAMA_RAG_SGI_ENABLED=False, OLLAMA_RAG_CACHE_SECONDS=0,
                   OLLAMA_RAG_SOURCE_PATHS=[])
class ApprovaScartaTests(_Base):
    def tearDown(self):
        clear_knowledge_cache()

    def test_approva_attiva_la_faq_corretta_dall_admin(self):
        bozza = AiKnowledgeEntry.objects.create(question="q", answer="bozza", is_active=False,
                                                source_label=faq_suggerite.SOURCE_LABEL_BOZZA)
        a = self._fb("come aggiungo una sigla nel registro timbri?", entry=bozza)
        entry = faq_suggerite.approva(self._request(), [a.pk], "Come aggiungo una sigla?",
                                      "Scheda del dipendente, pulsante «+ Sigla».")
        entry.refresh_from_db()
        self.assertTrue(entry.is_active)
        self.assertEqual(entry.answer, "Scheda del dipendente, pulsante «+ Sigla».")
        a.refresh_from_db()
        self.assertTrue(a.is_reviewed)
        context = build_knowledge_context("come aggiungo una sigla?")
        self.assertIn("+ Sigla", context.text)

    def test_scarta_chiude_e_non_tocca_le_faq_attive(self):
        attiva = AiKnowledgeEntry.objects.create(question="q", answer="a", is_active=True)
        bozza = AiKnowledgeEntry.objects.create(question="q", answer="b", is_active=False,
                                                source_label=faq_suggerite.SOURCE_LABEL_BOZZA)
        a = self._fb("x y z", entry=bozza)
        b = self._fb("x y z w", entry=attiva)
        self.assertEqual(faq_suggerite.scarta([a.pk, b.pk]), 2)
        self.assertFalse(AiKnowledgeEntry.objects.filter(pk=bozza.pk).exists())
        self.assertTrue(AiKnowledgeEntry.objects.filter(pk=attiva.pk).exists())
        self.assertEqual(AiChatFeedback.objects.filter(is_reviewed=True).count(), 2)


class AdminPannelloTests(_Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.url = reverse("admin_portale:ai_settings")

    def test_pannello_e_flusso_completo(self):
        a = self._fb("come inserisco un nuovo timbro?", correction="Nuovo record")
        page = self.client.get(self.url + "?tab=suggerimenti")
        self.assertContains(page, "FAQ suggerite dai 👎")
        self.assertContains(page, "Approva e attiva FAQ")  # c'è la correzione dell'utente
        self.assertContains(page, "Genera bozza con l'AI")

        with patch("ai_assistant.services.chat_with_ollama") as chat:
            chat.return_value = OllamaChatResult(content="Premi «Nuovo record».", model="m", done=True)
            response = self.client.post(self.url, {"action": "faq_genera_bozza", "tab": "suggerimenti",
                                                   "ids": str(a.pk)})
        self.assertEqual(response.status_code, 302)
        page = self.client.get(self.url + "?tab=suggerimenti")
        self.assertContains(page, "Risposta scritta dall")
        self.assertContains(page, "Rigenera bozza")

        self.client.post(self.url, {"action": "faq_approva_gruppo", "tab": "suggerimenti", "ids": str(a.pk),
                                    "question": "Come inserisco un timbro?", "answer": "Premi «Nuovo record»."})
        self.assertTrue(AiKnowledgeEntry.objects.filter(is_active=True, question="Come inserisco un timbro?").exists())
        page = self.client.get(self.url + "?tab=suggerimenti")
        self.assertContains(page, "Nessun 👎 da rivedere.")

    def test_chat_invita_al_feedback_senza_fonti(self):
        page = self.client.get(reverse("ai_assistant:chat"))
        self.assertContains(page, "ai-no-source-hint")
