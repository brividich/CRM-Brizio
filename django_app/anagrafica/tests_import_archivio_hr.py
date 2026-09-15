"""Import dell'archivio HR TOOLS nel fascicolo documentale (dati sintetici)."""
from __future__ import annotations

import csv
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import AuditLog

from .models import CartellaDocumentoDipendente, DocumentoDipendente
from .tests import _ensure_anagrafica_table
from .tests_exports_persone import _insert_dipendente

PDF = b"%PDF-1.4 sintetico"


class ImportArchivioHrTests(TestCase):
    def setUp(self):
        self.private = Path(tempfile.mkdtemp())
        self.src = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.private, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.src, ignore_errors=True)
        override = override_settings(ANAGRAFICA_PRIVATE_ROOT=str(self.private))
        override.enable()
        self.addCleanup(override.disable)

        _ensure_anagrafica_table()
        self.rossi = _insert_dipendente(7001, "Mario", "Rossi")
        self.de_luca = _insert_dipendente(7002, "Anna Maria", "De Luca")
        # Stesse parole con nome e cognome invertiti: due persone, abbinamento ambiguo.
        # (Righe con nome e cognome identici il portale le fonde già in una persona.)
        _insert_dipendente(7003, "Luca", "Bianchi")
        _insert_dipendente(7004, "Bianchi", "Luca")

        self._file("Contratti/ROSSI_MARIO/contratto.pdf", PDF)
        self._file("VISITE MEDICHE/ROSSI_MARIO/idoneita.pdf", PDF)
        self._file("!Richiami!/DE_LUCA_ANNA_MARIA/richiamo.pdf", PDF)
        self._file("DPI/ROSSI___________MARIO/consegna.pdf", PDF)
        self._file("DPI/ROSSI_MARIO/foto.heic", b"xxxx")
        self._file("DPI/ROSSI_MARIO/finto.pdf", b"non un pdf")
        self._file("Contratti/BIANCHI_LUCA/contratto.pdf", PDF)
        self._file("Contratti/VERDI_GIUSEPPE/contratto.pdf", PDF + b" altro contenuto")
        self._file("Categoria Nuova/ROSSI_MARIO/x.pdf", PDF)

    def _file(self, rel: str, data: bytes):
        path = self.src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("importa_archivio_hr", str(self.src), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_non_scrive(self):
        out = self._run()
        self.assertIn("DRY-RUN", out)
        self.assertFalse(DocumentoDipendente.objects.exists())
        self.assertFalse(CartellaDocumentoDipendente.objects.exists())
        self.assertIn("VERDI_GIUSEPPE", out)
        self.assertIn("ambiguo", out)
        self.assertIn("Categoria Nuova", out)

    def test_apply_importa_con_tipi_cartelle_e_audit(self):
        self._run("--apply")
        docs = DocumentoDipendente.objects.select_related("cartella")
        self.assertEqual(docs.count(), 4)
        per_nome = {d.nome_originale: d for d in docs}

        contratto = per_nome["contratto.pdf"]
        self.assertEqual(contratto.legacy_anagrafica_id, self.rossi)
        self.assertEqual(contratto.tipo, DocumentoDipendente.Tipo.MANUALE)
        self.assertEqual(contratto.cartella.nome, "Contratti")
        self.assertEqual(contratto.cartella.parent.nome, "Archivio HR TOOLS")

        self.assertEqual(per_nome["idoneita.pdf"].tipo, DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO)
        self.assertEqual(per_nome["consegna.pdf"].tipo, DocumentoDipendente.Tipo.DPI_CONSEGNA)
        richiamo = per_nome["richiamo.pdf"]
        self.assertEqual(richiamo.legacy_anagrafica_id, self.de_luca)
        self.assertTrue(richiamo.cartella.solo_admin)

        with contratto.file.open("rb") as handle:
            self.assertEqual(handle.read(), PDF)
        self.assertEqual(
            AuditLog.objects.filter(azione="DOCUMENTO_DIPENDENTE_IMPORT_ARCHIVIO").count(), 2
        )

    def test_rieseguibile_senza_doppioni(self):
        self._run("--apply")
        out = self._run("--apply")
        self.assertEqual(DocumentoDipendente.objects.count(), 4)
        self.assertIn("già presente", out)

    def test_mappa_risolve_non_abbinati_e_report(self):
        mappa = self.src.parent / f"{self.src.name}_mappa.csv"
        mappa.write_text("cartella;legacy_id\nVERDI_GIUSEPPE;7001\nBIANCHI_LUCA;0\n", encoding="utf-8")
        report = self.src.parent / f"{self.src.name}_report.csv"
        self.addCleanup(mappa.unlink, missing_ok=True)
        self.addCleanup(report.unlink, missing_ok=True)

        self._run("--apply", "--mappa", str(mappa), "--report", str(report), "--categoria", "Contratti")
        self.assertEqual(
            DocumentoDipendente.objects.filter(legacy_anagrafica_id=self.rossi).count(), 2
        )
        with report.open(encoding="utf-8-sig") as handle:
            esiti = {(r["cartella_persona"], r["esito"]) for r in csv.DictReader(handle, delimiter=";")}
        self.assertIn(("VERDI_GIUSEPPE", "importato"), esiti)
        self.assertIn(("BIANCHI_LUCA", "persona non abbinata"), esiti)
