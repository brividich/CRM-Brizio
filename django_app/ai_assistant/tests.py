import json
import tempfile
import socket
import urllib.error
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AiChatFeedback, AiKnowledgeEntry
from .services import (
    OllamaChatError,
    OllamaChatResult,
    build_knowledge_context,
    build_ollama_messages,
    chat_with_ollama,
    clear_knowledge_cache,
    warmup_ollama,
)
from .tools import RuntimeContext, _merge_contexts, build_runtime_context


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False)
class AiAssistantTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()  # isola il throttle per-utente tra i test
        self.user = get_user_model().objects.create_superuser(
            username="ai.admin",
            email="ai.admin@example.local",
            password="password",
        )

    def test_chat_page_requires_login(self):
        response = self.client.get(reverse("ai_assistant:chat"))
        self.assertEqual(response.status_code, 302)

    def test_chat_page_authenticated(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("ai_assistant:chat"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Assistente AI")
        self.assertContains(response, "Personalizzazione risposte e limiti")
        self.assertContains(response, "Non pu&ograve;")

    def test_api_chat_returns_ollama_response(self):
        self.client.force_login(self.user)
        with patch("ai_assistant.views.build_runtime_context") as mocked_context, patch(
            "ai_assistant.views.chat_with_ollama"
        ) as mocked_chat:
            mocked_context.return_value.text = ""
            mocked_context.return_value.sources = ()
            mocked_context.return_value.audit = {}
            mocked_chat.return_value = OllamaChatResult(
                content="Risposta sintetica.",
                model="llama3.1",
                done=True,
                sources=("README.md > ai_assistant",),
                rag_context_chars=120,
            )
            response = self.client.post(
                reverse("ai_assistant:api_chat"),
                data='{"message":"ciao"}',
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Risposta sintetica.")
        self.assertEqual(response.json()["sources"], ["README.md > ai_assistant"])
        mocked_chat.assert_called_once()

    def test_api_chat_is_rate_limited(self):
        self.client.force_login(self.user)
        with override_settings(OLLAMA_CHAT_RATE_LIMIT=1, OLLAMA_CHAT_RATE_WINDOW_SECONDS=60), patch(
            "ai_assistant.views.build_runtime_context"
        ) as mocked_context, patch("ai_assistant.views.chat_with_ollama") as mocked_chat:
            mocked_context.return_value.text = ""
            mocked_context.return_value.sources = ()
            mocked_context.return_value.audit = {}
            mocked_chat.return_value = OllamaChatResult(content="ok", model="llama3.1", done=True)
            first = self.client.post(
                reverse("ai_assistant:api_chat"),
                data='{"message":"ciao"}',
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            second = self.client.post(
                reverse("ai_assistant:api_chat"),
                data='{"message":"ciao"}',
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second)
        self.assertFalse(second.json()["ok"])

    def test_api_chat_stream_emits_ndjson_events(self):
        self.client.force_login(self.user)
        with patch("ai_assistant.views.build_runtime_context") as mocked_context, patch(
            "ai_assistant.views.open_ollama_stream"
        ) as mocked_open, patch("ai_assistant.views.iter_ollama_stream") as mocked_iter:
            mocked_context.return_value.text = ""
            mocked_context.return_value.sources = ()
            mocked_context.return_value.audit = {}
            mocked_open.return_value = (
                object(),
                {"model": "llama3.1", "provider": "ollama", "sources": (), "rag_context_chars": 0},
            )
            mocked_iter.return_value = iter(["Ciao", " mondo"])
            response = self.client.post(
                reverse("ai_assistant:api_chat_stream"),
                data='{"message":"ciao"}',
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
            body = b"".join(response.streaming_content).decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/x-ndjson", response["Content-Type"])
        events = [json.loads(line) for line in body.splitlines() if line.strip()]
        self.assertEqual([evt["type"] for evt in events], ["delta", "delta", "done"])
        self.assertEqual(events[0]["text"], "Ciao")
        self.assertEqual(events[-1]["model"], "llama3.1")
        self.assertIn("suggested_questions", events[-1])

    def test_api_daily_brief_generates_and_caches(self):
        self.client.force_login(self.user)
        with patch("ai_assistant.views.build_runtime_context") as mocked_context, patch(
            "ai_assistant.views.chat_with_ollama"
        ) as mocked_chat:
            mocked_context.return_value.text = "DATI LIVE - 2 ticket urgenti aperti"
            mocked_context.return_value.sources = ("tool:tickets:riepilogo",)
            mocked_context.return_value.audit = {}
            mocked_chat.return_value = OllamaChatResult(
                content="- 2 ticket urgenti da gestire oggi", model="qwen2.5:14b-instruct", done=True
            )
            first = self.client.get(reverse("ai_assistant:api_daily_brief"))
            second = self.client.get(reverse("ai_assistant:api_daily_brief"))

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["ok"])
        self.assertIn("ticket urgenti", first.json()["message"])
        self.assertFalse(first.json()["cached"])
        self.assertTrue(second.json()["cached"])
        self.assertEqual(mocked_chat.call_count, 1)  # la seconda risposta arriva dalla cache

    def test_api_daily_brief_handles_empty_context_without_llm(self):
        self.client.force_login(self.user)
        with patch("ai_assistant.views.build_runtime_context") as mocked_context, patch(
            "ai_assistant.views.chat_with_ollama"
        ) as mocked_chat:
            mocked_context.return_value.text = ""
            mocked_context.return_value.sources = ()
            mocked_context.return_value.audit = {}
            response = self.client.get(reverse("ai_assistant:api_daily_brief"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("non risultano", response.json()["message"])
        mocked_chat.assert_not_called()

    def test_api_daily_brief_disabled_returns_503(self):
        self.client.force_login(self.user)
        with override_settings(OLLAMA_DAILY_BRIEF_ENABLED=False):
            response = self.client.get(reverse("ai_assistant:api_daily_brief"))
        self.assertEqual(response.status_code, 503)

    def test_api_chat_stream_returns_502_on_setup_error(self):
        self.client.force_login(self.user)
        with patch("ai_assistant.views.build_runtime_context") as mocked_context, patch(
            "ai_assistant.views.open_ollama_stream",
            side_effect=OllamaChatError("Ollama non raggiungibile."),
        ):
            mocked_context.return_value.text = ""
            mocked_context.return_value.sources = ()
            mocked_context.return_value.audit = {}
            response = self.client.post(
                reverse("ai_assistant:api_chat_stream"),
                data='{"message":"ciao"}',
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json()["ok"])

    def test_chat_with_ollama_reports_openwebui_url_hint_on_405(self):
        with override_settings(
            OLLAMA_BASE_URL="http://10.0.0.34:3000",
            OLLAMA_CHAT_MODEL="llama3.1",
            OLLAMA_RAG_ENABLED=False,
        ), patch("ai_assistant.services.urllib.request.urlopen") as mocked_urlopen:
            mocked_urlopen.side_effect = urllib.error.HTTPError(
                url="http://10.0.0.34:3000/api/chat",
                code=405,
                msg="Method Not Allowed",
                hdrs=None,
                fp=None,
            )
            with self.assertRaises(OllamaChatError) as ctx:
                chat_with_ollama("ciao")

        self.assertIn("Open WebUI", str(ctx.exception))
        self.assertIn("http://10.0.0.34:11434", str(ctx.exception))

    def test_chat_with_ollama_reports_actionable_timeout(self):
        with override_settings(
            OLLAMA_BASE_URL="http://10.0.0.34:11434",
            OLLAMA_CHAT_MODEL="nemotron-3-nano:30b",
            OLLAMA_REQUEST_TIMEOUT_SECONDS=60,
            OLLAMA_RAG_ENABLED=False,
        ), patch("ai_assistant.services.urllib.request.urlopen") as mocked_urlopen:
            mocked_urlopen.side_effect = TimeoutError("timed out")
            with self.assertRaises(OllamaChatError) as ctx:
                chat_with_ollama("ciao")

        self.assertIn("Timeout dopo 60s", str(ctx.exception))
        self.assertIn("180-300", str(ctx.exception))

    def test_chat_with_ollama_reports_urlerror_timeout(self):
        with override_settings(
            OLLAMA_BASE_URL="http://10.0.0.34:11434",
            OLLAMA_CHAT_MODEL="nemotron-3-nano:30b",
            OLLAMA_REQUEST_TIMEOUT_SECONDS=60,
            OLLAMA_RAG_ENABLED=False,
        ), patch("ai_assistant.services.urllib.request.urlopen") as mocked_urlopen:
            mocked_urlopen.side_effect = urllib.error.URLError(socket.timeout("timed out"))
            with self.assertRaises(OllamaChatError) as ctx:
                chat_with_ollama("ciao")

        self.assertIn("Timeout dopo 60s", str(ctx.exception))

    def test_warmup_ollama_preloads_native_model(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"model":"llama3.1","done":true,"done_reason":"load"}'

        with override_settings(
            OLLAMA_CHAT_ENABLED=True,
            OLLAMA_API_PROVIDER="ollama",
            OLLAMA_BASE_URL="http://10.0.0.34:11434",
            OLLAMA_CHAT_MODEL="llama3.1",
            OLLAMA_KEEP_ALIVE="30m",
        ), patch("ai_assistant.services.urllib.request.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            result = warmup_ollama()

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://10.0.0.34:11434/api/generate")
        self.assertEqual(payload["model"], "llama3.1")
        self.assertEqual(payload["prompt"], "")
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["keep_alive"], "30m")
        self.assertTrue(result["ok"])
        self.assertTrue(result["loaded"])
        self.assertFalse(result["skipped"])

    def test_warmup_ollama_skips_openwebui_provider(self):
        with override_settings(
            OLLAMA_CHAT_ENABLED=True,
            OLLAMA_API_PROVIDER="openwebui",
            OLLAMA_BASE_URL="http://10.0.0.34:3000",
            OLLAMA_CHAT_MODEL="llama3.1",
        ), patch("ai_assistant.services.urllib.request.urlopen") as mocked_urlopen:
            result = warmup_ollama()

        mocked_urlopen.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertTrue(result["skipped"])
        self.assertIn("Open WebUI", result["message"])

    def test_warmup_ollama_reports_timeout_without_raising(self):
        with override_settings(
            OLLAMA_CHAT_ENABLED=True,
            OLLAMA_API_PROVIDER="ollama",
            OLLAMA_BASE_URL="http://10.0.0.34:11434",
            OLLAMA_CHAT_MODEL="llama3.1",
            OLLAMA_REQUEST_TIMEOUT_SECONDS=180,
        ), patch("ai_assistant.services.urllib.request.urlopen") as mocked_urlopen:
            mocked_urlopen.side_effect = TimeoutError("timed out")
            result = warmup_ollama(timeout=300)

        self.assertFalse(result["ok"])
        self.assertFalse(result["skipped"])
        self.assertIn("timeout dopo 300s", result["message"])

    def test_run_warmup_ollama_task_delegates_to_service(self):
        from ai_assistant.tasks import run_warmup_ollama

        sentinel = {"ok": True, "skipped": False, "loaded": True, "message": "ok"}
        with patch("ai_assistant.services.warmup_ollama", return_value=sentinel) as mocked:
            result = run_warmup_ollama(timeout=300)

        mocked.assert_called_once_with(timeout=300)
        self.assertIs(result, sentinel)

    def test_run_warmup_ollama_task_is_failsafe(self):
        from ai_assistant.tasks import run_warmup_ollama

        with patch("ai_assistant.services.warmup_ollama", side_effect=RuntimeError("boom")):
            result = run_warmup_ollama()

        self.assertFalse(result["ok"])
        self.assertFalse(result["skipped"])
        self.assertIn("inatteso", result["message"])

    def test_chat_with_openwebui_uses_chat_completions_endpoint(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"model":"llama3.1","choices":[{"message":{"content":"Da Open WebUI."}}]}'

        with override_settings(
            OLLAMA_API_PROVIDER="openwebui",
            OLLAMA_BASE_URL="http://10.0.0.34:3000",
            OLLAMA_CHAT_MODEL="llama3.1",
            OPENWEBUI_API_KEY="sk-test",
            OLLAMA_RAG_ENABLED=False,
        ), patch("ai_assistant.services.urllib.request.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            result = chat_with_ollama("ciao")

        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://10.0.0.34:3000/api/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer sk-test")
        self.assertEqual(result.content, "Da Open WebUI.")

    def test_chat_with_ollama_hides_rag_sources_when_runtime_context_present(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"model":"llama3.1","message":{"content":"Dato live."},"done":true}'

        with override_settings(
            OLLAMA_API_PROVIDER="ollama",
            OLLAMA_BASE_URL="http://10.0.0.34:11434",
            OLLAMA_CHAT_MODEL="llama3.1",
            OLLAMA_RAG_ENABLED=True,
        ), patch("ai_assistant.services.build_knowledge_context") as mocked_knowledge, patch(
            "ai_assistant.services.urllib.request.urlopen",
            return_value=FakeResponse(),
        ) as mocked_urlopen:
            mocked_knowledge.return_value = SimpleNamespace(
                text="[fonte: README.md > Audit delle route ancora in fallback] testo RAG",
                sources=("README.md > Audit delle route ancora in fallback",),
            )
            result = chat_with_ollama(
                "Quante ore ferie residue ha SMARRELLA?",
                runtime_context="DATI LIVE PORTALE - ANAGRAFICA HR / RATEI\nRISPOSTA DIRETTA: 10 ore.",
            )

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        joined_messages = "\n".join(item["content"] for item in payload["messages"])
        self.assertIn("CONTESTO LIVE AUTORIZZATO", joined_messages)
        self.assertIn("RISPOSTA DIRETTA", joined_messages)
        self.assertNotIn("README.md", joined_messages)
        self.assertEqual(result.sources, ())
        self.assertEqual(result.rag_context_chars, 0)

    def test_api_save_knowledge_requires_admin(self):
        normal_user = get_user_model().objects.create_user(username="ai.user", password="password")
        self.client.force_login(normal_user)

        response = self.client.post(
            reverse("ai_assistant:api_save_knowledge"),
            data='{"question":"Dove sono le ferie?","answer":"Nel modulo assenze."}',
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(AiKnowledgeEntry.objects.exists())

    def test_api_save_knowledge_creates_curated_entry(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("ai_assistant:api_save_knowledge"),
            data='{"question":"Dove sono le ferie?","answer":"Nel modulo assenze."}',
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        entry = AiKnowledgeEntry.objects.get()
        self.assertEqual(entry.question, "Dove sono le ferie?")
        self.assertEqual(entry.answer, "Nel modulo assenze.")
        self.assertEqual(entry.created_by, self.user)

    def test_build_messages_filters_history_roles(self):
        with override_settings(
            OLLAMA_CHAT_SYSTEM_PROMPT="Sistema",
            OLLAMA_CHAT_MAX_PROMPT_CHARS=50,
            OLLAMA_RAG_ENABLED=False,
        ):
            messages = build_ollama_messages(
                "Domanda",
                history=[
                    {"role": "tool", "content": "no"},
                    {"role": "assistant", "content": "ok"},
                ],
            )
        self.assertEqual([m["role"] for m in messages], ["system", "assistant", "user"])

    def test_build_knowledge_context_reads_configured_documents(self):
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as tmpdir:
            doc_path = Path(tmpdir) / "knowledge.md"
            doc_path.write_text(
                "# Assenze\nLe richieste ferie si gestiscono dal modulo assenze del portale.",
                encoding="utf-8",
            )

            with override_settings(
                OLLAMA_RAG_ENABLED=True,
                OLLAMA_RAG_SOURCE_PATHS=[str(doc_path)],
                OLLAMA_RAG_MAX_CHUNKS=2,
                OLLAMA_RAG_MAX_CONTEXT_CHARS=1000,
                OLLAMA_RAG_CACHE_SECONDS=0,
            ):
                context = build_knowledge_context("dove gestisco le richieste ferie?")

        self.assertIn("richieste ferie", context.text)
        self.assertTrue(any("knowledge.md" in source for source in context.sources))

    def test_knowledge_base_folder_is_indexed(self):
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=["django_app/ai_assistant/knowledge"],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            context = build_knowledge_context("come richiedo ferie o permessi?")

        self.assertTrue(any("knowledge" in source for source in context.sources))
        self.assertIn("Assenze", context.text)

    def test_build_knowledge_context_ranks_relevant_document_first(self):
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as tmpdir:
            (Path(tmpdir) / "ferie.md").write_text(
                "# Ferie\nLe richieste ferie e permessi si gestiscono dal modulo assenze del portale.",
                encoding="utf-8",
            )
            (Path(tmpdir) / "ticket.md").write_text(
                "# Ticket IT\nI guasti informatici si aprono dal modulo supporto tecnico.",
                encoding="utf-8",
            )

            with override_settings(
                OLLAMA_RAG_ENABLED=True,
                OLLAMA_RAG_SOURCE_PATHS=[tmpdir],
                OLLAMA_RAG_MAX_CHUNKS=1,
                OLLAMA_RAG_MAX_CONTEXT_CHARS=1000,
                OLLAMA_RAG_CACHE_SECONDS=0,
            ):
                context = build_knowledge_context("come gestisco le ferie e i permessi?")

        self.assertTrue(any("ferie.md" in source for source in context.sources))
        self.assertFalse(any("ticket.md" in source for source in context.sources))

    def test_new_curated_knowledge_files_are_retrievable(self):
        """Le domande tipiche recuperano il file di knowledge curato atteso.

        Guardia di regressione sui file aggiunti: se un titolo o un contenuto
        cambia al punto da non rispondere piu' alla domanda canonica, il test
        rompe. Sorgenti limitate alla KB pacchettizzata (come in produzione, dove
        docs/ e' escluso dal pacchetto), retrieval BM25 deterministico.
        """
        cases = [
            ("cosa sono le qualifiche e le abilitazioni?", "05_anagrafica_qualifiche_formazione"),
            ("a cosa serve il modulo anomalie?", "06_anomalie_produzione"),
            ("come funzionano le approvazioni automatiche?", "07_tasks_automazioni"),
            ("cosa significa ROL?", "08_glossario"),
            ("come accedo al portale con autenticazione a due fattori?", "09_accesso_account"),
        ]
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=["django_app/ai_assistant/knowledge"],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            clear_knowledge_cache()
            for question, expected_file in cases:
                context = build_knowledge_context(question)
                self.assertTrue(
                    any(expected_file in source for source in context.sources),
                    msg=f"'{question}' non recupera {expected_file}: fonti={context.sources}",
                )

    def test_curated_knowledge_base_is_among_effective_rag_sources(self):
        """La KB curata pacchettizzata e' sempre tra le sorgenti RAG effettive.

        Invariante critica: la knowledge base curata e' la fonte di conoscenza
        canonica spedita con l'app. Un OLLAMA_RAG_SOURCE_PATHS stantio nell'.env
        che la ometteva (bug reale: lasciava solo README.md in prod, dato che docs/
        e' escluso dal pacchetto) ha reso la KB inutilizzata. Questo test legge il
        valore EFFETTIVO (env o default) e fallisce se la KB non e' tra le sorgenti.
        """
        sources = [str(p) for p in settings.OLLAMA_RAG_SOURCE_PATHS]
        self.assertTrue(
            any("ai_assistant/knowledge" in s.replace("\\", "/") for s in sources),
            msg=f"La KB curata non e' tra le sorgenti RAG effettive: {sources}",
        )

    def test_ai_eval_rag_command_reports_full_recall_on_curated_kb(self):
        """L'harness `ai_eval --rag` gira senza crash e raggiunge recall pieno sulla KB.

        Verifica end-to-end: comando, golden set RAG e knowledge base curata. Le
        sorgenti sono limitate alla KB pacchettizzata; embeddings spenti -> BM25.
        """
        from ai_assistant.management.commands.ai_eval import _RAG_GOLDEN

        out = StringIO()
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=["django_app/ai_assistant/knowledge"],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            clear_knowledge_cache()
            call_command("ai_eval", "--rag", "--json", stdout=out)

        payload = json.loads(out.getvalue())
        summary = payload["summary"]
        self.assertEqual(summary["mode"], "rag")
        self.assertFalse(summary["embeddings_enabled"])
        self.assertEqual(summary["cases"], len(_RAG_GOLDEN))
        self.assertEqual(summary["recall_hits"], summary["cases"])
        self.assertGreater(summary["chunks_indexed"], 0)
        # Metriche rank-aware: ordinamento sano (MRR alto) e nessun file KB scoperto.
        self.assertIsNotNone(summary["mrr"])
        self.assertGreaterEqual(summary["mrr"], 0.8)
        self.assertGreaterEqual(summary["rank1_hits"], 1)
        self.assertEqual(
            summary["kb_files_uncovered"],
            [],
            msg="Ogni file di knowledge deve essere esercitato da almeno una golden RAG.",
        )

    def test_ai_eval_rag_live_flags_real_question_gaps(self):
        """`ai_eval --rag-live` valuta la copertura KB sulle domande REALI del DB.

        Una domanda coperta dalla KB curata risulta covered=True; una fuori dominio
        (nessun file di knowledge la risponde, al più il README generico) è un 'gap'.
        Esercita end-to-end l'harvest da AiChatFeedback e la logica di copertura.
        """
        AiChatFeedback.objects.create(
            prompt="quante ferie mi restano?", response="risposta", rating="up"
        )
        AiChatFeedback.objects.create(
            prompt="come prenoto un parcheggio per la bicicletta?",
            response="risposta",
            rating="down",
        )

        out = StringIO()
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=["README.md", "django_app/ai_assistant/knowledge"],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            clear_knowledge_cache()
            call_command("ai_eval", "--rag-live", "--json", stdout=out)

        payload = json.loads(out.getvalue())
        summary = payload["summary"]
        self.assertEqual(summary["mode"], "rag-live")
        self.assertEqual(summary["evaluated"], 2)
        by_prompt = {r["prompt"]: r for r in payload["results"]}
        ferie = by_prompt["quante ferie mi restano?"]
        self.assertTrue(ferie["covered"])
        # La domanda coperta porta uno score BM25 del chunk KB > 0 (visibilità A2).
        self.assertIsNotNone(ferie["kb_score"])
        self.assertGreater(ferie["kb_score"], 0)
        self.assertFalse(by_prompt["come prenoto un parcheggio per la bicicletta?"]["covered"])
        self.assertGreaterEqual(summary["gaps"], 1)

    def test_ai_eval_rag_live_min_score_flags_weak_matches_as_gaps(self):
        """Con --min-score alta anche un match KB forte diventa gap 'debole'.

        Verifica la soglia di qualità (A2): senza soglia la domanda è coperta; con una
        soglia irraggiungibile lo stesso match (sotto soglia) è classificato gap debole.
        """
        AiChatFeedback.objects.create(
            prompt="quante ferie mi restano?", response="risposta", rating="up"
        )

        def run(min_score):
            out = StringIO()
            with override_settings(
                OLLAMA_RAG_ENABLED=True,
                OLLAMA_EMBED_ENABLED=False,
                OLLAMA_RAG_SOURCE_PATHS=["README.md", "django_app/ai_assistant/knowledge"],
                OLLAMA_RAG_CACHE_SECONDS=0,
            ):
                clear_knowledge_cache()
                call_command("ai_eval", "--rag-live", "--json", "--min-score", str(min_score), stdout=out)
            return json.loads(out.getvalue())

        covered = run(0.0)
        self.assertTrue(covered["results"][0]["covered"])
        self.assertEqual(covered["summary"]["weak_gaps"], 0)

        strict = run(9999)
        row = strict["results"][0]
        self.assertFalse(row["covered"])
        self.assertTrue(row["weak"])  # ha recuperato un chunk KB, ma sotto soglia
        self.assertEqual(strict["summary"]["covered"], 0)
        self.assertEqual(strict["summary"]["weak_gaps"], 1)

    def test_wants_anagrafica_ratei_context_recognizes_phrasings(self):
        from ai_assistant.tools import _wants_anagrafica_ratei_context

        should_trigger = [
            "elenca i dipendenti in ordine delle ferie piu elevate",
            "chi ha piu ferie accumulate?",
            "quante ferie ha Rossi?",
            "primi 5 dipendenti per ferie residue",
            "ferie rimanenti dei dipendenti",
            "classifica ROL piu alti",
            "ferie maturate non godute",
        ]
        for prompt in should_trigger:
            self.assertTrue(_wants_anagrafica_ratei_context(prompt), prompt)

        should_not_trigger = [
            "chi e' assente in ferie domani?",
            "elenco dipendenti del reparto produzione",
            "quali sono i miei ticket aperti?",
        ]
        for prompt in should_not_trigger:
            self.assertFalse(_wants_anagrafica_ratei_context(prompt), prompt)

    def test_runtime_context_respects_configured_cap(self):
        from ai_assistant.tools import RuntimeContext, _merge_contexts

        big = RuntimeContext(
            text="X" * 5000, sources=("tool:test",), audit={"tool": "t", "allowed": True}
        )
        with override_settings(AI_RUNTIME_CONTEXT_MAX_CHARS=500, AI_RUNTIME_CONTEXT_MAX_LINES=50):
            merged = _merge_contexts([big])

        self.assertLessEqual(len(merged.text), 500)
        self.assertTrue(merged.audit["truncated"])
        self.assertEqual(merged.audit["max_chars"], 500)

    def test_chat_with_ollama_respects_timeout_override(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"model":"llama3.1","message":{"content":"ok"},"done":true}'

        with override_settings(
            OLLAMA_BASE_URL="http://10.0.0.34:11434",
            OLLAMA_CHAT_MODEL="llama3.1",
            OLLAMA_REQUEST_TIMEOUT_SECONDS=180,
            OLLAMA_RAG_ENABLED=False,
        ), patch("ai_assistant.services.urllib.request.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            chat_with_ollama("ciao", timeout=12)

        self.assertEqual(mocked_urlopen.call_args.kwargs.get("timeout"), 12)

    def test_ratei_name_filter_ignores_ranking_words_and_metrics(self):
        from ai_assistant.tools import _extract_ratei_name_filter

        # Domande di classifica / metriche: NON devono estrarre un nominativo
        # ("chi ha piu ferie" e' una classifica, "ROL" e' una metrica non un nome).
        for prompt in (
            "chi ha piu ferie residue",
            "chi ha più ferie residue",
            "chi ha meno permessi",
            "classifica ROL residui",
            "chi ha le ferie maturate piu alte",
        ):
            self.assertEqual(_extract_ratei_name_filter(prompt), "", prompt)

        # Ma un lookup nominativo reale resta funzionante.
        self.assertEqual(_extract_ratei_name_filter("quante ferie ha Rossi?"), "Rossi")

    def test_wants_asset_context_ignores_hr_deadline_queries(self):
        from ai_assistant.tools import _wants_asset_context

        # "ferie in scadenza" non e' una domanda sugli asset (scadenza e' generica)
        self.assertFalse(_wants_asset_context("quali ferie sono in scadenza?"))
        self.assertFalse(_wants_asset_context("permessi in scadenza dei dipendenti"))
        # ma una domanda asset reale (con keyword) resta riconosciuta
        self.assertTrue(_wants_asset_context("quali asset sono in scadenza?"))
        self.assertTrue(_wants_asset_context("manutenzione del carroponte"))

    def test_should_run_combines_keyword_and_semantic(self):
        from ai_assistant.tools import _should_run

        req = SimpleNamespace(ai_active_domains={"anagrafica"})
        self.assertTrue(_should_run(req, "anagrafica", False))  # via semantica
        self.assertTrue(_should_run(req, "tickets", True))      # via keyword
        self.assertFalse(_should_run(req, "tickets", False))    # ne' l'uno ne' l'altro

        req_no_attr = SimpleNamespace()
        self.assertTrue(_should_run(req_no_attr, "tickets", True))
        self.assertFalse(_should_run(req_no_attr, "tickets", False))

    def test_semantic_routing_activates_domain_without_keyword(self):
        from ai_assistant import tools

        def fake_embed(texts):
            vectors = []
            for text in texts:
                lowered = text.lower()
                if any(w in lowered for w in ("ferie", "dipendent", "permess", "rol", "ratei", "anagrafic")):
                    vectors.append([1.0, 0.0])
                else:
                    vectors.append([0.0, 1.0])
            return vectors

        tools._ROUTING_SEED_CACHE.update({"model": "", "vectors": None})
        with override_settings(
            OLLAMA_EMBED_ENABLED=True,
            OLLAMA_EMBED_MODEL="test-embed",
            OLLAMA_API_PROVIDER="ollama",
            RAG_EMBED_BACKEND="ollama",
            AI_TOOL_ROUTING_ENABLED=True,
            AI_TOOL_ROUTING_THRESHOLD=0.7,
            AI_TOOL_ROUTING_MARGIN=0.5,
            AI_TOOL_ROUTING_TOP_K=2,
        ), patch("ai_assistant.services._ollama_embed_texts", side_effect=fake_embed):
            active = tools._semantic_active_domains(
                "quanto tempo libero mi spetta ancora per le ferie quest'anno"
            )
        tools._ROUTING_SEED_CACHE.update({"model": "", "vectors": None})
        self.assertIn("anagrafica", active)

    def test_semantic_routing_does_not_bypass_acl(self):
        """Un tool attivato SOLO dal routing semantico (nessuna keyword) deve
        comunque applicare l'ACL interna e negare l'accesso se non autorizzato."""
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")
        with patch("ai_assistant.tools._rank_domains", return_value=[("tasks", 0.9)]), patch(
            "tasks.views._has_task_permission", return_value=False
        ), override_settings(
            AI_TOOL_ROUTING_THRESHOLD=0.7,
            AI_TOOL_ROUTING_MARGIN=0.04,
            AI_TOOL_ROUTING_TOP_K=2,
        ):
            context = build_runtime_context(request, "dammi un riepilogo generale per favore")

        self.assertIn("tool:tasks:accesso-negato", context.sources)
        self.assertTrue(context.audit["tools"])
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_tokenize_folds_accents(self):
        from ai_assistant.services import _tokenize

        tokens = _tokenize("Qualità città produzione")
        self.assertIn("qualita", tokens)
        self.assertIn("citta", tokens)
        self.assertIn("produzione", tokens)

    def test_hybrid_retrieval_recovers_semantic_match(self):
        """Con embeddings attivi, un documento pertinente ma senza match lessicale
        viene comunque recuperato (BM25 da solo lo perderebbe)."""

        def fake_embed(texts):
            vectors = []
            for text in texts:
                lowered = text.lower()
                if "permess" in lowered or "congedi" in lowered or "ferie" in lowered:
                    vectors.append([1.0, 0.0])
                else:
                    vectors.append([0.0, 1.0])
            return vectors

        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as tmpdir:
            (Path(tmpdir) / "assenze.md").write_text(
                "# Permessi e congedi\nGestione di permessi e congedi del personale dal portale.",
                encoding="utf-8",
            )
            (Path(tmpdir) / "backup.md").write_text(
                "# Backup server\nProcedura di backup notturno dei server e ripristino dati.",
                encoding="utf-8",
            )
            with override_settings(
                OLLAMA_RAG_ENABLED=True,
                OLLAMA_EMBED_ENABLED=True,
                OLLAMA_EMBED_MODEL="test-embed",
                OLLAMA_EMBED_PERSIST=False,
                RAG_EMBED_BACKEND="ollama",
                OLLAMA_RAG_SOURCE_PATHS=[tmpdir],
                OLLAMA_RAG_MAX_CHUNKS=1,
                OLLAMA_RAG_MAX_CONTEXT_CHARS=1000,
                OLLAMA_RAG_CACHE_SECONDS=0,
            ), patch("ai_assistant.services._ollama_embed_texts", side_effect=fake_embed):
                context = build_knowledge_context("come gestisco le ferie?")

        self.assertTrue(any("assenze.md" in source for source in context.sources))
        self.assertFalse(any("backup.md" in source for source in context.sources))

    def test_embeddings_failure_falls_back_to_bm25(self):
        with tempfile.TemporaryDirectory(dir=settings.BASE_DIR) as tmpdir:
            (Path(tmpdir) / "ferie.md").write_text(
                "# Ferie\nLe richieste ferie si gestiscono dal modulo assenze del portale.",
                encoding="utf-8",
            )
            with override_settings(
                OLLAMA_RAG_ENABLED=True,
                OLLAMA_EMBED_ENABLED=True,
                OLLAMA_EMBED_MODEL="test-embed",
                OLLAMA_EMBED_PERSIST=False,
                OLLAMA_EMBED_RETRY=0,  # niente backoff: il fallback e' immediato nel test
                RAG_EMBED_BACKEND="ollama",
                OLLAMA_RAG_SOURCE_PATHS=[tmpdir],
                OLLAMA_RAG_MAX_CHUNKS=2,
                OLLAMA_RAG_CACHE_SECONDS=0,
            ), patch("ai_assistant.services._ollama_embed_texts", return_value=None):
                context = build_knowledge_context("dove gestisco le richieste ferie?")

        self.assertIn("richieste ferie", context.text)
        self.assertTrue(any("ferie.md" in source for source in context.sources))

    def test_chat_payload_includes_ollama_tuning(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"model":"llama3.1","message":{"content":"ok"},"done":true}'

        with override_settings(
            OLLAMA_API_PROVIDER="ollama",
            OLLAMA_BASE_URL="http://10.0.0.34:11434",
            OLLAMA_CHAT_MODEL="llama3.1",
            OLLAMA_KEEP_ALIVE="45m",
            OLLAMA_NUM_CTX=4096,
            OLLAMA_NUM_PREDICT=512,
            OLLAMA_RAG_ENABLED=False,
        ), patch("ai_assistant.services.urllib.request.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            chat_with_ollama("ciao")

        payload = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["keep_alive"], "45m")
        self.assertEqual(payload["options"]["num_ctx"], 4096)
        self.assertEqual(payload["options"]["num_predict"], 512)

    def test_openwebui_payload_omits_native_tuning(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"model":"llama3.1","choices":[{"message":{"content":"ok"}}]}'

        with override_settings(
            OLLAMA_API_PROVIDER="openwebui",
            OLLAMA_BASE_URL="http://10.0.0.34:3000",
            OLLAMA_CHAT_MODEL="llama3.1",
            OPENWEBUI_API_KEY="sk-test",
            OLLAMA_KEEP_ALIVE="30m",
            OLLAMA_NUM_CTX=4096,
            OLLAMA_RAG_ENABLED=False,
        ), patch("ai_assistant.services.urllib.request.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            chat_with_ollama("ciao")

        payload = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertNotIn("keep_alive", payload)
        self.assertNotIn("options", payload)

    def test_build_knowledge_context_reads_curated_entries(self):
        AiKnowledgeEntry.objects.create(
            question="Come apro il modulo qualita interna?",
            answer="Usa la voce Procedure nel portale.",
            created_by=self.user,
            updated_by=self.user,
        )

        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_RAG_SOURCE_PATHS=[],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            context = build_knowledge_context("modulo qualita interna")

        self.assertIn("Procedure", context.text)
        self.assertTrue(any(source.startswith("faq-portale/") for source in context.sources))

    def test_build_messages_includes_knowledge_context(self):
        with override_settings(OLLAMA_CHAT_SYSTEM_PROMPT="Sistema", OLLAMA_CHAT_MAX_PROMPT_CHARS=50):
            messages = build_ollama_messages("Domanda", knowledge_context="[fonte: README.md] testo")

        self.assertEqual(messages[0]["content"], "Sistema")
        self.assertIn("CONTESTO PORTALE", messages[1]["content"])

    def test_build_messages_includes_runtime_context(self):
        with override_settings(OLLAMA_CHAT_SYSTEM_PROMPT="Sistema", OLLAMA_CHAT_MAX_PROMPT_CHARS=50):
            messages = build_ollama_messages("Chi e' assente domani?", runtime_context="Mario Rossi: Ferie")

        self.assertIn("CONTESTO LIVE AUTORIZZATO", messages[1]["content"])
        self.assertIn("Mario Rossi", messages[1]["content"])
        self.assertIn("Cita le fonti tool:*", messages[1]["content"])
        self.assertIn("fatti osservati", messages[1]["content"])

    def test_build_messages_includes_sanitized_user_preferences(self):
        with override_settings(OLLAMA_CHAT_SYSTEM_PROMPT="Sistema", OLLAMA_CHAT_MAX_PROMPT_CHARS=80):
            messages = build_ollama_messages(
                "Domanda",
                user_preferences={"style": "dettagliato", "show_limits": True},
            )

        self.assertIn("PREFERENZE DI RISPOSTA", messages[1]["content"])
        self.assertIn("Rispondi in modo dettagliato", messages[1]["content"])
        self.assertIn("permesso mancante", messages[1]["content"])
        self.assertIn("non autorizzano nuovi dati", messages[1]["content"])

    def test_runtime_absence_context_denies_users_without_calendar_permission(self):
        request = SimpleNamespace(user=self.user)
        with patch("ai_assistant.tools.get_legacy_user", return_value=None), patch(
            "assenze.views._assenze_permissions",
            return_value={"group": "UTENTI", "can_view_calendar": False},
        ):
            context = build_runtime_context(request, "chi e' assente domani?")

        self.assertIn("tool:assenze:accesso-negato", context.sources)
        self.assertIn("non ha permessi calendario assenze", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_absence_context_loads_admin_period(self):
        request = SimpleNamespace(user=self.user)
        with patch(
            "assenze.views._assenze_permissions",
            return_value={"group": "AMMINISTRAZIONE", "can_view_calendar": True, "can_update_any": True},
        ), patch("assenze.views._load_all_assenze_periodo") as mocked_loader:
            mocked_loader.return_value = [
                {
                    "dipendente": "Mario Rossi",
                    "tipo": "Ferie",
                    "consenso": "Approvato",
                    "inizio_label": "13/05/2026 08:00",
                    "fine_label": "13/05/2026 17:00",
                }
            ]
            context = build_runtime_context(request, "elenco assenti domani")

        self.assertIn("tool:assenze:periodo", context.sources)
        self.assertIn("Mario Rossi", context.text)
        self.assertIn("Ferie", context.text)
        self.assertEqual(context.audit["tools"][0]["row_count"], 1)

    def test_runtime_module_catalog_context_lists_visible_navigation(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")
        nav_item = SimpleNamespace(label="Ticket", href="/tickets/", legacy_url="/tickets/", coming=False)
        with patch("core.context_processors.legacy_nav", return_value={"nav_items": [nav_item]}):
            context = build_runtime_context(request, "quali moduli posso usare nel portale?")

        self.assertIn("tool:portale:moduli", context.sources)
        self.assertIn("Ticket", context.text)
        self.assertIn("/tickets/", context.text)
        self.assertEqual(context.audit["tools"][0]["tool"], "module_catalog")

    def test_runtime_ticket_context_limits_non_manager_to_own_tickets(self):
        from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket

        own = Ticket.objects.create(
            tipo=TipoTicket.IT,
            titolo="VPN non funziona",
            descrizione="Dettaglio privato da non inviare",
            categoria="RETE",
            priorita=PrioritaTicket.ALTA,
            stato=StatoTicket.APERTA,
            richiedente_nome=self.user.username,
            richiedente_email=self.user.email,
        )
        other = Ticket.objects.create(
            tipo=TipoTicket.IT,
            titolo="Stampante reparto qualita",
            descrizione="Altro dettaglio privato",
            categoria="STAMPANTE",
            priorita=PrioritaTicket.MEDIA,
            stato=StatoTicket.APERTA,
            richiedente_nome="Altro Utente",
            richiedente_email="altro@example.local",
        )
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("tickets.views._can_manage_tickets", return_value=False), patch(
            "ai_assistant.tools.get_legacy_user", return_value=None
        ):
            context = build_runtime_context(request, "quali ticket aperti ho?")

        self.assertIn("tool:tickets:riepilogo", context.sources)
        self.assertIn(own.numero_ticket, context.text)
        self.assertIn("VPN non funziona", context.text)
        self.assertNotIn(other.numero_ticket, context.text)
        self.assertNotIn("Stampante reparto qualita", context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "personale")

    def test_runtime_ticket_context_manager_sees_only_managed_ticket_types(self):
        from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket

        it_ticket = Ticket.objects.create(
            tipo=TipoTicket.IT,
            titolo="Postazione bloccata",
            descrizione="Dettaglio tecnico interno",
            categoria="PC",
            priorita=PrioritaTicket.URGENTE,
            stato=StatoTicket.APERTA,
            richiedente_nome="Mario Rossi",
            richiedente_email="mario@example.local",
        )
        man_ticket = Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo="Pressa ferma",
            descrizione="Dettaglio manutenzione interno",
            categoria="MACCHINARIO",
            priorita=PrioritaTicket.URGENTE,
            stato=StatoTicket.APERTA,
            richiedente_nome="Luigi Verdi",
            richiedente_email="luigi@example.local",
        )
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        def can_manage(_request, tipo=None):
            return tipo == TipoTicket.IT

        with patch("tickets.views._can_manage_tickets", side_effect=can_manage), patch(
            "ai_assistant.tools.get_legacy_user", return_value=None
        ):
            context = build_runtime_context(request, "mostra ticket urgenti aperti")

        self.assertIn(it_ticket.numero_ticket, context.text)
        self.assertNotIn(man_ticket.numero_ticket, context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "gestione:IT")
        self.assertEqual(context.audit["tools"][0]["filters"], ["priorita=urgente", "stato=aperto"])

    def test_runtime_ticket_context_does_not_include_sensitive_fields(self):
        from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket

        ticket = Ticket.objects.create(
            tipo=TipoTicket.IT,
            titolo="Accesso gestionale",
            descrizione="SEGRETO_DESCRIZIONE",
            categoria="SOFTWARE",
            priorita=PrioritaTicket.MEDIA,
            stato=StatoTicket.APERTA,
            richiedente_nome=self.user.username,
            richiedente_email=self.user.email,
            note_interne="SEGRETO_NOTE_INTERNE",
            sharepoint_item_id="SEGRETO_SHAREPOINT",
        )
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("tickets.views._can_manage_tickets", return_value=False), patch(
            "ai_assistant.tools.get_legacy_user", return_value=None
        ):
            context = build_runtime_context(request, "riepilogo ticket aperti")

        self.assertIn(ticket.numero_ticket, context.text)
        self.assertNotIn("SEGRETO_DESCRIZIONE", context.text)
        self.assertNotIn("SEGRETO_NOTE_INTERNE", context.text)
        self.assertNotIn("SEGRETO_SHAREPOINT", context.text)

    def test_runtime_tasks_context_limits_to_scoped_tasks(self):
        from tasks.models import Project, Task, TaskStatus

        User = get_user_model()
        assignee = User.objects.create_user(
            username="task.user",
            email="task.user@example.local",
            password="password",
        )
        other_user = User.objects.create_user(
            username="task.other",
            email="task.other@example.local",
            password="password",
        )
        project = Project.objects.create(name="Progetto visibile", created_by=other_user)
        visible = Task.objects.create(
            title="Preparare distinta materiali",
            status=TaskStatus.TODO,
            due_date=timezone.localdate() + timedelta(days=2),
            project=project,
            created_by=other_user,
            assigned_to=assignee,
        )
        hidden = Task.objects.create(
            title="Task non autorizzato",
            status=TaskStatus.TODO,
            due_date=timezone.localdate() + timedelta(days=2),
            created_by=other_user,
            assigned_to=other_user,
        )
        request = SimpleNamespace(user=assignee, path="/assistente-ai/")

        def has_task_permission(_request, action_code):
            return action_code == "tasks_view"

        with patch("tasks.views._has_task_permission", side_effect=has_task_permission):
            context = build_runtime_context(request, "quali task aperti ho?")

        self.assertIn("tool:tasks:riepilogo", context.sources)
        self.assertIn(visible.title, context.text)
        self.assertNotIn(hidden.title, context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "scoped")

    def test_runtime_tasks_context_denies_without_module_permission(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("tasks.views._has_task_permission", return_value=False):
            context = build_runtime_context(request, "mostra task in ritardo")

        self.assertIn("tool:tasks:accesso-negato", context.sources)
        self.assertIn("non ha accesso al modulo KICK-OFF", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_tasks_context_does_not_include_sensitive_fields(self):
        from tasks.models import Task, TaskStatus

        task = Task.objects.create(
            title="Verifica scadenza stampo",
            description="SEGRETO_DESCRIZIONE_TASK",
            status=TaskStatus.TODO,
            due_date=timezone.localdate() - timedelta(days=1),
            next_step_text="SEGRETO_NEXT_STEP",
            extra_data={"segreto": "SEGRETO_EXTRA_DATA"},
            created_by=self.user,
            assigned_to=self.user,
        )
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        def has_task_permission(_request, action_code):
            return action_code in {"tasks_view", "tasks_admin"}

        with patch("tasks.views._has_task_permission", side_effect=has_task_permission):
            context = build_runtime_context(request, "riepilogo task in ritardo")

        self.assertIn(task.title, context.text)
        self.assertIn("in ritardo", context.text)
        self.assertNotIn("SEGRETO_DESCRIZIONE_TASK", context.text)
        self.assertNotIn("SEGRETO_NEXT_STEP", context.text)
        self.assertNotIn("SEGRETO_EXTRA_DATA", context.text)

    def test_runtime_assets_context_summarizes_allowed_operational_data(self):
        from assets.models import Asset, AssetAdministrativeDeadline, PeriodicVerification, WorkOrder

        asset = Asset.objects.create(
            asset_tag="IT-AI-001",
            name="Notebook amministrazione",
            asset_type=Asset.TYPE_NOTEBOOK,
            status=Asset.STATUS_IN_USE,
            assignment_to="Mario Rossi",
            assignment_reparto="AMM",
            assignment_location="Ufficio A",
            serial_number="SEGRETO_SERIALE",
            notes="SEGRETO_NOTE_ASSET",
            sharepoint_folder_path="SEGRETO_SHAREPOINT",
        )
        AssetAdministrativeDeadline.objects.create(
            asset=asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_CERTIFICATE,
            title="Rinnovo garanzia",
            due_date=timezone.localdate() + timedelta(days=5),
            notes="SEGRETO_NOTE_SCADENZA",
        )
        WorkOrder.objects.create(
            asset=asset,
            kind=WorkOrder.KIND_CORRECTIVE,
            status=WorkOrder.STATUS_OPEN,
            title="Controllo alimentatore",
            description="SEGRETO_DESCRIZIONE_ODL",
            resolution="SEGRETO_RISOLUZIONE_ODL",
            cost_eur=123,
        )
        verification = PeriodicVerification.objects.create(
            name="Verifica annuale",
            next_verification_date=timezone.localdate() + timedelta(days=10),
            notes="SEGRETO_NOTE_VERIFICA",
        )
        verification.assets.add(asset)
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        context = build_runtime_context(request, "riepilogo asset con scadenze e manutenzioni")

        self.assertIn("tool:assets:riepilogo", context.sources)
        self.assertIn(asset.asset_tag, context.text)
        self.assertIn("Rinnovo garanzia", context.text)
        self.assertIn("Controllo alimentatore", context.text)
        self.assertIn("Verifica annuale", context.text)
        self.assertNotIn("SEGRETO_SERIALE", context.text)
        self.assertNotIn("SEGRETO_NOTE_ASSET", context.text)
        self.assertNotIn("SEGRETO_SHAREPOINT", context.text)
        self.assertNotIn("SEGRETO_DESCRIZIONE_ODL", context.text)
        self.assertNotIn("SEGRETO_RISOLUZIONE_ODL", context.text)
        self.assertNotIn("123", context.text)
        self.assertEqual(context.audit["tools"][0]["tool"], "assets_summary")

    def test_runtime_assets_context_limits_personal_scope(self):
        from assets.models import Asset

        User = get_user_model()
        user = User.objects.create_user(
            username="asset.owner",
            email="asset.owner@example.local",
            password="password",
        )
        owned = Asset.objects.create(
            asset_tag="IT-OWN-001",
            name="PC assegnato",
            asset_type=Asset.TYPE_PC,
            assignment_to=user.username,
        )
        other = Asset.objects.create(
            asset_tag="IT-OTH-001",
            name="PC altro utente",
            asset_type=Asset.TYPE_PC,
            assignment_to="Altro Utente",
        )
        request = SimpleNamespace(user=user, path="/assistente-ai/")

        with patch("assets.views._is_assets_admin", return_value=False), patch(
            "core.acl.user_can_modulo_action", return_value=True
        ), patch("ai_assistant.tools.get_legacy_user", return_value=None):
            context = build_runtime_context(request, "quali asset miei sono assegnati a me?")

        self.assertIn(owned.asset_tag, context.text)
        self.assertNotIn(other.asset_tag, context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "personal")

    def test_runtime_assets_context_denies_without_module_permission(self):
        User = get_user_model()
        user = User.objects.create_user(username="asset.denied", password="password")
        request = SimpleNamespace(user=user, path="/assistente-ai/")

        with patch("assets.views._is_assets_admin", return_value=False), patch(
            "core.acl.user_can_modulo_action", return_value=False
        ):
            context = build_runtime_context(request, "mostra asset in riparazione")

        self.assertIn("tool:assets:accesso-negato", context.sources)
        self.assertIn("non ha accesso all'inventario Assets", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_dpi_context_limits_regular_user_to_own_requests(self):
        from dpi.models import CategoriaDPI, ConsegnaDPI, RichiestaDPI, StatoRichiesta

        User = get_user_model()
        user = User.objects.create_user(username="dpi.user", email="dpi.user@example.local", password="password")
        other_user = User.objects.create_user(username="dpi.other", email="dpi.other@example.local", password="password")
        categoria = CategoriaDPI.objects.create(nome="Guanti", vita_utile_giorni=180)
        own = RichiestaDPI.objects.create(
            categoria=categoria,
            stato=StatoRichiesta.CONSEGNATA,
            quantita=2,
            motivazione="SEGRETO_MOTIVAZIONE",
            note_gestione="SEGRETO_NOTE_GESTIONE",
            richiedente_nome="Mario Rossi",
            richiedente_email=user.email,
            created_by=user,
        )
        ConsegnaDPI.objects.create(
            richiesta=own,
            data_consegna=timezone.localdate(),
            data_scadenza_stimata=timezone.localdate() + timedelta(days=20),
            note_consegna="SEGRETO_NOTE_CONSEGNA",
            firma_immagine="SEGRETO_FIRMA_BASE64",
        )
        other = RichiestaDPI.objects.create(
            categoria=categoria,
            stato=StatoRichiesta.INVIATA,
            richiedente_nome="Altro Utente",
            created_by=other_user,
        )
        request = SimpleNamespace(user=user, path="/assistente-ai/")

        with patch("dpi.views._is_gestore", return_value=False):
            context = build_runtime_context(request, "mostra le mie richieste dpi e consegne")

        self.assertIn("tool:dpi:riepilogo", context.sources)
        self.assertIn(own.numero, context.text)
        self.assertNotIn(other.numero, context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "personale")
        self.assertNotIn("SEGRETO_MOTIVAZIONE", context.text)
        self.assertNotIn("SEGRETO_NOTE_GESTIONE", context.text)
        self.assertNotIn("SEGRETO_NOTE_CONSEGNA", context.text)
        self.assertNotIn("SEGRETO_FIRMA_BASE64", context.text)

    def test_runtime_dpi_context_manager_sees_requesters_without_sensitive_fields(self):
        from dpi.models import CategoriaDPI, RichiestaDPI, StatoRichiesta

        categoria = CategoriaDPI.objects.create(nome="Elmetto")
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria,
            stato=StatoRichiesta.INVIATA,
            richiedente_nome="Luigi Verdi",
            motivazione="SEGRETO_MOTIVAZIONE_GESTORE",
            note_gestione="SEGRETO_NOTE_GESTORE",
            created_by=self.user,
        )
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("dpi.views._is_gestore", return_value=True):
            context = build_runtime_context(request, "riepilogo richieste dpi aperte")

        self.assertIn(richiesta.numero, context.text)
        self.assertIn("richiedente Luigi Verdi", context.text)
        self.assertNotIn("SEGRETO_MOTIVAZIONE_GESTORE", context.text)
        self.assertNotIn("SEGRETO_NOTE_GESTORE", context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "gestione")

    def test_runtime_dpi_context_denies_anonymous_user(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=False), path="/assistente-ai/")

        context = build_runtime_context(request, "mostra richieste dpi")

        self.assertIn("tool:dpi:accesso-negato", context.sources)
        self.assertIn("non e' autenticato", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_anomalie_context_manager_sees_open_authorized_rows(self):
        from anomalie.models import AnomalieAccessLevel

        rows = [
            {
                "id": 10,
                "sharepoint_item_id": 100,
                "ex_op_nominativo": "OP-100",
                "seriale": "SER-1",
                "pezzo_recuperato": 1,
                "aprire_rdc": 1,
                "numero_rdc": "RDC-5",
                "segnalare_cliente": 0,
                "chiudere": 0,
                "avanzamento": "In verifica",
                "modified_datetime": "2026-05-13 08:00",
                "title": "OP-100",
                "part_number": "PN-100",
                "capocomessa": "Mario Rossi",
                "incaricato": "Luigi Verdi",
            }
        ]
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("anomalie.views._has_table", return_value=True), patch(
            "anomalie.views._request_anomalie_global_access_level",
            return_value=AnomalieAccessLevel.READ_ALL,
        ), patch("anomalie.views._fetch_all_dict", return_value=rows):
            context = build_runtime_context(request, "riepilogo anomalie aperte")

        self.assertIn("tool:anomalie:riepilogo", context.sources)
        self.assertIn("Anomalia 10", context.text)
        self.assertIn("PN-100", context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "gestione")

    def test_runtime_anomalie_context_regular_user_filters_assigned_ops(self):
        from anomalie.models import AnomalieAccessLevel

        rows = [
            {
                "id": 11,
                "ex_op_nominativo": "OP-TEAM",
                "seriale": "SER-A",
                "chiudere": 0,
                "avanzamento": "Aperta",
                "capocomessa": "Mario Rossi",
                "incaricato": "Luigi Verdi",
            },
            {
                "id": 12,
                "ex_op_nominativo": "OP-ALTRO",
                "seriale": "SER-B",
                "chiudere": 0,
                "avanzamento": "Aperta",
                "capocomessa": "Altro Utente",
                "incaricato": "",
            },
        ]
        user = get_user_model().objects.create_user(username="mario.rossi", password="password")
        request = SimpleNamespace(user=user, path="/assistente-ai/")

        with patch("anomalie.views._has_table", return_value=True), patch(
            "anomalie.views._request_anomalie_global_access_level",
            return_value=AnomalieAccessLevel.NONE,
        ), patch("anomalie.views._fetch_all_dict", return_value=rows), patch(
            "anomalie.views._current_user_name_norms", return_value={"mario rossi"}
        ), patch(
            "anomalie.views._current_user_identity", return_value={"name_norm": "mario rossi"}
        ):
            context = build_runtime_context(request, "mostra le mie anomalie aperte")

        self.assertIn("Anomalia 11", context.text)
        self.assertNotIn("Anomalia 12", context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "in_carico")

    def test_runtime_anomalie_context_does_not_include_sensitive_fields(self):
        from anomalie.models import AnomalieAccessLevel

        rows = [
            {
                "id": 13,
                "ex_op_nominativo": "OP-PRIVACY",
                "seriale": "SER-P",
                "chiudere": 0,
                "avanzamento": "Aperta",
                "descrizione": "SEGRETO_DESC",
                "note_capocommessa": "SEGRETO_NOTE",
                "created_by": "SEGRETO_CREATED_BY",
                "modified_by": "SEGRETO_MODIFIED_BY",
                "attachment_path": "SEGRETO_PATH",
                "capocomessa": "Mario Rossi",
            }
        ]
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("anomalie.views._has_table", return_value=True), patch(
            "anomalie.views._request_anomalie_global_access_level",
            return_value=AnomalieAccessLevel.READ_ALL,
        ), patch("anomalie.views._fetch_all_dict", return_value=rows):
            context = build_runtime_context(request, "riepilogo anomalie")

        self.assertIn("Anomalia 13", context.text)
        self.assertNotIn("SEGRETO_DESC", context.text)
        self.assertNotIn("SEGRETO_NOTE", context.text)
        self.assertNotIn("SEGRETO_CREATED_BY", context.text)
        self.assertNotIn("SEGRETO_MODIFIED_BY", context.text)
        self.assertNotIn("SEGRETO_PATH", context.text)

    def test_runtime_anomalie_context_denies_anonymous_user(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=False), path="/assistente-ai/")

        context = build_runtime_context(request, "mostra anomalie aperte")

        self.assertIn("tool:anomalie:accesso-negato", context.sources)
        self.assertIn("non e' autenticato", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_procedure_context_limits_regular_user_to_own_assignments(self):
        from procedure_refresh.models import (
            AssignmentStatus,
            CampaignStatus,
            ProcedureAssignment,
            ProcedureCampaign,
            ProcedureDocument,
            ProcedureQuiz,
            ProcedureQuizAttempt,
            ProcedureRevision,
        )

        User = get_user_model()
        user = User.objects.create_user(username="procedure.user", password="password")
        other_user = User.objects.create_user(username="procedure.other", password="password")
        today = timezone.localdate()
        document = ProcedureDocument.objects.create(
            code="MT-100",
            title="Procedura controllo qualità",
            document_type="MT",
            description="SEGRETO_DESCRIZIONE_DOCUMENTO",
        )
        revision = ProcedureRevision.objects.create(
            document=document,
            revision_code="Rev.1",
            revision_date=today,
            effective_date=today,
            source_url="SEGRETO_URL_SHAREPOINT",
            source_path="SEGRETO_PATH_FILE",
            file_name="SEGRETO_FILE_NAME.pdf",
            file_hash="SEGRETO_HASH",
            is_current=True,
        )
        campaign = ProcedureCampaign.objects.create(
            name="Refresh reparto qualità",
            description="SEGRETO_DESCRIZIONE_CAMPAGNA",
            status=CampaignStatus.PUBLISHED,
            start_date=today,
            due_date=today + timedelta(days=7),
        )
        own = ProcedureAssignment.objects.create(
            campaign=campaign,
            revision=revision,
            user=user,
            due_date=today + timedelta(days=7),
            status=AssignmentStatus.READ_CONFIRMED,
            read_confirmed_flag=True,
            read_confirmed_at=timezone.now(),
            user_note="SEGRETO_NOTA_UTENTE",
            manager_note="SEGRETO_NOTA_MANAGER",
            ip_address="127.0.0.1",
            user_agent="SEGRETO_USER_AGENT",
        )
        other_document = ProcedureDocument.objects.create(
            code="MT-999",
            title="Procedura non autorizzata",
            document_type="MT",
        )
        other_revision = ProcedureRevision.objects.create(
            document=other_document,
            revision_code="Rev.X",
            revision_date=today,
            effective_date=today,
            source_url="SEGRETO_URL_ALTRO",
            file_name="altro.pdf",
        )
        other_campaign = ProcedureCampaign.objects.create(
            name="Refresh non autorizzato",
            status=CampaignStatus.PUBLISHED,
            start_date=today,
            due_date=today + timedelta(days=7),
        )
        ProcedureAssignment.objects.create(
            campaign=other_campaign,
            revision=other_revision,
            user=other_user,
            due_date=today + timedelta(days=7),
            status=AssignmentStatus.ASSIGNED,
        )
        quiz = ProcedureQuiz.objects.create(
            revision=revision,
            title="Quiz sicurezza",
            questions=[{"text": "SEGRETO_DOMANDA", "options": ["SEGRETO_OPZIONE"], "correct_index": 0}],
        )
        ProcedureQuizAttempt.objects.create(
            quiz=quiz,
            assignment=own,
            user=user,
            answers=[{"question": "SEGRETO_RISPOSTA"}],
            score=1,
            total_questions=1,
            ip_address="127.0.0.1",
            user_agent="SEGRETO_AGENT_QUIZ",
        )
        request = SimpleNamespace(user=user, path="/assistente-ai/")

        with patch("procedure_refresh.views._is_manager", return_value=False):
            context = build_runtime_context(request, "mostra le mie procedure e quiz")

        self.assertIn("tool:procedure_refresh:riepilogo", context.sources)
        self.assertIn("MT-100", context.text)
        self.assertIn("Procedura controllo qualità", context.text)
        self.assertIn("esito 1/1", context.text)
        self.assertNotIn("Procedura non autorizzata", context.text)
        self.assertNotIn("Refresh non autorizzato", context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "personal")
        self.assertEqual(context.audit["tools"][0]["assignment_count"], 1)
        self.assertNotIn("SEGRETO_DESCRIZIONE_DOCUMENTO", context.text)
        self.assertNotIn("SEGRETO_DESCRIZIONE_CAMPAGNA", context.text)
        self.assertNotIn("SEGRETO_URL_SHAREPOINT", context.text)
        self.assertNotIn("SEGRETO_PATH_FILE", context.text)
        self.assertNotIn("SEGRETO_FILE_NAME", context.text)
        self.assertNotIn("SEGRETO_HASH", context.text)
        self.assertNotIn("SEGRETO_NOTA_UTENTE", context.text)
        self.assertNotIn("SEGRETO_NOTA_MANAGER", context.text)
        self.assertNotIn("SEGRETO_USER_AGENT", context.text)
        self.assertNotIn("SEGRETO_DOMANDA", context.text)
        self.assertNotIn("SEGRETO_OPZIONE", context.text)
        self.assertNotIn("SEGRETO_RISPOSTA", context.text)

    def test_runtime_procedure_context_manager_sees_campaign_aggregates(self):
        from procedure_refresh.models import (
            AssignmentStatus,
            CampaignStatus,
            ProcedureAssignment,
            ProcedureCampaign,
            ProcedureCampaignDocument,
            ProcedureDocument,
            ProcedureRevision,
        )

        User = get_user_model()
        user = User.objects.create_user(username="procedure.manager.user", password="password")
        today = timezone.localdate()
        document = ProcedureDocument.objects.create(code="MTSI-200", title="Procedura laser", document_type="MTSI")
        revision = ProcedureRevision.objects.create(
            document=document,
            revision_code="Rev.2",
            revision_date=today,
            effective_date=today,
            source_url="SEGRETO_URL_MANAGER",
            file_name="laser.pdf",
        )
        campaign = ProcedureCampaign.objects.create(
            name="Campagna laser",
            description="SEGRETO_DESCRIZIONE_MANAGER",
            status=CampaignStatus.PUBLISHED,
            start_date=today,
            due_date=today + timedelta(days=3),
        )
        ProcedureCampaignDocument.objects.create(campaign=campaign, revision=revision)
        ProcedureAssignment.objects.create(
            campaign=campaign,
            revision=revision,
            user=user,
            status=AssignmentStatus.READ_CONFIRMED,
            read_confirmed_flag=True,
        )
        ProcedureAssignment.objects.create(
            campaign=campaign,
            revision=revision,
            user=self.user,
            due_date=today - timedelta(days=1),
            status=AssignmentStatus.OVERDUE,
            user_note="SEGRETO_NOTA_REPORT",
        )
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("procedure_refresh.views._is_manager", return_value=True):
            context = build_runtime_context(request, "riepilogo campagne procedure e prese visione")

        self.assertIn("tool:procedure_refresh:riepilogo", context.sources)
        self.assertIn("Campagna laser", context.text)
        self.assertIn("documenti 1", context.text)
        self.assertIn("assegnazioni 2", context.text)
        self.assertIn("confermate 1", context.text)
        self.assertIn("scadute 1", context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "manager")
        self.assertNotIn("SEGRETO_DESCRIZIONE_MANAGER", context.text)
        self.assertNotIn("SEGRETO_URL_MANAGER", context.text)
        self.assertNotIn("SEGRETO_NOTA_REPORT", context.text)

    def test_runtime_procedure_context_denies_anonymous_user(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=False), path="/assistente-ai/")

        context = build_runtime_context(request, "mostra procedure refresh")

        self.assertIn("tool:procedure_refresh:accesso-negato", context.sources)
        self.assertIn("non e' autenticato", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_notizie_context_lists_visible_news_without_body_or_attachments(self):
        from notizie.models import (
            COMPLIANCE_APERTO,
            STATO_PUBBLICATA,
            Notizia,
            NotiziaAllegato,
            NotiziaAudience,
            NotiziaLettura,
        )

        visible = Notizia.objects.create(
            titolo="Comunicazione sicurezza",
            corpo="SEGRETO_CORPO_NOTIZIA",
            stato=STATO_PUBBLICATA,
            versione=2,
            hash_versione="SEGRETO_HASH_NOTIZIA",
            obbligatoria=True,
            pubblicato_il=timezone.now(),
        )
        NotiziaAudience.objects.create(notizia=visible, legacy_role_id=5)
        NotiziaAllegato.objects.create(
            notizia=visible,
            nome_file="SEGRETO_NOME_FILE.pdf",
            url_esterno="SEGRETO_URL_ALLEGATO",
            hash_file="SEGRETO_HASH_ALLEGATO",
        )
        NotiziaLettura.objects.create(
            notizia=visible,
            legacy_user_id=77,
            versione_letta=2,
            hash_versione_letta="SEGRETO_HASH_LETTURA",
            opened_at=timezone.now(),
        )
        hidden = Notizia.objects.create(
            titolo="Comunicazione non visibile",
            corpo="SEGRETO_CORPO_NASCOSTO",
            stato=STATO_PUBBLICATA,
            versione=1,
            pubblicato_il=timezone.now(),
        )
        NotiziaAudience.objects.create(notizia=hidden, legacy_role_id=9)
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("notizie.views._get_legacy_role_id", return_value=5), patch(
            "notizie.views._get_legacy_user_id", return_value=77
        ), patch("notizie.views._is_admin_or_hr", return_value=False):
            context = build_runtime_context(request, "mostra notizie obbligatorie da confermare")

        self.assertIn("tool:notizie:riepilogo", context.sources)
        self.assertIn("Comunicazione sicurezza", context.text)
        self.assertIn("obbligatoria", context.text)
        self.assertIn(f"compliance utente {COMPLIANCE_APERTO}", context.text)
        self.assertIn("allegati 1", context.text)
        self.assertNotIn("Comunicazione non visibile", context.text)
        self.assertEqual(context.audit["tools"][0]["scope"], "visible")
        self.assertEqual(context.audit["tools"][0]["row_count"], 1)
        self.assertNotIn("SEGRETO_CORPO_NOTIZIA", context.text)
        self.assertNotIn("SEGRETO_HASH_NOTIZIA", context.text)
        self.assertNotIn("SEGRETO_NOME_FILE", context.text)
        self.assertNotIn("SEGRETO_URL_ALLEGATO", context.text)
        self.assertNotIn("SEGRETO_HASH_ALLEGATO", context.text)
        self.assertNotIn("SEGRETO_HASH_LETTURA", context.text)
        self.assertNotIn("77", context.text)

    def test_runtime_notizie_context_denies_anonymous_user(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=False), path="/assistente-ai/")

        context = build_runtime_context(request, "mostra notizie pubblicate")

        self.assertIn("tool:notizie:accesso-negato", context.sources)
        self.assertIn("non e' autenticato", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_sicurezza_context_returns_only_aggregates(self):
        from diario_preposto.models import SegnalazioneAllegato, SegnalazionePreposto
        from rilevazione_incidenti.models import RilevazioneIncidente, TipoEventoSicurezza

        now = timezone.now()
        segnalazione = SegnalazionePreposto.objects.create(
            titolo="SEGRETO_TITOLO_DIARIO",
            descrizione="SEGRETO_DESCRIZIONE_DIARIO",
            data_segnalazione=now,
            preposto="SEGRETO_PREPOSTO",
            chi_segnala="SEGRETO_SEGNALANTE",
            creato_da=self.user,
        )
        SegnalazioneAllegato.objects.create(
            segnalazione=segnalazione,
            nome_file="SEGRETO_ALLEGATO_DIARIO.pdf",
            file="diario_preposto/allegati/SEGRETO_ALLEGATO_DIARIO.pdf",
        )
        RilevazioneIncidente.objects.create(
            nominativo="SEGRETO_NOMINATIVO",
            tipologia_scheda="Near Miss",
            tipo_evento=TipoEventoSicurezza.NEAR_MISS,
            reparto="CNC",
            data_segnalazione=now,
            descrizione_attivita="SEGRETO_ATTIVITA",
            descrizione_avvenimento="SEGRETO_AVVENIMENTO",
            persone_coinvolte="SEGRETO_PERSONE",
            causa_evento="SEGRETO_CAUSA",
            note_preposto="SEGRETO_NOTE_PREPOSTO",
            note_rspp="SEGRETO_NOTE_RSPP",
            why_1="SEGRETO_5WHY",
            partecipanti="SEGRETO_PARTECIPANTI",
        )
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("diario_preposto.views._can_write", return_value=True), patch(
            "diario_preposto.views._can_manage_settings", return_value=False
        ), patch("rilevazione_incidenti.views._can_create", return_value=True), patch(
            "rilevazione_incidenti.views._can_manage_rspp", return_value=False
        ), patch("rilevazione_incidenti.views._can_manage_settings", return_value=False), patch(
            "rilevazione_incidenti.services.active_headcount", return_value=100
        ):
            context = build_runtime_context(request, "mostra kpi sicurezza diario preposto e incidenti")

        self.assertIn("tool:sicurezza:riepilogo", context.sources)
        self.assertIn("Segnalazioni anno corrente: 1", context.text)
        self.assertIn("Segnalazioni con almeno un allegato: 1", context.text)
        self.assertIn("near miss: 1", context.text)
        self.assertIn("CNC: 1", context.text)
        self.assertEqual(context.audit["tools"][0]["diario_year_count"], 1)
        self.assertEqual(context.audit["tools"][0]["near_miss_count"], 1)
        self.assertNotIn("SEGRETO_TITOLO_DIARIO", context.text)
        self.assertNotIn("SEGRETO_DESCRIZIONE_DIARIO", context.text)
        self.assertNotIn("SEGRETO_PREPOSTO", context.text)
        self.assertNotIn("SEGRETO_SEGNALANTE", context.text)
        self.assertNotIn("SEGRETO_ALLEGATO_DIARIO", context.text)
        self.assertNotIn("SEGRETO_NOMINATIVO", context.text)
        self.assertNotIn("SEGRETO_ATTIVITA", context.text)
        self.assertNotIn("SEGRETO_AVVENIMENTO", context.text)
        self.assertNotIn("SEGRETO_PERSONE", context.text)
        self.assertNotIn("SEGRETO_CAUSA", context.text)
        self.assertNotIn("SEGRETO_NOTE_PREPOSTO", context.text)
        self.assertNotIn("SEGRETO_NOTE_RSPP", context.text)
        self.assertNotIn("SEGRETO_5WHY", context.text)
        self.assertNotIn("SEGRETO_PARTECIPANTI", context.text)

    def test_runtime_sicurezza_context_denies_without_permissions(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        with patch("diario_preposto.views._can_write", return_value=False), patch(
            "diario_preposto.views._can_manage_settings", return_value=False
        ), patch("rilevazione_incidenti.views._can_create", return_value=False), patch(
            "rilevazione_incidenti.views._can_manage_rspp", return_value=False
        ), patch("rilevazione_incidenti.views._can_manage_settings", return_value=False):
            context = build_runtime_context(request, "riepilogo sicurezza incidenti")

        self.assertIn("tool:sicurezza:accesso-negato", context.sources)
        self.assertIn("non ha permessi", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_cross_domain_today_router_prioritizes_operational_tools(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        def fake_context(label, source, tool, priority_text):
            return RuntimeContext(
                text=f"DATI LIVE PORTALE - {label}\n{priority_text}",
                sources=(source,),
                audit={"tool": tool, "allowed": True, "row_count": 1},
            )

        with patch(
            "ai_assistant.tools._notizie_context",
            return_value=fake_context("NOTIZIE", "tool:notizie:riepilogo", "notizie_summary", "Notizia obbligatoria"),
        ), patch(
            "ai_assistant.tools._procedure_context",
            return_value=fake_context(
                "PROCEDURE",
                "tool:procedure_refresh:riepilogo",
                "procedure_refresh_summary",
                "Procedura da leggere",
            ),
        ), patch(
            "ai_assistant.tools._dpi_context",
            return_value=fake_context("DPI", "tool:dpi:riepilogo", "dpi_summary", "DPI in scadenza"),
        ), patch(
            "ai_assistant.tools._assets_context",
            return_value=fake_context("ASSETS", "tool:assets:riepilogo", "assets_summary", "Asset in scadenza"),
        ), patch(
            "ai_assistant.tools._ticket_context",
            return_value=fake_context("TICKET", "tool:tickets:riepilogo", "tickets_summary", "Ticket urgente"),
        ), patch(
            "ai_assistant.tools._tasks_context",
            return_value=fake_context("TASKS", "tool:tasks:riepilogo", "tasks_summary", "Task in ritardo"),
        ):
            context = build_runtime_context(request, "cosa devo fare oggi?")

        self.assertEqual(context.sources[0], "tool:runtime:router")
        self.assertIn("tool:procedure_refresh:riepilogo", context.sources)
        self.assertIn("tool:notizie:riepilogo", context.sources)
        self.assertIn("tool:tickets:riepilogo", context.sources)
        self.assertIn("Priorita risposta", context.text)
        self.assertLess(context.text.index("PROCEDURE"), context.text.index("TICKET"))
        self.assertLess(context.text.index("TICKET"), context.text.index("TASKS"))
        self.assertEqual(context.audit["tool_count"], 7)
        self.assertEqual(context.audit["tools"][0]["tool"], "runtime_router")
        self.assertFalse(context.audit["truncated"])

    def test_runtime_cross_domain_router_does_not_steal_explicit_task_prompt(self):
        from tasks.models import Task, TaskStatus

        task = Task.objects.create(
            title="Preparare priorità giornaliere",
            status=TaskStatus.TODO,
            due_date=timezone.localdate(),
            created_by=self.user,
            assigned_to=self.user,
        )
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        def has_task_permission(_request, action_code):
            return action_code in {"tasks_view", "tasks_admin"}

        with patch("tasks.views._has_task_permission", side_effect=has_task_permission):
            context = build_runtime_context(request, "mostra cosa devo fare oggi sui task")

        self.assertIn("tool:tasks:riepilogo", context.sources)
        self.assertNotIn("tool:runtime:router", context.sources)
        self.assertIn(task.title, context.text)

    def test_runtime_context_global_limit_truncates_text_and_audit(self):
        long_context = RuntimeContext(
            text="\n".join(f"- riga {index}" for index in range(500)),
            sources=("tool:test:lungo",),
            audit={"tool": "test_long", "allowed": True},
        )

        context = _merge_contexts([long_context])

        self.assertIn("Contesto runtime troncato", context.text)
        self.assertTrue(context.audit["truncated"])
        self.assertLessEqual(context.audit["context_lines"], context.audit["max_lines"] + 2)
        self.assertIn("tool:test:lungo", context.sources)

    def test_runtime_context_reports_missing_live_tool_for_deferred_hr_domains(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        context = build_runtime_context(request, "mostra timbrature e cartellini")

        self.assertIn("tool:runtime:non-disponibile", context.sources)
        self.assertIn("Timbri/Presenze", context.text)
        self.assertIn("nessun tool live AI", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])
        self.assertEqual(context.audit["tools"][0]["tool"], "runtime_unavailable")

    def test_runtime_anagrafica_context_lists_privacy_consent_for_authorized_user(self):
        from anagrafica.models import DipendenteAnagraficaAziendale

        request = SimpleNamespace(user=self.user, path="/assistente-ai/")
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=10,
            area="Produzione",
            ruolo_aziendale="Operatore",
            consenso_privacy=True,
            data_consenso_privacy=date(2026, 5, 1),
        )
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=11,
            area="Produzione",
            ruolo_aziendale="Magazzino",
            consenso_privacy=False,
        )
        rows = [
            {
                "id": 10,
                "nome": "Mario",
                "cognome": "Rossi",
                "matricola": "M10",
                "reparto": "Produzione",
                "mansione": "Operatore",
                "attivo": True,
            },
            {
                "id": 11,
                "nome": "Luigi",
                "cognome": "Bianchi",
                "matricola": "M11",
                "reparto": "Produzione",
                "mansione": "Magazzino",
                "attivo": True,
            },
        ]

        with patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=rows):
            context = build_runtime_context(
                request,
                "elenco dipendenti che hanno fornito il consenso privacy",
            )

        self.assertIn("tool:anagrafica:dipendenti", context.sources)
        self.assertNotIn("tool:runtime:non-disponibile", context.sources)
        self.assertIn("Mario Rossi", context.text)
        self.assertNotIn("Luigi Bianchi", context.text)
        self.assertIn("consenso privacy: si", context.text)
        self.assertIn("01-05-2026", context.text)
        self.assertEqual(context.audit["tools"][0]["tool"], "anagrafica_summary")
        self.assertTrue(context.audit["tools"][0]["allowed"])

    def test_runtime_anagrafica_context_lists_top_ferie_residue(self):
        from anagrafica.models import SaldoCedolino

        request = SimpleNamespace(user=self.user, path="/assistente-ai/")
        period = date(2026, 5, 31)
        fixtures = [
            (10, "RSSMRA80A01H501A", "10.00"),
            (11, "BNCLGU80A01H501B", "32.50"),
            (12, "VRDGPP80A01H501C", "5.00"),
            (13, "NRILRA80A01H501D", "48.25"),
            (14, "FRNPLA80A01H501E", "22.00"),
            (15, "GLLSRA80A01H501F", "18.00"),
        ]
        for legacy_id, tax_code, ferie_residui in fixtures:
            SaldoCedolino.objects.create(
                tax_code=tax_code,
                legacy_anagrafica_id=legacy_id,
                data_competenza=period,
                ferie_residui=ferie_residui,
            )
        rows = [
            {"id": 10, "nome": "Mario", "cognome": "Rossi", "reparto": "Produzione"},
            {"id": 11, "nome": "Luigi", "cognome": "Bianchi", "reparto": "Magazzino"},
            {"id": 12, "nome": "Giuseppe", "cognome": "Verdi", "reparto": "Qualita"},
            {"id": 13, "nome": "Laura", "cognome": "Neri", "reparto": "Produzione"},
            {"id": 14, "nome": "Paolo", "cognome": "Ferrari", "reparto": "Ufficio"},
            {"id": 15, "nome": "Sara", "cognome": "Galli", "reparto": "Ufficio"},
        ]

        with patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=rows):
            context = build_runtime_context(
                request,
                "elencami i primi 5 dipendenti con maggior numero di ore ferie residue",
            )

        self.assertIn("tool:anagrafica:ratei", context.sources)
        self.assertIn("Ferie residue", context.text)
        self.assertIn("31-05-2026", context.text)
        self.assertIn("Laura Neri", context.text)
        self.assertIn("48.25 ore", context.text)
        self.assertIn("Luigi Bianchi", context.text)
        self.assertNotIn("Giuseppe Verdi", context.text)
        self.assertEqual(context.audit["tools"][0]["ratei_metric"], "ferie_residui")
        self.assertEqual(context.audit["tools"][0]["shown_count"], 5)

    def test_runtime_anagrafica_context_lists_named_ferie_residue(self):
        from anagrafica.models import SaldoCedolino

        request = SimpleNamespace(user=self.user, path="/assistente-ai/")
        period = date(2026, 5, 31)
        SaldoCedolino.objects.create(
            tax_code="SMRGIU80A01H501A",
            legacy_anagrafica_id=20,
            data_competenza=period,
            ferie_residui="18.75",
        )
        SaldoCedolino.objects.create(
            tax_code="RSSMRA80A01H501B",
            legacy_anagrafica_id=21,
            data_competenza=period,
            ferie_residui="99.00",
        )
        rows = [
            {"id": 20, "nome": "Giulia", "cognome": "Smarrella", "reparto": "Amministrazione"},
            {"id": 21, "nome": "Mario", "cognome": "Rossi", "reparto": "Produzione"},
        ]

        with patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=rows):
            context = build_runtime_context(request, "Quante ore ferie residue ha SMARRELLA?")

        tool_audit = context.audit["tools"][0]
        self.assertIn("tool:anagrafica:ratei", context.sources)
        self.assertIn("RISPOSTA DIRETTA", context.text)
        self.assertIn("Giulia Smarrella ha 18.75 ore di ferie residue", context.text)
        self.assertNotIn("Mario Rossi: 99.00 ore", context.text)
        self.assertEqual(tool_audit["name_filter"], "SMARRELLA")
        self.assertEqual(tool_audit["row_count"], 1)
        self.assertEqual(tool_audit["shown_count"], 1)

    def test_runtime_anagrafica_context_converts_named_ferie_to_days_when_requested(self):
        from anagrafica.models import SaldoCedolino

        request = SimpleNamespace(user=self.user, path="/assistente-ai/")
        period = date(2026, 5, 31)
        SaldoCedolino.objects.create(
            tax_code="SMRGIU80A01H501A",
            legacy_anagrafica_id=20,
            data_competenza=period,
            ferie_residui="15.00",
        )
        rows = [{"id": 20, "nome": "Giulia", "cognome": "Smarrella", "reparto": "Amministrazione"}]

        with patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=rows):
            context = build_runtime_context(request, "Quanti giorni di ferie residue ha SMARRELLA?")

        self.assertIn("Giulia Smarrella ha 15.00 ore (2.00 giorni a 7.5 ore/giorno)", context.text)

    def test_runtime_anagrafica_context_denies_user_without_hr_permission(self):
        user = get_user_model().objects.create_user(username="ai.base", password="password")
        request = SimpleNamespace(user=user, path="/assistente-ai/")

        context = build_runtime_context(request, "elenco dipendenti")

        self.assertIn("tool:anagrafica:accesso-negato", context.sources)
        self.assertIn("permessi Anagrafica HR", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_anagrafica_context_blocks_forbidden_hr_fields(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        context = build_runtime_context(request, "mostra codice fiscale e iban del dipendente")

        self.assertIn("tool:anagrafica:accesso-limitato", context.sources)
        self.assertIn("non espone dati HR riservati", context.text)
        self.assertFalse(context.audit["tools"][0]["allowed"])

    def test_runtime_context_audit_records_allowed_denied_and_unavailable_tools(self):
        allowed = RuntimeContext(
            text="DATI LIVE PORTALE - TASKS\n- Task visibile",
            sources=("tool:tasks:riepilogo",),
            audit={"tool": "tasks_summary", "allowed": True, "row_count": 1},
        )
        denied = RuntimeContext(
            text="DATI LIVE PORTALE - ASSETS\nEsito autorizzazione: negato.",
            sources=("tool:assets:accesso-negato",),
            audit={"tool": "assets_summary", "allowed": False, "reason": "missing_assets_list"},
        )
        unavailable = RuntimeContext(
            text="DATI LIVE PORTALE - TOOL NON DISPONIBILE\nDominio richiesto: Timbri/Presenze.",
            sources=("tool:runtime:non-disponibile",),
            audit={"tool": "runtime_unavailable", "allowed": False, "reason": "missing_live_tool_privacy_review"},
        )

        context = _merge_contexts([denied, unavailable, allowed])

        tools = context.audit["tools"]
        self.assertEqual([tool["tool"] for tool in tools], ["assets_summary", "tasks_summary", "runtime_unavailable"])
        self.assertEqual(context.audit["tool_count"], 3)
        self.assertIn("tool:assets:accesso-negato", context.sources)
        self.assertIn("tool:runtime:non-disponibile", context.sources)
        self.assertFalse(tools[0]["allowed"])
        self.assertTrue(tools[1]["allowed"])
        self.assertFalse(tools[2]["allowed"])

    def test_runtime_context_can_merge_multiple_tools(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")
        nav_item = SimpleNamespace(label="Assenze", href="/assenze/", legacy_url="/assenze/", coming=False)
        with patch("core.context_processors.legacy_nav", return_value={"nav_items": [nav_item]}), patch(
            "assenze.views._assenze_permissions",
            return_value={"group": "UTENTI", "can_view_calendar": False},
        ):
            context = build_runtime_context(request, "quali moduli ho e chi e' assente domani?")

        self.assertIn("tool:portale:moduli", context.sources)
        self.assertIn("tool:assenze:accesso-negato", context.sources)
        self.assertEqual(context.audit["tool_count"], 2)

    def test_api_chat_passes_runtime_context_and_sources(self):
        self.client.force_login(self.user)
        with patch("ai_assistant.views.build_runtime_context") as mocked_context, patch(
            "ai_assistant.views.chat_with_ollama"
        ) as mocked_chat:
            mocked_context.return_value.text = "Mario Rossi: Ferie"
            mocked_context.return_value.sources = ("tool:assenze:periodo",)
            mocked_context.return_value.audit = {"tool": "assenze_periodo", "allowed": True}
            mocked_chat.return_value = OllamaChatResult(content="Mario Rossi e' assente.", model="llama3.1", done=True)
            response = self.client.post(
                reverse("ai_assistant:api_chat"),
                data='{"message":"chi e assente domani"}',
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        mocked_chat.assert_called_once_with(
            "chi e assente domani",
            history=None,
            runtime_context="Mario Rossi: Ferie",
            user_preferences={},
        )
        self.assertEqual(response.json()["sources"], ["tool:assenze:periodo"])

    def test_api_chat_sanitizes_and_passes_preferences(self):
        self.client.force_login(self.user)
        with patch("ai_assistant.views.build_runtime_context") as mocked_context, patch(
            "ai_assistant.views.chat_with_ollama"
        ) as mocked_chat:
            mocked_context.return_value.text = ""
            mocked_context.return_value.sources = ()
            mocked_context.return_value.audit = {}
            mocked_chat.return_value = OllamaChatResult(content="Ok", model="llama3.1", done=True)
            response = self.client.post(
                reverse("ai_assistant:api_chat"),
                data=json.dumps(
                    {
                        "message": "rispondi",
                        "preferences": {
                            "style": "dettagliato",
                            "show_limits": True,
                            "bad": "ignored",
                        },
                    }
                ),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        mocked_chat.assert_called_once_with(
            "rispondi",
            history=None,
            runtime_context="",
            user_preferences={"style": "dettagliato", "show_limits": True},
        )


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    SETUP_WIZARD_REQUIRED=False,
    AI_TOOL_ROUTING_ENABLED=False,  # routing keyword-only: test deterministico, no rete
)
class CarichiMacchinaContextTests(TestCase):
    """Tool live 'carichi macchina' (Ondata 1.2): read-only, ACL=login, soli aggregati."""

    def setUp(self):
        from decimal import Decimal

        from django.core.cache import cache

        from assets.models import Asset
        from gestione_carichi_macchina.models import Commessa, Macchina, Pianificazione

        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="carichi.user",
            email="carichi.user@example.local",
            password="password",
        )

        oggi = timezone.localdate()
        lunedi = oggi - timedelta(days=oggi.weekday())

        asset_a = Asset.objects.create(asset_tag="MZAI1", name="Mazak AI 1", asset_type=Asset.TYPE_PC)
        asset_b = Asset.objects.create(asset_tag="DMAI2", name="DMG AI 2", asset_type=Asset.TYPE_PC)
        self.mac_a = Macchina.objects.create(
            asset=asset_a, categoria=Macchina.CAT_5AXIS, ore_giorno_disponibili=Decimal("8.0")
        )
        self.mac_b = Macchina.objects.create(
            asset=asset_b, categoria=Macchina.CAT_TORNI, ore_giorno_disponibili=Decimal("8.0")
        )

        # Dato "sensibile" di commessa: NON deve mai comparire nell'output del tool.
        self.commessa = Commessa.objects.create(
            numero="OP-SEGRETO", nome="SEGRETO_COMMESSA", cliente="SEGRETO_CLIENTE"
        )
        # Carico solo sulla macchina A (24h nella settimana) -> piu' satura di B (0h).
        Pianificazione.objects.create(
            macchina=self.mac_a, data=lunedi, ore=Decimal("16.00"), commessa=self.commessa
        )
        Pianificazione.objects.create(
            macchina=self.mac_a, data=lunedi + timedelta(days=1), ore=Decimal("8.00")
        )

    @staticmethod
    def _carichi_audit(context):
        for entry in (context.audit or {}).get("tools", []):
            if entry.get("tool") == "carichi_macchina":
                return entry
        return None

    def test_wants_carico_gate_precision(self):
        from ai_assistant.tools import _wants_carico_context

        # Domande di carico reali -> True
        self.assertTrue(_wants_carico_context("qual e' la saturazione delle macchine questa settimana?"))
        self.assertTrue(_wants_carico_context("carico macchina MZAI1"))
        self.assertTrue(_wants_carico_context("quanto e' satura l'officina?"))
        # "macchina" da sola (manutenzione/asset) NON deve attivare il tool carichi
        self.assertFalse(_wants_carico_context("manutenzione della macchina"))
        self.assertFalse(_wants_carico_context("quali asset sono in riparazione?"))
        self.assertFalse(_wants_carico_context("mostra le mie ferie residue"))

    def test_carichi_context_aggregates_current_week(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        context = build_runtime_context(
            request, "qual e' la saturazione delle macchine questa settimana?"
        )

        self.assertIn("tool:carichi:riepilogo", context.sources)
        self.assertIn("MZAI1", context.text)
        self.assertIn("saturazione", context.text)
        self.assertIn("lavori pianificati", context.text)
        self.assertIn("2 lavori pianificati", context.text)  # n. lavori macchina A
        # Nessun dettaglio commessa/cliente nell'output del tool
        self.assertNotIn("SEGRETO_COMMESSA", context.text)
        self.assertNotIn("SEGRETO_CLIENTE", context.text)
        self.assertNotIn("OP-SEGRETO", context.text)

        audit = self._carichi_audit(context)
        self.assertIsNotNone(audit)
        self.assertTrue(audit["allowed"])
        self.assertEqual(audit["scope"], "settimana_corrente")
        self.assertEqual(audit["filtro"], "top8")

    def test_carichi_context_filters_by_cited_machine(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        context = build_runtime_context(
            request, "qual e' il carico della macchina MZAI1 questa settimana?"
        )

        self.assertIn("MZAI1", context.text)
        self.assertNotIn("DMAI2", context.text)
        audit = self._carichi_audit(context)
        self.assertIsNotNone(audit)
        self.assertEqual(audit["filtro"], "codice")

    def test_carichi_context_denies_anonymous(self):
        from django.contrib.auth.models import AnonymousUser

        request = SimpleNamespace(user=AnonymousUser(), path="/assistente-ai/")

        context = build_runtime_context(request, "qual e' la saturazione delle macchine?")

        self.assertIn("tool:carichi:accesso-negato", context.sources)
        audit = self._carichi_audit(context)
        self.assertIsNotNone(audit)
        self.assertFalse(audit["allowed"])
        self.assertEqual(audit["reason"], "anonymous")


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False)
class SgiRagLoaderTests(TestCase):
    """F1 — loader RAG del corpus documentale SGI (specifiche + procedure correnti).

    Verifica: chunk citabili (handle spec:/proc:), solo revisioni in vigore, cache
    del testo per file_hash, fail-safe su PDF assente/illeggibile, opt-out via
    setting. Estrazione PDF (pymupdf) e Ollama non vengono mai toccati dalla rete:
    il testo e' iniettato/mockato.
    """

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        clear_knowledge_cache()

    def _make_specifica_in_validita(self, *, codice, revisione, titolo, cliente="ACME", tag="timbri"):
        from gestione_specifiche import constants as C
        from gestione_specifiche.models import Specifica

        spec = Specifica.objects.create(
            codice=codice, revisione=revisione, titolo=titolo, cliente=cliente, tag=tag
        )
        # FSMField protetto: lo stato "in vigore" si imposta via update() (come l'import storico).
        Specifica.objects.filter(pk=spec.pk).update(stato=C.STATO_IN_VALIDITA)
        return Specifica.objects.get(pk=spec.pk)

    def test_sgi_loader_indexes_current_specifica_with_citable_source(self):
        self._make_specifica_in_validita(codice="MT CN 06", revisione="7", titolo="Manuale tecnico")
        pdf_text = (
            "1 Scopo\nDescrizione generale del documento.\n\n"
            "4.2 Registrazione timbri\n"
            "La registrazione dei timbri di presenza segue questa regola.\n"
        )
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_RAG_SGI_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=[],
            OLLAMA_RAG_CACHE_SECONDS=0,
            OLLAMA_RAG_MAX_CHUNKS=4,
        ), patch("ai_assistant.services._sgi_extract_specifica_text", return_value=pdf_text):
            clear_knowledge_cache()
            context = build_knowledge_context("in che documento si parla dei timbri?")

        self.assertIn("timbri", context.text.lower())
        self.assertTrue(
            any(s.startswith("spec:MT CN 06#rev7") for s in context.sources),
            msg=f"manca l'handle citabile spec:: {context.sources}",
        )
        self.assertTrue(
            any("§4.2" in s for s in context.sources),
            msg=f"la citazione deve riportare la sezione §4.2: {context.sources}",
        )

    def test_sgi_loader_excludes_non_current_specifica(self):
        from gestione_specifiche.models import Specifica

        # Resta in bozza (stato di default): non e' in vigore -> non indicizzata.
        Specifica.objects.create(codice="SPEC-BOZZA", revisione="A", titolo="Bozza timbri presenze")
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_RAG_SGI_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=[],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            clear_knowledge_cache()
            context = build_knowledge_context("timbri presenze bozza")

        self.assertFalse(
            any(s.startswith("spec:") for s in context.sources),
            msg=f"una specifica non in vigore non deve essere indicizzata: {context.sources}",
        )

    def test_sgi_loader_without_pdf_falls_back_to_metadata(self):
        # Nessun allegato -> il documento resta comunque citabile dai metadati.
        self._make_specifica_in_validita(
            codice="MT CN 09", revisione="2", titolo="Gestione presenze e timbrature", tag="presenze"
        )
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_RAG_SGI_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=[],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            clear_knowledge_cache()
            context = build_knowledge_context("gestione presenze e timbrature")

        self.assertTrue(
            any(s.startswith("spec:MT CN 09#rev2") for s in context.sources),
            msg=f"il fallback metadati deve restare citabile: {context.sources}",
        )

    def test_extract_pdf_text_is_failsafe(self):
        from ai_assistant.services import _extract_pdf_text

        # Input non-PDF / vuoto / None: mai un'eccezione, sempre stringa vuota.
        self.assertEqual(_extract_pdf_text(b"questo non e' un pdf"), "")
        self.assertEqual(_extract_pdf_text(None), "")
        self.assertEqual(_extract_pdf_text(""), "")

    def test_sgi_specifica_text_cached_by_file_hash(self):
        import io

        from ai_assistant.services import _sgi_extract_specifica_text

        class _StubAllegato:
            def __init__(self, data):
                self.data = data
                self.open_calls = 0

            def __bool__(self):
                return True

            def open(self, mode="rb"):
                self.open_calls += 1
                return io.BytesIO(self.data)

        class _StubSpec:
            pk = 4242
            updated_at = timezone.now()

            def __init__(self, allegato):
                self.allegato = allegato

        allegato = _StubAllegato(b"%PDF-1.4 byte finti")
        spec = _StubSpec(allegato)
        with override_settings(
            OLLAMA_RAG_SGI_MAX_PDF_CHARS=200000,
            OLLAMA_RAG_SGI_TEXT_CACHE_TTL=600,
        ), patch("ai_assistant.services._extract_pdf_text", return_value="TESTO ESTRATTO") as mock_extract:
            first = _sgi_extract_specifica_text(spec)
            second = _sgi_extract_specifica_text(spec)

        self.assertEqual(first, "TESTO ESTRATTO")
        self.assertEqual(second, "TESTO ESTRATTO")
        # 2a chiamata servita dalla cache: nessuna ri-estrazione ne' ri-lettura del file.
        self.assertEqual(mock_extract.call_count, 1)
        self.assertEqual(allegato.open_calls, 1)

    def test_sgi_loader_disabled_by_setting(self):
        self._make_specifica_in_validita(codice="MT CN 06", revisione="7", titolo="Manuale timbri")
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_RAG_SGI_ENABLED=False,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=[],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            clear_knowledge_cache()
            context = build_knowledge_context("timbri manuale")

        self.assertFalse(
            any(s.startswith("spec:") for s in context.sources),
            msg=f"con OLLAMA_RAG_SGI_ENABLED=False il corpus SGI non va indicizzato: {context.sources}",
        )

    def test_sgi_loader_indexes_current_procedure_metadata_only(self):
        from procedure_refresh.models import ProcedureDocument, ProcedureRevision

        doc = ProcedureDocument.objects.create(
            code="MT CN 06", title="Registrazione presenze e timbri", category="Qualita", is_active=True
        )
        ProcedureRevision.objects.create(
            document=doc, revision_code="7", revision_date=date.today(), effective_date=date.today(),
            source_type="sharepoint", source_url="https://sp.example/x", file_name="mtcn06.pdf", is_current=True,
        )
        # Documento dismesso (is_active=False): la sua revisione corrente NON va indicizzata.
        doc_off = ProcedureDocument.objects.create(code="MT CN 99", title="Documento dismesso", is_active=False)
        ProcedureRevision.objects.create(
            document=doc_off, revision_code="1", revision_date=date.today(), effective_date=date.today(),
            source_type="sharepoint", source_url="https://sp.example/y", file_name="off.pdf", is_current=True,
        )
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_RAG_SGI_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=[],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            clear_knowledge_cache()
            context = build_knowledge_context("dove registro i timbri di presenza?")

        self.assertTrue(
            any(s.startswith("proc:MT CN 06#rev7") for s in context.sources),
            msg=f"la procedura corrente deve essere citabile (fallback metadati): {context.sources}",
        )
        self.assertFalse(
            any("MT CN 99" in s for s in context.sources),
            msg=f"un documento dismesso non deve comparire: {context.sources}",
        )

    # ── F2: regola di citazione nel prompt + comando di indicizzazione ──────
    def test_prompt_carries_sgi_citation_rule(self):
        messages = build_ollama_messages(
            "in che MT si parla di timbri?",
            knowledge_context=(
                "[fonte: proc:MT CN 06#rev7 > MT CN 06 Rev.7 — §4.2 Registrazione timbri]\n"
                "La registrazione dei timbri di presenza segue questa regola."
            ),
        )
        block = "\n".join(m["content"] for m in messages if m["role"] == "system")
        self.assertIn("REGOLA DI CITAZIONE DOCUMENTI SGI", block)
        self.assertIn("Non disponibile nei documenti indicizzati", block)

    def test_index_sgi_documents_command_reports_sgi_chunks(self):
        self._make_specifica_in_validita(codice="MT CN 06", revisione="7", titolo="Manuale timbri presenze")
        out = StringIO()
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_RAG_SGI_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=[],
            OLLAMA_RAG_CACHE_SECONDS=0,
        ):
            clear_knowledge_cache()
            call_command("index_sgi_documents", "--json", stdout=out)

        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["embeddings_enabled"])
        self.assertGreaterEqual(payload["chunks_spec"], 1)
        self.assertEqual(payload["chunks_sgi"], payload["chunks_spec"] + payload["chunks_proc"])

    def test_index_sgi_documents_skips_when_rag_disabled(self):
        out = StringIO()
        with override_settings(OLLAMA_RAG_ENABLED=False):
            call_command("index_sgi_documents", "--json", stdout=out)

        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["skipped"])

    def test_run_index_sgi_documents_task_is_failsafe(self):
        from ai_assistant.tasks import run_index_sgi_documents

        with patch("ai_assistant.services.index_sgi_documents", side_effect=RuntimeError("boom")):
            result = run_index_sgi_documents()

        self.assertFalse(result["ok"])
        self.assertIn("inatteso", result["message"])

    # ── F3: stemming opt-in + golden set SGI / ai_eval --rag-sgi ────────────
    def test_stemming_unifies_inflected_forms_when_enabled(self):
        from ai_assistant import services

        services._STEMMER_CACHE.update({"loaded": False, "stemmer": None})
        with override_settings(OLLAMA_RAG_STEMMING_ENABLED=True):
            stemmed = {services._tokenize(w)[0] for w in ("timbri", "timbro", "timbrare")}
        with override_settings(OLLAMA_RAG_STEMMING_ENABLED=False):
            raw = {services._tokenize(w)[0] for w in ("timbri", "timbro", "timbrare")}
        services._STEMMER_CACHE.update({"loaded": False, "stemmer": None})

        self.assertEqual(len(stemmed), 1, msg=f"lo stemming deve unificare le flessioni: {stemmed}")
        self.assertEqual(len(raw), 3, msg=f"senza stemming le flessioni restano distinte: {raw}")

    def test_stemming_is_failsafe_when_dependency_missing(self):
        import builtins

        from ai_assistant import services

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "snowballstemmer":
                raise ImportError("dipendenza assente")
            return real_import(name, *args, **kwargs)

        services._STEMMER_CACHE.update({"loaded": False, "stemmer": None})
        with override_settings(OLLAMA_RAG_STEMMING_ENABLED=True), patch(
            "builtins.__import__", side_effect=fake_import
        ):
            tokens = services._tokenize("timbrare")
        services._STEMMER_CACHE.update({"loaded": False, "stemmer": None})

        self.assertEqual(tokens, ["timbrare"], msg="dipendenza assente -> nessuno stemming, mai crash")

    def test_ai_eval_rag_sgi_reports_recall_on_seeded_corpus(self):
        from ai_assistant import services

        self._make_specifica_in_validita(codice="MT CN 06", revisione="7", titolo="Registrazione presenze")
        pdf_text = (
            "4.2 Registrazione timbri\n"
            "I timbri di presenza si registrano a inizio e fine turno tramite il portale."
        )
        out = StringIO()
        services._STEMMER_CACHE.update({"loaded": False, "stemmer": None})
        # Stemming ON: e' la config consigliata per il corpus SGI (unifica le flessioni
        # timbri/timbro/timbrare/presenze), così tutte le golden recuperano MT CN 06.
        with override_settings(
            OLLAMA_RAG_ENABLED=True,
            OLLAMA_RAG_SGI_ENABLED=True,
            OLLAMA_EMBED_ENABLED=False,
            OLLAMA_RAG_SOURCE_PATHS=[],
            OLLAMA_RAG_CACHE_SECONDS=0,
            OLLAMA_RAG_STEMMING_ENABLED=True,
        ), patch("ai_assistant.services._sgi_extract_specifica_text", return_value=pdf_text):
            clear_knowledge_cache()
            call_command("ai_eval", "--rag-sgi", "--json", stdout=out)
        services._STEMMER_CACHE.update({"loaded": False, "stemmer": None})

        payload = json.loads(out.getvalue())
        summary = payload["summary"]
        self.assertEqual(summary["mode"], "rag-sgi")
        self.assertTrue(summary["stemming_enabled"])
        self.assertGreaterEqual(summary["sgi_chunks"], 1)
        self.assertGreaterEqual(summary["cases"], 1)
        # Unico documento del corpus: con stemming tutte le golden recuperano MT CN 06.
        self.assertEqual(summary["recall_hits"], summary["cases"])

    def test_stemming_recovers_inflected_query_match(self):
        """Misura l'effetto della leva stemming: una query flessa ('timbrare') recupera
        il documento sui 'timbri' solo con lo stemming attivo (prima/dopo deterministico)."""
        from ai_assistant import services

        self._make_specifica_in_validita(codice="MT CN 06", revisione="7", titolo="Presenze")
        self._make_specifica_in_validita(codice="MT CN 80", revisione="1", titolo="Gestione personale")
        text_map = {
            "MT CN 06": "4.2 Registrazione timbri\nI timbri di inizio e fine turno.",
            "MT CN 80": "1 Personale\nGestione del personale interno ed esterno dell'azienda.",
        }

        def fake_extract(spec):
            return text_map.get(spec.codice, "")

        def sources_for(stemming):
            services._STEMMER_CACHE.update({"loaded": False, "stemmer": None})
            with override_settings(
                OLLAMA_RAG_ENABLED=True,
                OLLAMA_RAG_SGI_ENABLED=True,
                OLLAMA_EMBED_ENABLED=False,
                OLLAMA_RAG_SOURCE_PATHS=[],
                OLLAMA_RAG_CACHE_SECONDS=0,
                OLLAMA_RAG_MAX_CHUNKS=4,
                OLLAMA_RAG_STEMMING_ENABLED=stemming,
            ), patch("ai_assistant.services._sgi_extract_specifica_text", side_effect=fake_extract):
                clear_knowledge_cache()
                ctx = build_knowledge_context("come timbrare, info sul personale")
            return ctx.sources

        off = sources_for(False)
        on = sources_for(True)
        services._STEMMER_CACHE.update({"loaded": False, "stemmer": None})

        # OFF: 'timbrare' non combacia con 'timbri' -> il documento timbri non emerge.
        self.assertFalse(any("MT CN 06" in s for s in off), msg=f"off={off}")
        # ON: 'timbrare'->'timbr' == 'timbri'->'timbr' -> il documento timbri viene recuperato.
        self.assertTrue(any("MT CN 06" in s for s in on), msg=f"on={on}")


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False)
class EmbedBackendTests(TestCase):
    """Backend embeddings configurabile (RAG_EMBED_BACKEND) + fix chunk oversize."""

    def test_split_long_section_bounds_oversized_paragraph(self):
        from ai_assistant.services import _split_long_section

        # Un PDF estratto come UN unico blocco senza righe vuote: prima del fix
        # diventava un chunk gigante che sfondava il limite del modello embed.
        giant = "parola " * 2000  # ~14000 char in un solo "paragrafo"
        with override_settings(OLLAMA_RAG_CHUNK_OVERLAP_CHARS=0):
            chunks = _split_long_section("proc:X#rev1", "X Rev.1", giant, max_chars=900)
        self.assertGreater(len(chunks), 1, "il blocco gigante deve essere spezzato")
        self.assertTrue(
            all(len(c.content) <= 900 for c in chunks),
            msg=f"nessun chunk deve superare max_chars: {[len(c.content) for c in chunks]}",
        )

    def test_openai_backend_parses_embeddings(self):
        from ai_assistant import services

        payload = {
            "object": "list",
            "data": [
                {"embedding": [0.1, 0.2, 0.3], "index": 0},
                {"embedding": [0.4, 0.5, 0.6], "index": 1},
            ],
            "model": "bge-m3",
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        with override_settings(
            RAG_EMBED_BACKEND="openai",
            RAG_EMBED_OPENAI_BASE_URL="http://10.0.0.34:8081",
            RAG_EMBED_OPENAI_MODEL="BAAI/bge-m3",
        ), patch("ai_assistant.services.urllib.request.urlopen", return_value=FakeResponse()) as mocked:
            result = services._compute_embeddings(["a", "b"])

        self.assertEqual(result, [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        # ha chiamato l'endpoint OpenAI-compatibile, non Ollama
        self.assertTrue(mocked.call_args.args[0].full_url.endswith("/v1/embeddings"))

    def test_openai_backend_failsafe_on_mismatch(self):
        from ai_assistant import services

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"object":"list","data":[]}'  # 0 vettori per 2 input

        with override_settings(
            RAG_EMBED_BACKEND="openai",
            RAG_EMBED_OPENAI_BASE_URL="http://x:8081",
            RAG_EMBED_OPENAI_MODEL="m",
        ), patch("ai_assistant.services.urllib.request.urlopen", return_value=FakeResponse()):
            self.assertIsNone(services._compute_embeddings(["a", "b"]))

    def test_embeddings_enabled_respects_backend(self):
        from ai_assistant.services import embeddings_enabled

        # openai: indipendente dal provider chat
        with override_settings(OLLAMA_EMBED_ENABLED=True, RAG_EMBED_BACKEND="openai", OLLAMA_API_PROVIDER="openwebui"):
            self.assertTrue(embeddings_enabled())
        # master switch off -> sempre False
        with override_settings(OLLAMA_EMBED_ENABLED=False, RAG_EMBED_BACKEND="openai"):
            self.assertFalse(embeddings_enabled())
        # ollama + openwebui -> False (gli embeddings non passano da Open WebUI)
        with override_settings(OLLAMA_EMBED_ENABLED=True, RAG_EMBED_BACKEND="ollama", OLLAMA_API_PROVIDER="openwebui"):
            self.assertFalse(embeddings_enabled())
