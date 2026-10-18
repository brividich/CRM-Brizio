"""Ricerca nei documenti per la barra «Cerca o vai a…» (services.cerca_documenti)."""
from __future__ import annotations

from collections import Counter
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from ai_assistant import services
from ai_assistant.services import KnowledgeChunk, cerca_documenti


def _chunk(source, title, content):
    toks = Counter(services._tokenize(f"{title}\n{content}"))
    return KnowledgeChunk(source=source, title=title, content=content, tokens=toks)


def _indice():
    chunks = [
        _chunk("guida:dpi#0", "Guida DPI — Richiedere un DPI",
               "Guida DPI — Richiedere un DPI\nGuida completa nel portale: /dpi/guida/\nPer richiedere i guanti apri DPI e premi Nuova richiesta."),
        _chunk("proc:PR-07#rev2", "PR-07 Gestione DPI", "La procedura PR-07 descrive la consegna dei guanti e la sostituzione."),
        _chunk("spec:SP-11", "SP-11 Verniciatura", "Specifica di verniciatura dei pezzi."),
    ]
    return services._build_index(chunks)


class CercaDocumentiTests(TestCase):
    def setUp(self):
        self._prima = dict(services._KNOWLEDGE_CACHE)
        services._KNOWLEDGE_CACHE["index"] = _indice()

    def tearDown(self):
        services._KNOWLEDGE_CACHE.clear()
        services._KNOWLEDGE_CACHE.update(self._prima)

    def test_trova_guida_con_link_e_rispetta_acl(self):
        stato, res = cerca_documenti("come richiedo i guanti", allowed_guides=frozenset({"dpi"}))
        self.assertEqual(stato, "pronto")
        self.assertEqual(res[0]["tipo"], "Guida")
        self.assertEqual(res[0]["url"], "/dpi/guida/")
        self.assertIn("guanti", res[0]["preview"].lower())
        self.assertNotIn("Procedura", [r["tipo"] for r in res])  # procedure solo ai manager
        stato, res = cerca_documenti("guanti consegna", allow_procedure=True, allowed_guides=frozenset())
        self.assertEqual([r["tipo"] for r in res], ["Procedura"])  # guida non consentita: fuori
        self.assertEqual(res[0]["url"], "")

    def test_indice_a_freddo_non_blocca(self):
        services._KNOWLEDGE_CACHE.pop("index", None)
        with patch.object(services, "prewarm_async") as prewarm:
            stato, res = cerca_documenti("guanti")
        self.assertEqual((stato, res), ("in_preparazione", []))
        prewarm.assert_called_once()

    def test_api_richiede_accesso_e_risponde_json(self):
        url = reverse("ai_assistant:api_cerca_documenti")
        self.assertEqual(self.client.get(url + "?q=guanti").status_code in (401, 302), True)
        user = get_user_model().objects.create_superuser("cd_admin", "cd@example.invalid", "x")
        self.client.force_login(user)
        data = self.client.get(url + "?q=guanti").json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["results"])
        self.assertEqual(self.client.get(url + "?q=gu").json()["results"], [])
