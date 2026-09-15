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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CartelleRiservateTests(TestCase):
    """I documenti delle cartelle `solo_admin` restano ai super-amministratori
    anche nella scheda dipendente e col link diretto di download."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from django.core.files.base import ContentFile

        self.private = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.private, ignore_errors=True)
        override = override_settings(ANAGRAFICA_PRIVATE_ROOT=str(self.private))
        override.enable()
        self.addCleanup(override.disable)

        _ensure_anagrafica_table()
        self.legacy_id = _insert_dipendente(7101, "Mario", "Rossi")
        User = get_user_model()
        self.superuser = User.objects.create_superuser("riserv_super", "s@example.invalid", "x")
        self.hr = User.objects.create_user("riserv_hr", "h@example.invalid", "x")

        riservata = CartellaDocumentoDipendente.objects.create(nome="Richiami", solo_admin=True)
        normale = CartellaDocumentoDipendente.objects.create(nome="Contratti")
        self.doc_riservato = self._doc(riservata, "richiamo_sintetico.pdf", ContentFile)
        self.doc_normale = self._doc(normale, "contratto_sintetico.pdf", ContentFile)

    def _doc(self, cartella, nome, ContentFile):
        doc = DocumentoDipendente(
            legacy_anagrafica_id=self.legacy_id, tipo=DocumentoDipendente.Tipo.MANUALE,
            cartella=cartella, nome_originale=nome, tipo_mime="application/pdf",
        )
        doc.file.save(nome, ContentFile(PDF), save=True)
        return doc

    def _download(self, user, doc):
        # View chiamata direttamente: qui si verifica il suo controllo, non il
        # middleware ACL (che per un utente senza binding reindirizza prima).
        from unittest.mock import patch

        from django.test import RequestFactory

        from .views import documento_dipendente_download

        request = RequestFactory().get(f"/anagrafica/documenti/{doc.pk}/download")
        request.user = user
        with patch("anagrafica.views._check_hr_permission", return_value=True):
            return documento_dipendente_download(request, doc_id=doc.pk)

    def test_download_riservato_negato_a_hr_non_superuser(self):
        self.assertEqual(self._download(self.hr, self.doc_riservato).status_code, 403)
        self.assertEqual(self._download(self.hr, self.doc_normale).status_code, 200)

    def test_download_riservato_consentito_al_superuser(self):
        self.assertEqual(self._download(self.superuser, self.doc_riservato).status_code, 200)

    def test_scheda_nasconde_riservati_ai_non_superuser(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.signed_cookies import SessionStore
        from django.test import RequestFactory
        from unittest.mock import patch

        from .views import dipendente_detail

        def nomi_visibili(user):
            request = RequestFactory().get(f"/anagrafica/dipendenti/{self.legacy_id}/")
            request.user = user
            request.session = SessionStore()
            request._messages = FallbackStorage(request)
            with patch("anagrafica.views.render") as render:
                dipendente_detail(request, legacy_id=self.legacy_id)
            if not render.called:
                return None
            context = render.call_args.args[2]
            return {d.nome_originale for d in context["documenti_dipendente"]}

        self.assertEqual(
            nomi_visibili(self.superuser), {"richiamo_sintetico.pdf", "contratto_sintetico.pdf"}
        )
        self.hr.is_staff = True
        self.hr.save()
        with patch("anagrafica.views._check_hr_permission", return_value=True), \
                patch("anagrafica.views._is_anagrafica_admin", return_value=True):
            visibili = nomi_visibili(self.hr)
        self.assertIsNotNone(visibili, "la scheda non è stata renderizzata per l'utente HR")
        self.assertEqual(visibili, {"contratto_sintetico.pdf"})
