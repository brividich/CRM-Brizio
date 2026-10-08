"""Test B2: glossario nel retrieval (pre-pass del tokenizer, pattern protetti, chunk
curati, bozze escluse, cache invalidata). Solo testi sintetici."""

from __future__ import annotations

import re
import unicodedata

from django.test import TestCase, override_settings

from ai_assistant import glossario_rag, services

from .models import Termine, Variante
from .services import aggiungi_variante, valida

FRASI = [
    "Come si registra un'anomalia sull'OP?",
    "Procedura MT CN 06 Rev.21 — §4.2 Responsabilità della qualità",
    "Lamatura ⌴ ⌀12 ↧2 e foro ⌀20 H7, filetto M8x1.25, Ra 0,8",
    "Qualità, città, perché: accenti e punteggiatura!",
    "MOD.093 IDOR CN 01 Allegato A — MT CN 125_10",
    "",
]


def _tokenize_originale(value: str) -> list[str]:
    """Copia del tokenizer prima di B2 (riferimento per la non regressione)."""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return [t for t in re.findall(r"[a-z0-9_]{3,}", folded) if t not in services._RAG_STOPWORDS]


class _Base(TestCase):
    def setUp(self):
        glossario_rag.bump_versione()
        self.lamatura = Termine.objects.get(termine="lamatura")
        valida(self.lamatura, None)
        self.planarita = Termine.objects.get(termine="planarità")
        valida(self.planarita, None)
        glossario_rag.bump_versione()

    def tearDown(self):
        glossario_rag.bump_versione()

    def gl(self, termine) -> str:
        return f"gl_{termine.pk}"


class FlagSpentoTests(_Base):
    @override_settings(OLLAMA_RAG_GLOSSARIO_ENABLED=False, OLLAMA_RAG_STEMMING_ENABLED=False)
    def test_token_identici_a_prima(self):
        for frase in FRASI:
            self.assertEqual(services._tokenize(frase), _tokenize_originale(frase), frase)

    @override_settings(OLLAMA_RAG_GLOSSARIO_ENABLED=False)
    def test_niente_chunk_ne_firma(self):
        self.assertEqual(services._load_glossario_chunks(), [])
        self.assertEqual(glossario_rag.firma(), ())


@override_settings(OLLAMA_RAG_GLOSSARIO_ENABLED=True)
class PatternProtettiTests(_Base):
    def test_nessun_falso_positivo_sui_codici_documento(self):
        for codice in ("MT CN 06 Rev.21", "MOD.093", "IDOR CN 01 Allegato A", "MT CN 125_10",
                       "MTSI CN 16 Rev.3 del 12/03/2026", "pag. 3 di 12"):
            protetti = [t for t in glossario_rag.token_protetti(codice)]
            self.assertEqual(protetti, [], codice)

    def test_casi_positivi(self):
        casi = {
            "⌀20 H7": {"iso286_h7"},
            "20 g6": {"iso286_g6"},
            "accoppiamento ⌀20 H7/g6": {"iso286_h7", "iso286_g6"},
            "M8": {"filetto_m8"},
            "M8x1.25": {"filetto_m8", "filetto_m8x1_25"},
            "M8 x 1,25": {"filetto_m8", "filetto_m8x1_25"},
            "Ra 0,8": {"rug_ra", "rug_ra_0_8"},
            "Ra0.8": {"rug_ra", "rug_ra_0_8"},
            "Rz 6,3": {"rug_rz", "rug_rz_6_3"},
        }
        for testo, attesi in casi.items():
            self.assertEqual(set(glossario_rag.token_protetti(testo)), attesi, testo)

    def test_tokenize_include_i_protetti(self):
        self.assertIn("iso286_h7", services._tokenize("foro ⌀20 H7"))


@override_settings(OLLAMA_RAG_GLOSSARIO_ENABLED=True)
class VariantiTests(_Base):
    def test_varianti_e_simbolo_stesso_token(self):
        for testo in ("lamatura", "una spot face sul pezzo", "simbolo ⌴ sul foro", "SPOTFACE"):
            self.assertIn(self.gl(self.lamatura), services._tokenize(testo), testo)

    def test_accenti(self):
        token = self.gl(self.planarita)
        self.assertIn(token, services._tokenize("verifica di planarità"))
        self.assertIn(token, services._tokenize("verifica di planarita"))
        self.assertIn(token, services._tokenize("flatness"))

    def test_bozza_esclusa_senza_include_bozze(self):
        bozza = Termine.objects.get(termine="svasatura")
        self.assertEqual(bozza.stato, "bozza")
        self.assertNotIn(self.gl(bozza), services._tokenize("svasatura countersink"))
        with override_settings(OLLAMA_RAG_GLOSSARIO_INCLUDE_BOZZE=True):
            glossario_rag.bump_versione()
            self.assertIn(self.gl(bozza), services._tokenize("svasatura countersink"))
        glossario_rag.bump_versione()
        self.assertNotIn(self.gl(bozza), services._tokenize("svasatura"))

    def test_usa_nel_rag_false_escluso(self):
        self.lamatura.usa_nel_rag = False
        self.lamatura.save()
        self.assertNotIn(self.gl(self.lamatura), services._tokenize("lamatura"))

    def test_sigle_corte_case_sensitive(self):
        nc = Termine.objects.get(termine="non conformità")
        valida(nc, None)
        self.assertIn(self.gl(nc), services._tokenize("aprire una NC sul lotto"))
        fai = Termine.objects.get(termine="ispezione del primo articolo")
        valida(fai, None)
        self.assertIn(self.gl(fai), services._tokenize("rapporto FAI"))
        self.assertNotIn(self.gl(fai), services._tokenize("come fai a saperlo"))

    def test_cache_invalidata_dalla_modifica(self):
        self.assertNotIn(self.gl(self.lamatura), services._tokenize("fresalama sintetica xyz"))
        aggiungi_variante(self.lamatura, "fresalama sintetica xyz", "gergo")  # signal -> bump
        self.assertIn(self.gl(self.lamatura), services._tokenize("fresalama sintetica xyz"))
        Variante.objects.filter(testo="fresalama sintetica xyz").delete()
        self.assertNotIn(self.gl(self.lamatura), services._tokenize("fresalama sintetica xyz"))
        prima = glossario_rag.firma()
        self.lamatura.definizione = "Definizione aggiornata."
        self.lamatura.save()
        self.assertNotEqual(glossario_rag.firma(), prima)


@override_settings(OLLAMA_RAG_GLOSSARIO_ENABLED=True)
class ChunkCuratiTests(_Base):
    def test_solo_validati_con_fonte_e_senza_note_interne(self):
        self.lamatura.note_interne = "NOTA-RISERVATA-SINTETICA"
        self.lamatura.save()
        chunks = services._load_glossario_chunks()
        fonti = {c.source for c in chunks}
        self.assertEqual(fonti, {f"glossario:{self.lamatura.pk}#lamatura", f"glossario:{self.planarita.pk}#planarita"})
        lam = next(c for c in chunks if c.source.endswith("#lamatura"))
        self.assertIn("spot face", lam.content)
        self.assertIn("⌴", lam.content)
        self.assertNotIn("NOTA-RISERVATA-SINTETICA", lam.content)
        self.assertIn(self.gl(self.lamatura), lam.tokens)

    @override_settings(OLLAMA_RAG_SGI_ENABLED=False, OLLAMA_RAG_SOURCE_PATHS=[], OLLAMA_EMBED_ENABLED=False,
                       RAG_EMBED_BACKEND="ollama")
    def test_indice_e_retrieval(self):
        services.clear_knowledge_cache()
        index = services._load_knowledge_index()
        self.assertTrue(any(c.source.startswith("glossario:") for c in index.chunks))
        from collections import Counter

        query = "cosa significa spot face?"
        ranked = services._select_chunk_indices(query, Counter(services._tokenize(query)), index)
        self.assertTrue(index.chunks[ranked[0]].source.endswith("#lamatura"))
        services.clear_knowledge_cache()
