import json
import tempfile
import socket
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AiKnowledgeEntry
from .services import OllamaChatError, OllamaChatResult, build_knowledge_context, build_ollama_messages, chat_with_ollama
from .tools import RuntimeContext, _merge_contexts, build_runtime_context


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False)
class AiAssistantTests(TestCase):
    def setUp(self):
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
