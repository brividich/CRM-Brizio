"""Fase 3: permessi reali dell'utente, conteggi/periodi nei tool, moduli chiesti senza dati."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from . import permessi_utente
from .services import OllamaChatResult, _knowledge_for_chat, clear_knowledge_cache
from .tools import _direct_count_line, build_runtime_context


class IntentoTests(SimpleTestCase):
    def test_domande_sui_permessi(self):
        self.assertTrue(permessi_utente.vuole_permessi("Posso inserire un nuovo timbro?"))
        self.assertTrue(permessi_utente.vuole_permessi("perché non vedo il pulsante copia nei timbri?"))
        self.assertTrue(permessi_utente.vuole_permessi("ho il permesso di chiudere un'anomalia?"))
        # «permessi» delle assenze non è una domanda sui permessi del portale.
        self.assertFalse(permessi_utente.vuole_permessi("quanti permessi residui ho?"))
        self.assertFalse(permessi_utente.vuole_permessi("quanti ticket ho aperto?"))

    def test_moduli_citati(self):
        self.assertEqual([m.slug for m in permessi_utente.moduli_citati("posso aggiungere una firma?")], ["timbri"])
        self.assertEqual([m.slug for m in permessi_utente.moduli_citati("quante richieste dpi?")], ["dpi"])
        self.assertEqual(permessi_utente.moduli_citati("buongiorno"), [])

    def test_conteggio_diretto(self):
        riga = _direct_count_line("quante anomalie aperte?", total=3, capped=False, soggetto="Risultano",
                                  oggetto="anomalie", period_label="questo mese (ottobre 2026)")
        self.assertEqual(riga, "RISPOSTA DIRETTA: Risultano 3 anomalie in questo mese (ottobre 2026).\n")
        self.assertEqual(_direct_count_line("quali anomalie?", total=3, capped=False, soggetto="x", oggetto="y"), "")
        self.assertIn("almeno 200", _direct_count_line("quanti?", total=200, capped=True, soggetto="x", oggetto="y"))

    def test_moduli_senza_dati(self):
        self.assertEqual(permessi_utente.moduli_senza_dati("quante anomalie aperte ci sono?", ()), ["anomalie"])
        self.assertEqual(
            permessi_utente.moduli_senza_dati("quante anomalie aperte ci sono?", ("tool:anomalie:riepilogo",)), []
        )
        self.assertEqual(permessi_utente.moduli_senza_dati("quali audit sono in scadenza?", ()), ["sistema_gestione"])
        # Le domande «come si fa» non chiedono dati.
        self.assertEqual(permessi_utente.moduli_senza_dati("come apro un ticket?", ()), [])

    def test_percorsi_dei_moduli_esistono(self):
        from django.urls import resolve

        for modulo in permessi_utente.MODULI:
            resolve(modulo.path)


class PermessiToolTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("perm.admin", password="x")
        self.user = get_user_model().objects.create_user("perm.utente", password="x")

    def test_superuser_vede_tutte_le_azioni_timbri_si(self):
        request = SimpleNamespace(user=self.admin, path="/assistente-ai/")
        context = build_runtime_context(request, "posso inserire un nuovo timbro?")
        self.assertIn("tool:portale:permessi", context.sources)
        self.assertIn("Registro Timbri", context.text)
        self.assertIn("Accesso al modulo: SI", context.text)
        self.assertIn("«Nuovo record»", context.text)
        self.assertNotIn(": NO", context.text)

    def test_azioni_dai_controlli_del_modulo(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/", legacy_user=None)
        with patch("ai_assistant.permessi_utente.accesso_modulo", return_value=True), patch(
            "timbri.views._can_view_timbri", return_value=True
        ), patch("timbri.views._can_edit_timbri", return_value=False), patch(
            "timbri.views._can_copy_timbri", return_value=True
        ), patch("timbri.views._can_download_timbri", return_value=False), patch(
            "timbri.views._can_manage_timbri_config", return_value=False
        ):
            context = build_runtime_context(request, "posso modificare un timbro?")
        self.assertIn("- Consultare il registro: SI", context.text)
        self.assertIn("«Nuovo record», «Modifica», «Archivia»): NO", context.text)
        self.assertIn("(«Copia»): SI", context.text)

    def test_senza_accesso_al_modulo_niente_azioni(self):
        request = SimpleNamespace(user=self.user, path="/assistente-ai/", legacy_user=None)
        with patch("ai_assistant.permessi_utente.accesso_modulo", return_value=False):
            context = build_runtime_context(request, "posso vedere i ticket del reparto?")
        self.assertIn("Accesso al modulo: NO", context.text)
        self.assertNotIn("Azioni:", context.text)

    def test_permessi_canonici_del_modulo(self):
        from core.models import PermissionDefinition

        PermissionDefinition.objects.create(code="tickets.test.uno", label="Gestire i ticket IT", module="tickets")
        request = SimpleNamespace(user=self.admin, path="/assistente-ai/")
        context = build_runtime_context(request, "ho il permesso di gestire i ticket?")
        self.assertIn("- Gestire i ticket IT: SI", context.text)

    def test_timbri_non_e_piu_il_dominio_timbrature(self):
        request = SimpleNamespace(user=self.admin, path="/assistente-ai/")
        context = build_runtime_context(request, "quali timbri ho nel registro?")
        self.assertNotIn("tool:runtime:non-disponibile", context.sources)
        context = build_runtime_context(request, "mostrami le mie timbrature")
        self.assertIn("tool:runtime:non-disponibile", context.sources)


@override_settings(OLLAMA_EMBED_ENABLED=False, OLLAMA_RAG_SGI_ENABLED=False, OLLAMA_RAG_CACHE_SECONDS=0)
class PermessiNonTolgonoIlRagTests(TestCase):
    def tearDown(self):
        clear_knowledge_cache()

    def test_permessi_come_tool_di_navigazione(self):
        from . import guide_portale

        tutte = frozenset(g.slug for g in guide_portale.guide())
        knowledge = _knowledge_for_chat(
            "come posso inserire un nuovo timbro?",
            runtime_context="DATI LIVE PORTALE - PERMESSI DELL'UTENTE CORRENTE",
            runtime_sources=("tool:portale:permessi",),
            allow_specifiche=False, allow_procedure=False, allowed_guides=tutte,
        )
        self.assertIn("Registro Timbri", knowledge.knowledge_text)


class AuditModuliSenzaDatiTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.admin = get_user_model().objects.create_superuser("perm.audit", password="x")
        self.client.force_login(self.admin)

    def test_audit_registra_solo_lo_slug(self):
        from core.models import AuditLog

        with patch("ai_assistant.views.build_runtime_context") as ctx, patch(
            "ai_assistant.views.chat_with_ollama"
        ) as chat:
            ctx.return_value.text = ""
            ctx.return_value.sources = ()
            ctx.return_value.audit = {}
            chat.return_value = OllamaChatResult(content="Non ho quei dati.", model="m", done=True)
            self.client.post(
                reverse("ai_assistant:api_chat"),
                data=json.dumps({"message": "quali audit sono in scadenza?"}),
                content_type="application/json",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        log = AuditLog.objects.filter(azione="ai_chat").latest("id")
        self.assertEqual(log.dettaglio["moduli_senza_dati"], ["sistema_gestione"])
        self.assertNotIn("quali audit", json.dumps(log.dettaglio))
