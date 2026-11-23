"""Indice RAG costruito dal cluster, salvato su file e letto pronto dal portale."""
from __future__ import annotations

import os
import tempfile
from collections import Counter
from unittest import mock

from django.test import SimpleTestCase, override_settings

from ai_assistant import indice_file, services


def _indice(testo: str = "c") -> services.KnowledgeIndex:
    chunk = services.KnowledgeChunk(
        source="a.md", title="t", content=testo, tokens=Counter({"x": 1}), title_tokens=frozenset({"t"})
    )
    return services.KnowledgeIndex(chunks=(chunk,), idf={"x": 1.0}, avgdl=1.0)


class IndiceFileTests(SimpleTestCase):
    def setUp(self):
        self.cartella = tempfile.TemporaryDirectory()
        self.addCleanup(self.cartella.cleanup)
        self.impostazioni = override_settings(
            OLLAMA_RAG_INDEX_FILE_ENABLED=True,
            OLLAMA_RAG_INDEX_FILE=os.path.join(self.cartella.name, "rag", "indice.bin"),
        )
        self.impostazioni.enable()
        self.addCleanup(self.impostazioni.disable)
        services.clear_knowledge_cache()
        self.addCleanup(services.clear_knowledge_cache)

    def test_salva_e_carica(self):
        indice_file.salva(_indice(), ("firma",))
        firma, indice = indice_file.carica()
        self.assertEqual(indice, _indice())
        self.assertEqual(firma, indice_file.impronta_firma(("firma",)))
        self.assertEqual(indice_file.firma_su_file(), firma)

    def test_file_alterato_ignorato(self):
        indice_file.salva(_indice(), ("firma",))
        dati = bytearray(indice_file.percorso().read_bytes())
        dati[-1] ^= 1
        indice_file.percorso().write_bytes(bytes(dati))
        self.assertIsNone(indice_file.carica())

    def test_portale_legge_il_file_senza_costruire(self):
        indice_file.salva(_indice(), ("firma",))
        with mock.patch.object(services, "_build_knowledge_index", side_effect=AssertionError("costruito")), \
                mock.patch.object(indice_file, "richiedi_ricostruzione") as richiesta:
            self.assertEqual(services._index_from_file(("firma",)), _indice())
            # Seconda chiamata: dalla memoria, il file non si rilegge.
            with mock.patch.object(indice_file, "carica", side_effect=AssertionError("riletto")):
                self.assertEqual(services._index_from_file(("firma",)), _indice())
        richiesta.assert_not_called()

    def test_documenti_cambiati_risponde_col_file_e_chiede_ricostruzione(self):
        indice_file.salva(_indice(), ("vecchia",))
        with mock.patch.object(indice_file, "richiedi_ricostruzione") as richiesta:
            self.assertEqual(services._index_from_file(("nuova",)), _indice())
        richiesta.assert_called()

    def test_file_nuovo_viene_ricaricato(self):
        indice_file.salva(_indice("vecchio"), ("firma",))
        with mock.patch.object(indice_file, "richiedi_ricostruzione"):
            services._index_from_file(("firma",))
            indice_file.salva(_indice("nuovo"), ("firma",))
            nuovo_mtime = indice_file.mtime() + 5
            os.utime(indice_file.percorso(), (nuovo_mtime, nuovo_mtime))
            self.assertEqual(services._index_from_file(("firma",)).chunks[0].content, "nuovo")

    def test_senza_file_chiede_ricostruzione_e_lascia_il_vecchio_percorso(self):
        with mock.patch.object(indice_file, "richiedi_ricostruzione") as richiesta:
            self.assertIsNone(services._index_from_file(("firma",)))
        richiesta.assert_called_once()

    def test_build_and_save_salta_se_gia_allineato(self):
        with mock.patch.object(services, "_iter_knowledge_files", return_value=[]), \
                mock.patch.object(services, "_knowledge_signature", return_value=("firma",)), \
                mock.patch.object(services, "_build_knowledge_index", return_value=_indice()) as build:
            primo = services.build_and_save_knowledge_index()
            secondo = services.build_and_save_knowledge_index()
        self.assertFalse(primo["skipped"])
        self.assertTrue(secondo["skipped"])
        self.assertEqual(build.call_count, 1)

    def test_rebuild_in_background_va_al_cluster(self):
        with mock.patch.object(indice_file, "richiedi_ricostruzione", return_value=True) as richiesta, \
                mock.patch("threading.Thread", side_effect=AssertionError("thread nel processo web")):
            self.assertTrue(services._start_background_rebuild())
        richiesta.assert_called_once()
