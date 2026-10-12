"""Guide in-app dei moduli nel RAG dell'assistente, gate ACL e tool ticket per periodo."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from . import guide_portale
from .services import (
    _GROUNDING_RULES,
    _knowledge_for_chat,
    _retrieval_query,
    build_knowledge_context,
    build_ollama_messages,
    clear_knowledge_cache,
)
from .tools import build_runtime_context

_RAG_ONLY_GUIDES = dict(
    OLLAMA_RAG_ENABLED=True,
    OLLAMA_RAG_GUIDE_ENABLED=True,
    OLLAMA_EMBED_ENABLED=False,
    OLLAMA_RAG_SGI_ENABLED=False,
    OLLAMA_RAG_STEMMING_ENABLED=False,
    OLLAMA_RAG_SOURCE_PATHS=[],
    OLLAMA_RAG_CACHE_SECONDS=0,
)


def _tutte() -> frozenset[str]:
    return frozenset(g.slug for g in guide_portale.guide())


class GuideTestoTests(SimpleTestCase):
    def test_html_in_markdown_toglie_tag_variabili_e_varianti_per_utente(self):
        sorgente = (
            '{% extends "core/base.html" %}{% block extra_head %}<style>.x{}</style>{% endblock %}'
            "{% block content %}<h1>Guida X</h1>"
            '<h2>Stampa <span class="p {% if puo %}si">Puoi stampare{% else %}no">Non abilitato per te{% endif %}</span></h2>'
            "<p>Premi <b>Stampa</b> per al massimo {{ max_etichette }} etichette.</p>"
            "<ul><li>Primo passo abbastanza lungo da essere una frase vera</li><li>Secondo</li></ul>"
            "<table><tr><th>Campo</th><th>Valore</th></tr></table>{# nota #}"
            "{% endblock %}"
        )
        testo = guide_portale.html_in_markdown(sorgente)
        self.assertIn("## Stampa", testo)
        self.assertNotIn("abilitato per te", testo)
        self.assertNotIn("Puoi stampare", testo)
        self.assertNotIn("{{", testo)
        self.assertNotIn("<", testo)
        self.assertNotIn(".x{}", testo)
        self.assertNotIn("Guida X", testo)
        self.assertIn("- Primo passo", testo)
        self.assertIn("Campo · Valore", testo)

    def test_sezioni_in_markdown_converte_i_blocchi(self):
        testo = guide_portale.sezioni_in_markdown([
            {"titolo": "Capitolo", "blocchi": [
                ("p", "Paragrafo."), ("ul", ["uno", "due"]), ("nota", "Occhio."),
                ("def", [("Termine", "spiegazione")]),
            ]},
        ])
        self.assertIn("## Capitolo", testo)
        self.assertIn("- uno", testo)
        self.assertIn("Attenzione: Occhio.", testo)
        self.assertIn("- Termine: spiegazione", testo)

    def test_le_guide_dei_moduli_sono_indicizzate_con_il_link(self):
        sezioni = guide_portale.sezioni()
        slugs = {s.slug for s in sezioni}
        for atteso in ("timbri", "anomalie", "audit", "registro-ofi", "assets", "formazione"):
            self.assertIn(atteso, slugs)
        timbri = [s for s in sezioni if s.slug == "timbri"]
        self.assertTrue(all(s.url == "/timbri/?guida=1" for s in timbri))
        self.assertTrue(any("Nuovo record" in s.testo for s in timbri))


@override_settings(**_RAG_ONLY_GUIDES)
class GuideRetrievalTests(TestCase):
    def setUp(self):
        clear_knowledge_cache()

    def tearDown(self):
        clear_knowledge_cache()

    def test_senza_guide_consentite_nessuna_guida(self):
        ctx = build_knowledge_context("come inserisco un nuovo timbro?")
        self.assertFalse(any(s.startswith("guida:") for s in ctx.sources))

    def test_domanda_sul_timbro_porta_la_guida_timbri_in_testa(self):
        ctx = build_knowledge_context("come posso inserire un nuovo timbro?", allowed_guides=_tutte())
        self.assertTrue(ctx.sources[0].startswith("guida:timbri#"))
        self.assertIn("/timbri/?guida=1", ctx.text)

    def test_gate_acl_esclude_le_guide_non_consentite(self):
        ctx = build_knowledge_context(
            "come posso inserire un nuovo timbro?", allowed_guides=frozenset({"anomalie"})
        )
        self.assertFalse(any(s.startswith("guida:timbri") for s in ctx.sources))

    def test_tool_di_dati_live_passano_solo_le_guide_e_solo_per_il_come_si_fa(self):
        come = _knowledge_for_chat(
            "come aggiungo una firma al dipendente?",
            runtime_context="DATI LIVE PORTALE - TICKET",
            runtime_sources=("tool:tickets:riepilogo",),
            allow_specifiche=False, allow_procedure=False, allowed_guides=_tutte(),
        )
        self.assertEqual(come.knowledge_text, "")
        self.assertIn("Registro Timbri", come.guide_text)
        self.assertLessEqual(len(come.sources), 2)

        dati = _knowledge_for_chat(
            "quanti ticket ho?",
            runtime_context="DATI LIVE PORTALE - TICKET",
            runtime_sources=("tool:tickets:riepilogo",),
            allow_specifiche=False, allow_procedure=False, allowed_guides=_tutte(),
        )
        self.assertEqual((dati.knowledge_text, dati.guide_text, dati.sources), ("", "", ()))

    def test_catalogo_moduli_non_toglie_la_conoscenza(self):
        nav = _knowledge_for_chat(
            "dove trovo il modulo per inserire un timbro?",
            runtime_context="DATI LIVE PORTALE - MODULI DISPONIBILI",
            runtime_sources=("tool:portale:moduli",),
            allow_specifiche=False, allow_procedure=False, allowed_guides=_tutte(),
        )
        self.assertIn("Registro Timbri", nav.knowledge_text)

    def test_domanda_di_seguito_usa_il_turno_precedente(self):
        history = [
            {"role": "user", "content": "come posso inserire un nuovo timbro?"},
            {"role": "assistant", "content": "..."},
        ]
        query = _retrieval_query("ok dammi le indicazioni su come inserirlo nel modulo", history)
        self.assertIn("timbro", query)
        # Una domanda nuova che nomina il suo modulo non eredita il turno precedente.
        self.assertEqual(
            _retrieval_query("come stampo le etichette QR degli asset?", history),
            "come stampo le etichette QR degli asset?",
        )


class GroundingMessagesTests(SimpleTestCase):
    def test_regole_e_guida_nel_payload(self):
        messages = build_ollama_messages(
            "come faccio?", runtime_context="DATI LIVE X", guide_context="Guida Y"
        )
        contents = [m["content"] for m in messages if m["role"] == "system"]
        self.assertIn(_GROUNDING_RULES, contents[0])
        self.assertTrue(any("GUIDA D'USO DEL MODULO" in c and "Guida Y" in c for c in contents))


class GuideConsentiteTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("guide-acl", password="x")

    def test_senza_request_nessuna_guida(self):
        self.assertEqual(guide_portale.guide_consentite(None), frozenset())

    def test_superuser_tutte(self):
        admin = get_user_model().objects.create_superuser("guide-admin", password="x")
        request = SimpleNamespace(user=admin)
        self.assertEqual(guide_portale.guide_consentite(request), _tutte())

    def test_decide_l_acl_della_pagina_guida(self):
        request = SimpleNamespace(user=self.user, legacy_user=object())

        def _decisione(*, path, **kwargs):
            return {"allowed": path.startswith("/timbri/")}

        with patch("core.legacy_utils.legacy_auth_enabled", return_value=True), patch(
            "core.acl_v2.resolve_acl_access", side_effect=_decisione
        ):
            consentite = guide_portale.guide_consentite(request)
        self.assertEqual(consentite, frozenset({"timbri"}))


class TicketPeriodoTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "ticket-periodo", email="ticket-periodo@example.local", password="x"
        )

    def _ticket(self, titolo, stato, giorni_fa=0, richiedente=None):
        from tickets.models import PrioritaTicket, Ticket, TipoTicket

        ticket = Ticket.objects.create(
            tipo=TipoTicket.IT,
            titolo=titolo,
            descrizione="sintetico",
            categoria="RETE",
            priorita=PrioritaTicket.MEDIA,
            stato=stato,
            richiedente_nome=richiedente or self.user.username,
            richiedente_email="" if richiedente else self.user.email,
        )
        if giorni_fa:
            Ticket.objects.filter(pk=ticket.pk).update(created_at=timezone.now() - timedelta(days=giorni_fa))
        return ticket

    def test_quanti_ticket_ho_aperto_questo_mese(self):
        from tickets.models import StatoTicket

        oggi = timezone.localdate()
        self._ticket("Chiuso del mese", StatoTicket.CHIUSO)
        self._ticket("Aperto del mese", StatoTicket.APERTA)
        self._ticket("Vecchio", StatoTicket.APERTA, giorni_fa=oggi.day + 40)
        self._ticket("Di un altro", StatoTicket.APERTA, richiedente="Altro Utente")
        request = SimpleNamespace(user=self.user, path="/assistente-ai/")

        # Anche chi gestisce la coda: «ho aperto» resta l'ambito personale.
        with patch("tickets.views._can_manage_tickets", return_value=True), patch(
            "ai_assistant.tools.get_legacy_user", return_value=None
        ):
            context = build_runtime_context(request, "Quanti ticket ho aperto questo mese?")

        self.assertIn("tool:tickets:riepilogo", context.sources)
        self.assertIn("RISPOSTA DIRETTA: Hai aperto 2 ticket in questo mese", context.text)
        self.assertIn("Chiuso del mese", context.text)
        self.assertNotIn("Vecchio", context.text)
        self.assertNotIn("Di un altro", context.text)
