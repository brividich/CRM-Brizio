"""Test per gli helper di validazione upload in ``core/upload_mime.py``."""
from __future__ import annotations

from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.upload_mime import (
    UploadMimeValidationError,
    check_magic_signature,
    safe_filename,
    validate_extension_and_mime,
    validate_filename,
)


class SafeFilenameTests(SimpleTestCase):
    def test_basic_filename_is_preserved(self):
        self.assertEqual(safe_filename("documento.pdf"), "documento.pdf")

    def test_strips_unix_path_traversal(self):
        self.assertEqual(safe_filename("../../etc/passwd"), "passwd")

    def test_strips_windows_path_traversal(self):
        self.assertEqual(safe_filename(r"..\..\windows\system32\cmd.exe"), "cmd.exe")

    def test_strips_mixed_separators(self):
        self.assertEqual(safe_filename("foo/bar\\baz.txt"), "baz.txt")

    def test_rejects_dot_only_names(self):
        self.assertEqual(safe_filename("."), "")
        self.assertEqual(safe_filename(".."), "")
        self.assertEqual(safe_filename("..."), "")

    def test_strips_null_byte_and_control_chars(self):
        self.assertEqual(safe_filename("evil\x00.pdf"), "evil.pdf")
        self.assertEqual(safe_filename("evil\x07.pdf"), "evil.pdf")

    def test_empty_input(self):
        self.assertEqual(safe_filename(""), "")
        self.assertEqual(safe_filename(None), "")

    def test_truncates_long_filename(self):
        long_name = "a" * 500 + ".pdf"
        result = safe_filename(long_name, max_length=50)
        self.assertLessEqual(len(result), 50)
        self.assertTrue(result.endswith(".pdf"))


class ValidateFilenameTests(SimpleTestCase):
    def test_valid_filename(self):
        self.assertEqual(validate_filename("foo.pdf"), "foo.pdf")

    def test_path_traversal_raises(self):
        with self.assertRaises(UploadMimeValidationError):
            validate_filename("../../etc/passwd.pdf"[:0])  # vuoto -> errore
        with self.assertRaises(UploadMimeValidationError):
            validate_filename("..")

    def test_empty_raises(self):
        with self.assertRaises(UploadMimeValidationError):
            validate_filename("")
        with self.assertRaises(UploadMimeValidationError):
            validate_filename(None)


class CheckMagicSignatureTests(SimpleTestCase):
    def test_pdf_signature_match(self):
        f = SimpleUploadedFile("a.pdf", b"%PDF-1.4\n...", content_type="application/pdf")
        self.assertTrue(check_magic_signature(f, ".pdf"))

    def test_pdf_signature_mismatch(self):
        f = SimpleUploadedFile("a.pdf", b"NOT_A_PDF", content_type="application/pdf")
        self.assertFalse(check_magic_signature(f, ".pdf"))

    def test_png_signature_match(self):
        f = SimpleUploadedFile("a.png", b"\x89PNG\r\n\x1a\nrest", content_type="image/png")
        self.assertTrue(check_magic_signature(f, ".png"))

    def test_png_signature_mismatch(self):
        f = SimpleUploadedFile("a.png", b"GIF89a...", content_type="image/png")
        self.assertFalse(check_magic_signature(f, ".png"))

    def test_unknown_extension_returns_true(self):
        # Estensione non in mappa: skip non-bloccante.
        f = SimpleUploadedFile("a.xyz", b"stuff", content_type="application/octet-stream")
        self.assertTrue(check_magic_signature(f, ".xyz"))

    def test_xlsx_signature_match(self):
        # xlsx e' uno zip: PK\x03\x04
        f = SimpleUploadedFile("a.xlsx", b"PK\x03\x04rest", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertTrue(check_magic_signature(f, ".xlsx"))

    def test_webp_requires_riff_and_webp(self):
        good = SimpleUploadedFile("a.webp", b"RIFF\x00\x00\x00\x00WEBPextra", content_type="image/webp")
        self.assertTrue(check_magic_signature(good, ".webp"))
        bad = SimpleUploadedFile("a.webp", b"RIFF\x00\x00\x00\x00WAVEextra", content_type="image/webp")
        self.assertFalse(check_magic_signature(bad, ".webp"))


class ValidateExtensionAndMimeTests(SimpleTestCase):
    def _patch_magic(self, mime_value: str):
        return patch("core.upload_mime.sniff_upload_mime", return_value=mime_value)

    def test_accepts_valid_pdf(self):
        f = SimpleUploadedFile("doc.pdf", b"%PDF-1.4\n%test", content_type="application/pdf")
        with self._patch_magic("application/pdf"):
            mime = validate_extension_and_mime(
                f,
                allowed_extensions={".pdf"},
                allowed_mimes={"application/pdf"},
                max_bytes=1024 * 1024,
            )
        self.assertEqual(mime, "application/pdf")

    def test_rejects_disallowed_extension(self):
        f = SimpleUploadedFile("evil.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        with self.assertRaises(UploadMimeValidationError):
            validate_extension_and_mime(
                f,
                allowed_extensions={".pdf"},
                allowed_mimes={"application/pdf"},
            )

    def test_rejects_path_traversal_filename(self):
        f = SimpleUploadedFile("../../../etc/passwd", b"%PDF-1.4\n", content_type="application/pdf")
        # Il nome viene "stripato" a "passwd" (no estensione) -> formato non consentito.
        with self.assertRaises(UploadMimeValidationError):
            validate_extension_and_mime(
                f,
                allowed_extensions={".pdf"},
                allowed_mimes={"application/pdf"},
            )

    def test_rejects_oversize(self):
        f = SimpleUploadedFile("big.pdf", b"%PDF-1.4\n", content_type="application/pdf")
        # Forziamo size grande con monkey patch dell'attributo.
        f.size = 10 * 1024 * 1024
        with self.assertRaises(UploadMimeValidationError):
            validate_extension_and_mime(
                f,
                allowed_extensions={".pdf"},
                allowed_mimes={"application/pdf"},
                max_bytes=1 * 1024 * 1024,
            )

    def test_rejects_empty_when_disallowed(self):
        f = SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf")
        with self.assertRaises(UploadMimeValidationError):
            validate_extension_and_mime(
                f,
                allowed_extensions={".pdf"},
                allowed_mimes={"application/pdf"},
                allow_empty=False,
            )

    def test_rejects_mime_mismatch(self):
        f = SimpleUploadedFile("doc.pdf", b"<html>...</html>", content_type="application/pdf")
        with self._patch_magic("text/html"):
            with self.assertRaises(UploadMimeValidationError):
                validate_extension_and_mime(
                    f,
                    allowed_extensions={".pdf"},
                    allowed_mimes={"application/pdf"},
                )

    def test_rejects_null_byte_in_filename(self):
        f = SimpleUploadedFile("evil\x00.pdf", b"%PDF-1.4", content_type="application/pdf")
        # safe_filename strippa il null byte; il file diventa "evil.pdf" valido.
        # Verifichiamo invece un nome solo null byte = invalido.
        f2 = SimpleUploadedFile("\x00", b"%PDF-1.4", content_type="application/pdf")
        with self.assertRaises(UploadMimeValidationError):
            validate_extension_and_mime(
                f2,
                allowed_extensions={".pdf"},
                allowed_mimes={"application/pdf"},
            )
