"""Upload dei documenti di anagrafica: tipo verificato dal contenuto, nessun ripiego
sul Content-Type del browser (prima un ``sniff_mime`` inesistente faceva sempre
fallire la verifica e si accettava qualunque cosa il browser dichiarasse).

I cinque punti di upload rifiutano un HTML rinominato .pdf anche se il browser lo
dichiara ``application/pdf``; i formati Office veri (anche quando libmagic li
etichetta in modo generico) passano solo con la firma binaria giusta.
"""
from __future__ import annotations

import io
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import DocumentoDipendente
from .models_formazione import (
    TrainingAttachment, TrainingCourse, TrainingEnrollment, TrainingPlan, TrainingProvider,
    TrainingProviderDocument, TrainingSession,
)
from .services.upload_documenti import UploadMimeValidationError, valida_documento

User = get_user_model()
HTML = b"<!doctype html><html><body><script>alert(1)</script></body></html>"
PDF = b"%PDF-1.4\n% documento sintetico\n"
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 2040


def _html_finto_pdf():
    return SimpleUploadedFile("documento.pdf", HTML, content_type="application/pdf")


def _xlsx():
    from openpyxl import Workbook
    buf = io.BytesIO()
    Workbook().save(buf)
    return buf.getvalue()


class ValidaDocumentoTests(TestCase):
    def test_html_rinominato_rifiutato(self):
        for nome in ("documento.pdf", "documento.docx", "documento.xls", "documento.msg"):
            with self.subTest(nome=nome), self.assertRaises(UploadMimeValidationError):
                valida_documento(SimpleUploadedFile(nome, HTML, content_type="application/pdf"),
                                 {".pdf", ".docx", ".xls", ".msg"})

    def test_formati_veri_accettati(self):
        estensioni = {".pdf", ".xlsx", ".xls", ".msg"}
        self.assertEqual(valida_documento(SimpleUploadedFile("a.pdf", PDF), estensioni), "application/pdf")
        self.assertEqual(valida_documento(SimpleUploadedFile("a.xlsx", _xlsx()), estensioni),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(valida_documento(SimpleUploadedFile("a.xls", OLE), estensioni), "application/vnd.ms-excel")
        self.assertEqual(valida_documento(SimpleUploadedFile("a.msg", OLE), estensioni), "application/vnd.ms-outlook")

    def test_zip_qualunque_non_passa_per_pdf(self):
        with self.assertRaises(UploadMimeValidationError):
            valida_documento(SimpleUploadedFile("a.pdf", _xlsx()), {".pdf", ".xlsx"})

    def test_html_non_ammesso_nel_fascicolo(self):
        from .views import _ALLOWED_MANUAL_DOC_EXTENSIONS
        self.assertNotIn(".html", _ALLOWED_MANUAL_DOC_EXTENSIONS)


class CinquePuntiDiUploadTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("upl_admin_test", "u@example.invalid", "x")
        self.client.force_login(self.admin)
        piano = TrainingPlan.objects.create(codice="PUP", nome="Piano upload")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="CUP", titolo="Corso upload",
                                                   durata_ore_teorica=4)
        self.sess = TrainingSession.objects.create(corso=self.corso, codice_sessione="SUP1",
                                                   data_inizio=date.today(), data_fine=date.today())
        self.enr = TrainingEnrollment.objects.create(sessione=self.sess, legacy_anagrafica_id=901, stato="ISCRITTO")
        self.azienda = TrainingProvider.objects.create(nome="Ente sintetico upload")

    def _post(self, url, extra=None):
        with tempfile.TemporaryDirectory() as root, override_settings(ANAGRAFICA_PRIVATE_ROOT=root):
            return self.client.post(url, {"file": _html_finto_pdf(), **(extra or {})}, follow=True)

    def test_allegato_sessione(self):
        r = self._post(reverse("anagrafica:formazione_allegato_upload", args=[self.sess.pk]), {"tipo": "MATERIALE"})
        self.assertFalse(TrainingAttachment.objects.filter(sessione=self.sess).exists())
        self.assertContains(r, "File rifiutato")

    def test_allegato_corso(self):
        r = self._post(reverse("anagrafica:formazione_corso_allegato_upload", args=[self.corso.pk]))
        self.assertFalse(TrainingAttachment.objects.filter(corso=self.corso).exists())
        self.assertContains(r, "File rifiutato")

    def test_documento_dipendente(self):
        r = self._post(reverse("anagrafica:documento_upload", args=[902]))
        self.assertFalse(DocumentoDipendente.objects.filter(legacy_anagrafica_id=902).exists())
        self.assertContains(r, "File rifiutato")

    def test_documento_ente_formativo(self):
        r = self._post(reverse("anagrafica:formazione_azienda_documento_add", args=[self.azienda.pk]),
                       {"titolo": "Accreditamento"})
        self.assertFalse(TrainingProviderDocument.objects.exists())
        self.assertContains(r, "File rifiutato")

    def test_attestato_iscrizione(self):
        r = self._post(reverse("anagrafica:formazione_iscrizione_attestato_upload", args=[self.sess.pk, self.enr.pk]),
                       {"rilasciato_da": "Ente", "numero_attestato": "X-1"})
        self.enr.refresh_from_db()
        self.assertNotEqual(self.enr.stato, "COMPLETATO")
        self.assertContains(r, "File rifiutato")
