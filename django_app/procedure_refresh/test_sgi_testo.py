"""Test fase A1 database SGI: estrattore, persistenza, precedenza PDF, catena task,
lettura dal RAG e chunking. Solo PDF sintetici generati in una cartella temporanea."""

from __future__ import annotations

import io
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from procedure_refresh.models import (
    DocumentType,
    ProcedureDocument,
    ProcedureRevision,
    SgiTestoEstratto,
    SourceType,
)
from procedure_refresh.sgi_testo import (
    estrai,
    normalizza,
    persisti_estrazione,
    revisioni_da_estrarre,
    tabella_markdown,
)


def _griglia(page, x0, y0, righe, colonne, w=110, h=22, prefisso="V"):
    for r in range(righe + 1):
        page.draw_line((x0, y0 + r * h), (x0 + colonne * w, y0 + r * h))
    for c in range(colonne + 1):
        page.draw_line((x0 + c * w, y0), (x0 + c * w, y0 + righe * h))
    for r in range(righe):
        for c in range(colonne):
            page.insert_text((x0 + c * w + 5, y0 + r * h + 15), f"{prefisso}{r}{c}")


def pdf_documento(path: Path, *, pagine: int = 3, tabella: bool = True, cornice: bool = False) -> None:
    """PDF sintetico: intestazione ripetuta con numero pagina, sezioni §, una tabella."""
    import fitz

    doc = fitz.open()
    for n in range(1, pagine + 1):
        page = doc.new_page()
        page.insert_text((72, 40), f"XX ZZ 01 Rev.3 Documento sintetico pag. {n} di {pagine}")
        page.insert_text((72, 300), f"{n}. Sezione sintetica numero {n}")
        page.insert_text((72, 320), f"Testo di prova {n} della sezione, abbastanza lungo da contare come nativo.")
        if tabella and n == 1:
            _griglia(page, 72, 400, 3, 3)
        if cornice:
            page.draw_rect(fitz.Rect(20, 20, page.rect.width - 20, page.rect.height - 20))
    doc.save(str(path))
    doc.close()


def pdf_scansione(path: Path) -> None:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 30, 30), False)
    pix.clear_with(180)
    page.insert_image(fitz.Rect(72, 72, 400, 400), pixmap=pix)
    doc.save(str(path))
    doc.close()


class EstrattoreTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_tabella_in_pipe_table_e_non_duplicata(self):
        p = self.dir / "doc.pdf"
        pdf_documento(p)
        res = estrai(p)
        self.assertEqual(res.formato, "pdf")
        self.assertEqual(res.metodo, "pymupdf_layout")
        self.assertIn("| V00 | V01 | V02 |", res.testo)
        self.assertIn("| V20 | V21 | V22 |", res.testo)
        self.assertEqual(res.testo.count("V11"), 1)  # non duplicata nel testo dei blocchi

    def test_intestazione_ripetuta_tenuta_una_volta(self):
        p = self.dir / "doc.pdf"
        pdf_documento(p, pagine=4, tabella=False)
        res = estrai(p)
        self.assertEqual(res.testo.count("Documento sintetico pag."), 1)
        self.assertEqual(res.n_pagine, 4)
        self.assertTrue(res.ha_testo_nativo)
        self.assertGreaterEqual(res.n_sezioni, 2)
        self.assertTrue(any("ripetute rimosse" in a for a in res.avvisi))

    def test_cornice_di_pagina_non_e_una_tabella(self):
        p = self.dir / "doc.pdf"
        pdf_documento(p, pagine=2, tabella=False, cornice=True)
        res = estrai(p)
        self.assertIn("Sezione sintetica numero 2", res.testo)
        self.assertNotIn("| Sezione", res.testo)

    def test_scansione(self):
        p = self.dir / "scan.pdf"
        pdf_scansione(p)
        res = estrai(p)
        self.assertFalse(res.ha_testo_nativo)
        self.assertEqual(res.testo, "")
        self.assertTrue(any("scansione" in a for a in res.avvisi))

    def test_file_corrotto_e_formato_non_supportato_fail_safe(self):
        bad = self.dir / "rotto.pdf"
        bad.write_bytes(b"non un pdf")
        res = estrai(bad)
        self.assertEqual(res.testo, "")
        self.assertTrue(res.avvisi)
        res = estrai(self.dir / "x.docx")
        self.assertIn("formato non supportato: .docx", res.avvisi)
        self.assertEqual(estrai(self.dir / "inesistente.pdf").testo, "")

    def test_normalizza_e_tabella_markdown(self):
        self.assertEqual(normalizza("manu-\ntenzione  ordinaria  qui"), "manutenzione ordinaria qui")
        self.assertEqual(normalizza("Café"), "Café")
        md = tabella_markdown([["A", "B"], ["1", None], ["x|y", "2"], [None, ""]])
        self.assertEqual(md, "| A | B |\n|---|---|\n| 1 |  |\n| x/y | 2 |")
        self.assertEqual(tabella_markdown([[None, ""]]), "")


class _RevisioneMixin:
    def _rev(self, code, path, *, file_hash="h1", escludi=False, title="Documento sintetico"):
        doc = ProcedureDocument.objects.create(
            code=code, title=title, document_type=DocumentType.ALTRO, escludi_dal_rag=escludi,
        )
        return ProcedureRevision.objects.create(
            document=doc, revision_code="3", revision_date=date(2026, 1, 1), effective_date=date(2026, 1, 1),
            source_type=SourceType.FILESERVER, source_path=str(path), file_name=Path(path).name,
            file_hash=file_hash, is_current=True,
        )


class PersistenzaTests(_RevisioneMixin, TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.pdf = self.dir / "XX ZZ 01 Rev.3_Documento.pdf"
        pdf_documento(self.pdf)

    def tearDown(self):
        self._tmp.cleanup()

    def test_idempotente_su_hash(self):
        rev = self._rev("XX ZZ 01", self.pdf)
        self.assertEqual(persisti_estrazione(rev), "estratto")
        row = SgiTestoEstratto.objects.get(revision=rev)
        self.assertEqual(row.file_hash, "h1")
        self.assertIn("| V00 |", row.testo)
        rev.refresh_from_db()
        self.assertEqual(persisti_estrazione(rev), "invariato")
        self.assertEqual(persisti_estrazione(rev, forza=True), "estratto")
        rev.file_hash = "h2"
        rev.save()
        self.assertEqual([r.pk for r in revisioni_da_estrarre()], [rev.pk])
        self.assertEqual(persisti_estrazione(rev), "estratto")
        self.assertEqual(SgiTestoEstratto.objects.get(revision=rev).file_hash, "h2")
        self.assertEqual(SgiTestoEstratto.objects.count(), 1)

    def test_salti(self):
        rev = self._rev("XX ZZ 02", self.pdf, file_hash="")
        self.assertTrue(persisti_estrazione(rev).startswith("saltato: hash"))
        rev2 = self._rev("XX ZZ 03", self.dir / "manca.pdf")
        self.assertTrue(persisti_estrazione(rev2).startswith("saltato: file"))
        self.assertFalse(SgiTestoEstratto.objects.exists())

    def test_documenti_fuori_dal_rag_esclusi(self):
        self._rev("XX ZZ 04", self.pdf, escludi=True)
        self._rev("MOD.187", self.pdf, file_hash="h9", title="Elenco sintetico")  # deny-list roster
        ok = self._rev("XX ZZ 05", self.pdf)
        self.assertEqual([r.pk for r in revisioni_da_estrarre()], [ok.pk])

    def test_comando(self):
        self._rev("XX ZZ 01", self.pdf)
        out = io.StringIO()
        call_command("sgi_estrai_testi", "--dry-run", stdout=out)
        self.assertIn("Revisioni da estrarre: 1", out.getvalue())
        self.assertFalse(SgiTestoEstratto.objects.exists())
        call_command("sgi_estrai_testi", stdout=io.StringIO())
        self.assertEqual(SgiTestoEstratto.objects.count(), 1)
        out = io.StringIO()
        call_command("sgi_estrai_testi", stdout=out)
        self.assertIn("Revisioni da estrarre: 0", out.getvalue())


class CatenaTaskTests(_RevisioneMixin, TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.pdf = self.dir / "doc.pdf"
        pdf_documento(self.pdf, pagine=1)

    def tearDown(self):
        self._tmp.cleanup()

    def test_flag_spento_non_estrae(self):
        from procedure_refresh.tasks import accoda_estrazione_sgi, run_sgi_estrazione_un_documento

        rev = self._rev("XX ZZ 01", self.pdf)
        with override_settings(SGI_ESTRAZIONE_PERSISTITA_ENABLED=False):
            self.assertFalse(accoda_estrazione_sgi())
            res = run_sgi_estrazione_un_documento(rev.pk)
        self.assertTrue(res["stato"].startswith("saltato"))
        self.assertFalse(SgiTestoEstratto.objects.exists())

    @override_settings(SGI_ESTRAZIONE_PERSISTITA_ENABLED=True)
    def test_catena_un_documento_per_task_poi_reindex(self):
        from procedure_refresh.tasks import accoda_estrazione_sgi, run_sgi_estrazione_un_documento

        r1 = self._rev("XX ZZ 01", self.pdf)
        r2 = self._rev("XX ZZ 02", self.pdf, file_hash="h2")
        with mock.patch("django_q.tasks.async_task") as m:
            self.assertTrue(accoda_estrazione_sgi(reindex=True))
            m.assert_called_once_with(
                "procedure_refresh.tasks.run_sgi_estrazione_un_documento", r1.pk, coda=[r2.pk], reindex=True,
            )
        with mock.patch("django_q.tasks.async_task") as m:
            res = run_sgi_estrazione_un_documento(r1.pk, coda=[r2.pk], reindex=True)
            self.assertEqual(res["stato"], "estratto")
            m.assert_called_once_with(
                "procedure_refresh.tasks.run_sgi_estrazione_un_documento", r2.pk, coda=[], reindex=True,
            )
        with mock.patch("django_q.tasks.async_task") as m:
            run_sgi_estrazione_un_documento(r2.pk, coda=[], reindex=True)
            m.assert_called_once_with("ai_assistant.tasks.run_index_sgi_documents")
        self.assertEqual(SgiTestoEstratto.objects.count(), 2)
        with mock.patch("django_q.tasks.async_task") as m:
            self.assertFalse(accoda_estrazione_sgi())  # tutto aggiornato
            m.assert_not_called()

    @override_settings(SGI_ESTRAZIONE_PERSISTITA_ENABLED=True)
    def test_errore_non_interrompe_la_catena(self):
        from procedure_refresh.tasks import run_sgi_estrazione_un_documento

        with mock.patch("django_q.tasks.async_task") as m, \
                mock.patch("procedure_refresh.sgi_testo.persisti_estrazione", side_effect=RuntimeError):
            res = run_sgi_estrazione_un_documento(self._rev("XX ZZ 01", self.pdf).pk, coda=[999])
        self.assertTrue(res["stato"].startswith("errore"))
        m.assert_called_once()

    def test_auto_sync_accoda_estrazione_con_flag(self):
        from core.models import SiteConfig
        from procedure_refresh.tasks import run_sgi_auto_sync

        share = self.dir / "share" / "9100_Qualita"
        share.mkdir(parents=True)
        pdf_documento(share / "MT CN 97 Rev.1_Documento sintetico.pdf", pagine=1)
        SiteConfig.set("pr_sgi_auto_sync_attivo", "1", "test")
        with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=str(self.dir / "share"),
                               SGI_ESTRAZIONE_PERSISTITA_ENABLED=True), \
                mock.patch("django_q.tasks.async_task") as m:
            res = run_sgi_auto_sync(reindex=True)
        self.assertTrue(res.get("estrazione_accodata"))
        self.assertEqual(m.call_args.args[0], "procedure_refresh.tasks.run_sgi_estrazione_un_documento")
        self.assertTrue(m.call_args.kwargs["reindex"])


class PrecedenzaPdfTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        area = self.root / "9100_Qualita"
        area.mkdir()
        pdf_documento(area / "XX ZZ 01 Rev.3_Documento sintetico.pdf", pagine=1)
        (area / "XX ZZ 01 Rev.3_Documento sintetico.docx").write_bytes(b"PK")
        (area / "XX ZZ 02 Rev.4_Altro sintetico.docx").write_bytes(b"PK")
        (area / "~$ ZZ 02 Rev.4_Altro sintetico.docx").write_bytes(b"lock")

    def tearDown(self):
        self._tmp.cleanup()

    def _scan(self):
        from procedure_refresh.management.commands.import_sgi_da_share import scan_share_candidates

        return scan_share_candidates(self.root)

    def test_default_solo_pdf(self):
        candidates, _s, conflicts = self._scan()
        self.assertEqual([c["file_name"] for c in candidates], ["XX ZZ 01 Rev.3_Documento sintetico.pdf"])
        self.assertEqual(conflicts, [])

    @override_settings(PROCEDURE_REFRESH_SGI_EXTENSIONS=[".pdf", ".docx"])
    def test_stesso_codice_e_revisione_vince_il_pdf(self):
        candidates, _s, conflicts = self._scan()
        nomi = sorted(c["file_name"] for c in candidates)
        self.assertEqual(nomi, ["XX ZZ 01 Rev.3_Documento sintetico.pdf", "XX ZZ 02 Rev.4_Altro sintetico.docx"])
        self.assertEqual(conflicts[0]["scartato"], "XX ZZ 01 Rev.3_Documento sintetico.docx")

    @override_settings(PROCEDURE_REFRESH_SGI_EXTENSIONS=[".pdf", ".docx"], PROCEDURE_REFRESH_SGI_PREFER_PDF=False)
    def test_senza_preferenza_decide_il_nome_file(self):
        candidates, _s, _c = self._scan()
        self.assertIn("XX ZZ 01 Rev.3_Documento sintetico.pdf", [c["file_name"] for c in candidates])


class LetturaRagTests(_RevisioneMixin, TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pdf = Path(self._tmp.name) / "doc.pdf"
        pdf_documento(self.pdf, pagine=1)
        self.rev = self._rev("XX ZZ 01", self.pdf)
        SgiTestoEstratto.objects.create(
            revision=self.rev, file_hash="h1", formato="pdf", metodo="pymupdf_layout", testo="TESTO PERSISTITO",
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _testo(self):
        from django.core.cache import cache

        from ai_assistant.services import _sgi_extract_procedure_text

        cache.clear()
        return _sgi_extract_procedure_text(self.rev)

    def test_flag_spento_legge_il_pdf_come_prima(self):
        with override_settings(SGI_ESTRAZIONE_PERSISTITA_ENABLED=False):
            testo = self._testo()
        self.assertNotIn("TESTO PERSISTITO", testo)
        self.assertIn("Sezione sintetica numero 1", testo)

    def test_flag_acceso_legge_il_persistito_se_hash_coincide(self):
        with override_settings(SGI_ESTRAZIONE_PERSISTITA_ENABLED=True):
            self.assertEqual(self._testo(), "TESTO PERSISTITO")
            self.rev.file_hash = "cambiato"
            self.rev.save()
            self.assertIn("Sezione sintetica numero 1", self._testo())

    def test_safe_doc_path(self):
        from ai_assistant.services import _sgi_safe_doc_path, _sgi_safe_pdf_path

        self.assertEqual(_sgi_safe_pdf_path(str(self.pdf)), self.pdf)
        self.assertIsNone(_sgi_safe_doc_path(str(self.pdf), (".docx",)))
        self.assertIsNone(_sgi_safe_pdf_path(str(self.pdf) + ".mancante"))


class ChunkingSgiTests(TestCase):
    TESTO = "1. Scopo\n" + "parola " * 60 + "\n\n2. Tabella\n| A | B |\n|---|---|\n" + "".join(
        f"| riga {i} valore | dato {i} |\n" for i in range(40)
    )

    def _chunks(self, max_chars=300):
        from ai_assistant.services import _sgi_chunks_from_text

        return _sgi_chunks_from_text(source="proc:XX#rev3", doc_label="XX Rev.3", text=self.TESTO, max_chars=max_chars)

    def test_header_spento_identico_allo_split_storico(self):
        from ai_assistant.services import _sgi_sections, _split_long_section

        testo = "1. Scopo\nTesto semplice senza tabelle.\n\n2. Campo\nAltro testo."
        from ai_assistant.services import _sgi_chunks_from_text

        nuovi = _sgi_chunks_from_text(source="s", doc_label="D", text=testo, max_chars=300)
        storici = []
        for label, body in _sgi_sections(testo):
            storici.extend(_split_long_section("s", f"D — {label}" if label else "D", body, max_chars=300))
        self.assertEqual([(c.title, c.content) for c in nuovi], [(c.title, c.content) for c in storici])

    def test_tabelle_mai_spezzate_a_meta_riga(self):
        for chunk in self._chunks():
            for line in chunk.content.splitlines():
                if "|" in line:
                    self.assertTrue(line.startswith("|") and line.endswith("|"), line)
        tabellari = [c for c in self._chunks() if "| riga" in c.content]
        self.assertGreater(len(tabellari), 1)
        for c in tabellari:
            self.assertIn("| A | B |", c.content)  # intestazione ripetuta

    @override_settings(OLLAMA_RAG_SGI_CHUNK_HEADER=True)
    def test_header_nel_testo_del_chunk(self):
        chunks = self._chunks()
        self.assertTrue(all(c.content.startswith("XX Rev.3 — §") for c in chunks))
        self.assertIn("XX Rev.3 — §2 Tabella\n", chunks[-1].content)

    def test_chunk_chars_sgi_default_e_override(self):
        from ai_assistant.services import _sgi_chunk_chars

        with override_settings(OLLAMA_RAG_CHUNK_CHARS=900, OLLAMA_RAG_SGI_CHUNK_CHARS=900):
            self.assertEqual(_sgi_chunk_chars(), 900)
        with override_settings(OLLAMA_RAG_SGI_CHUNK_CHARS=1400):
            self.assertEqual(_sgi_chunk_chars(), 1400)
