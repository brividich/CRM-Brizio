"""Prestazioni dell'assistente AI: indice RAG in memoria, ranking e preriscaldamento."""

from __future__ import annotations

from collections import Counter
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from ai_assistant import services
from ai_assistant.services import KnowledgeChunk


def _chunk(i: int, text: str, title: str = "") -> KnowledgeChunk:
    return KnowledgeChunk(
        source=f"doc{i}.md",
        title=title or f"Sezione {i}",
        content=text,
        tokens=Counter(services._tokenize(text)),
    )


_CORPUS = [
    _chunk(0, "richiesta ferie e permessi dal portale"),
    _chunk(1, "consegna DPI guanti e scarpe antinfortunistiche"),
    _chunk(2, "apertura ticket di assistenza informatica", title="Ticket ferie"),
    _chunk(3, "manutenzione macchine utensili e ordini di lavoro"),
    _chunk(4, "ferie ferie ferie piano annuale"),
]


class Bm25PostingsTests(SimpleTestCase):
    def test_ranking_con_indice_invertito_uguale_alla_scansione_completa(self):
        from dataclasses import replace

        index = services._build_index(list(_CORPUS))
        self.assertIsNotNone(index.postings)
        scansione = replace(index, postings=None)
        for domanda in ("ferie", "ticket ferie", "guanti dpi", "macchine", "nulla di pertinente"):
            tokens = Counter(services._tokenize(domanda))
            self.assertEqual(
                services._bm25_ranking(tokens, index),
                services._bm25_ranking(tokens, scansione),
                domanda,
            )

    def test_il_titolo_rende_candidato_il_chunk(self):
        index = services._build_index(list(_CORPUS))
        ranking = services._bm25_ranking(Counter(services._tokenize("ticket")), index)
        self.assertEqual(ranking[0], 2)


class RankingSemanticoTests(SimpleTestCase):
    def _index(self, vectors):
        from dataclasses import replace

        index = services._build_index(list(_CORPUS[: len(vectors)]))
        return replace(index, embeddings=services._embedding_matrix(vectors), embed_model="m")

    def test_ordina_per_coseno_e_scarta_i_non_positivi(self):
        index = self._index([[1.0, 0.0], [0.0, 1.0], [0.7, 0.7], [-1.0, 0.0]])
        with patch.object(services, "_query_embedding", return_value=[1.0, 0.1]):
            self.assertEqual(services._semantic_ranking("domanda", index), [0, 2, 1])

    def test_dimensione_diversa_ripiega_su_bm25(self):
        index = self._index([[1.0, 0.0], [0.0, 1.0]])
        with patch.object(services, "_query_embedding", return_value=[1.0, 0.0, 0.0]):
            self.assertEqual(services._semantic_ranking("domanda", index), [])

    def test_riga_nulla_non_rompe_la_normalizzazione(self):
        matrix = services._embedding_matrix([[0.0, 0.0], [3.0, 4.0]])
        self.assertEqual(matrix.shape, (2, 2))
        self.assertAlmostEqual(float(matrix[1][0]), 0.6, places=5)
        self.assertEqual(float(matrix[0].sum()), 0.0)


class EmbeddingDomandaCondivisoTests(SimpleTestCase):
    def test_nello_scope_la_stessa_domanda_si_embedda_una_volta(self):
        with patch.object(services, "embed_texts", return_value=[[1.0, 0.0]]) as embed:
            with services.query_embedding_scope():
                services.embed_query("quante ferie ho?", timeout=6)
                services.embed_query("quante ferie ho?")
            self.assertEqual(embed.call_count, 1)
            services.embed_query("quante ferie ho?")
            self.assertEqual(embed.call_count, 2)  # fuori dallo scope nessuna memoria

    def test_un_errore_non_viene_memorizzato(self):
        with patch.object(services, "embed_texts", side_effect=[None, [[1.0]]]) as embed:
            with services.query_embedding_scope():
                self.assertIsNone(services.embed_query("x"))
                self.assertEqual(services.embed_query("x"), [1.0])
            self.assertEqual(embed.call_count, 2)


@override_settings(OLLAMA_EMBED_PERSIST=False)
class EmbeddingsRiusoTests(SimpleTestCase):
    def test_i_vettori_in_memoria_non_vengono_ricalcolati(self):
        chunks = list(_CORPUS[:3])
        reuse = {services._embed_cache_key("m", c): [1.0, 0.0] for c in chunks[:2]}
        with patch.object(services, "_compute_embeddings", return_value=[[0.0, 1.0]]) as compute:
            vectors = services._embeddings_for_chunks(chunks, "m", reuse=reuse)
        compute.assert_called_once()
        self.assertEqual(len(compute.call_args.args[0]), 1)
        self.assertEqual([list(v) for v in vectors], [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])

    def test_oltre_il_tetto_non_chiama_il_backend(self):
        with patch.object(services, "_compute_embeddings") as compute:
            self.assertIsNone(services._embeddings_for_chunks(list(_CORPUS), "m", max_compute=2))
        compute.assert_not_called()


@override_settings(
    OLLAMA_RAG_ENABLED=True,
    OLLAMA_RAG_CACHE_SECONDS=300,
    OLLAMA_RAG_BACKGROUND_REBUILD=True,
    OLLAMA_EMBED_ENABLED=False,
)
class IndiceInBackgroundTests(SimpleTestCase):
    def setUp(self):
        services.clear_knowledge_cache()
        self.addCleanup(services.clear_knowledge_cache)

    def _firma(self, valore):
        return patch.object(services, "_knowledge_signature", return_value=(valore,))

    def test_documenti_cambiati_rispondono_con_l_indice_corrente_e_ricostruiscono_dopo(self):
        primo = services._build_index(list(_CORPUS[:2]))
        with self._firma("v1"), patch.object(services, "_build_knowledge_index", return_value=primo) as build:
            services._KNOWLEDGE_CACHE.update({"index": primo, "signature": ("v1",), "loaded_at": 1e12})
            self.assertIs(services._load_knowledge_index(), primo)
            build.assert_not_called()
        with self._firma("v2"), patch.object(services, "_start_background_rebuild") as avvia, \
                patch.object(services, "_build_knowledge_index") as build:
            self.assertIs(services._load_knowledge_index(), primo)
        avvia.assert_called_once()
        build.assert_not_called()

    def test_primo_build_sincrono_con_tetto_embeddings(self):
        indice = services._build_index(list(_CORPUS))

        def finto_build(files, signature, *, max_compute):
            services._KNOWLEDGE_CACHE.update({"index": indice, "signature": signature, "complete": True})
            return indice

        with self._firma("v1"), override_settings(OLLAMA_EMBED_INLINE_MAX=50), \
                patch.object(services, "_build_knowledge_index", side_effect=finto_build) as build, \
                patch.object(services, "_start_background_rebuild") as avvia:
            self.assertIs(services._load_knowledge_index(), indice)
        self.assertEqual(build.call_args.kwargs["max_compute"], 50)
        avvia.assert_not_called()

    def test_indice_incompleto_avvia_il_completamento(self):
        indice = services._build_index(list(_CORPUS))

        def finto_build(files, signature, *, max_compute):
            services._KNOWLEDGE_CACHE.update({"index": indice, "signature": signature, "complete": False})
            return indice

        with self._firma("v1"), patch.object(services, "_build_knowledge_index", side_effect=finto_build), \
                patch.object(services, "_start_background_rebuild") as avvia:
            services._load_knowledge_index()
            avvia.assert_called_once()
            avvia.reset_mock()
            self.assertIs(services._load_knowledge_index(), indice)  # nessun build sincrono ripetuto
            avvia.assert_called_once()

    @override_settings(OLLAMA_RAG_CACHE_SECONDS=0)
    def test_cache_zero_ricostruisce_sempre_in_modo_sincrono(self):
        indice = services._build_index(list(_CORPUS))
        with self._firma("v1"), patch.object(services, "_build_knowledge_index", return_value=indice) as build, \
                patch.object(services, "_start_background_rebuild") as avvia:
            services._load_knowledge_index()
            services._load_knowledge_index()
        self.assertEqual(build.call_count, 2)
        self.assertIsNone(build.call_args.kwargs["max_compute"])
        avvia.assert_not_called()

    def test_un_solo_rebuild_in_background_alla_volta(self):
        with patch.object(services.threading, "Thread") as thread:
            self.assertTrue(services._start_background_rebuild())
            self.assertFalse(services._start_background_rebuild())
        thread.assert_called_once()
        services._KNOWLEDGE_CACHE["rebuilding"] = False


class PreriscaldamentoTests(SimpleTestCase):
    def tearDown(self):
        services._PREWARM_STATE["running"] = False

    @override_settings(AI_PREWARM_ON_PAGE_OPEN=False)
    def test_spento_da_configurazione(self):
        with patch.object(services.threading, "Thread") as thread:
            self.assertFalse(services.prewarm_async())
        thread.assert_not_called()

    @override_settings(AI_PREWARM_ON_PAGE_OPEN=True, OLLAMA_CHAT_ENABLED=True)
    def test_uno_alla_volta(self):
        with patch.object(services.threading, "Thread") as thread:
            self.assertTrue(services.prewarm_async())
            self.assertFalse(services.prewarm_async())
        thread.assert_called_once()
