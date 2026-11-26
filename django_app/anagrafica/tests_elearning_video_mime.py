"""Video MP4 che libmagic non riconosce («application/octet-stream»): si accettano se la struttura
è quella di un MP4. Dati sintetici."""
from __future__ import annotations

import io
import struct
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from core.upload_mime import UploadMimeValidationError

from .services import elearning_video as ev


def _box(tipo: bytes, corpo: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(corpo), tipo) + corpo


def _mp4(prima: bytes = b"") -> bytes:
    return prima + _box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41") + _box(b"mdat", b"\x00" * 64)


class Mp4Tests(SimpleTestCase):
    def test_struttura(self):
        self.assertTrue(ev.sembra_mp4(io.BytesIO(_mp4())))
        self.assertTrue(ev.sembra_mp4(io.BytesIO(_mp4(_box(b"free", b"\x00" * 8) + _box(b"wide")))))
        self.assertFalse(ev.sembra_mp4(io.BytesIO(b"MZ" + b"\x00" * 200)))
        self.assertFalse(ev.sembra_mp4(io.BytesIO(b"<html>" + b" " * 100)))

    def test_octet_stream_ma_mp4_accettato(self):
        f = SimpleUploadedFile("lezione.mp4", _mp4(_box(b"free")), content_type="video/mp4")
        with mock.patch("core.upload_mime.sniff_upload_mime", return_value="application/octet-stream"):
            ev.valida_video(f, 10 * 1024 * 1024)

    def test_octet_stream_non_mp4_rifiutato(self):
        f = SimpleUploadedFile("lezione.mp4", b"\x00\x01\x02" * 100, content_type="video/mp4")
        with mock.patch("core.upload_mime.sniff_upload_mime", return_value="application/octet-stream"):
            with self.assertRaises(UploadMimeValidationError):
                ev.valida_video(f, 10 * 1024 * 1024)

    def test_quicktime_accettato_e_estensione_obbligatoria(self):
        f = SimpleUploadedFile("lezione.mp4", _mp4(), content_type="video/mp4")
        with mock.patch("core.upload_mime.sniff_upload_mime", return_value="video/quicktime"):
            ev.valida_video(f, 10 * 1024 * 1024)
        g = SimpleUploadedFile("lezione.exe", _mp4(), content_type="video/mp4")
        with mock.patch("core.upload_mime.sniff_upload_mime", return_value="video/mp4"):
            with self.assertRaises(UploadMimeValidationError):
                ev.valida_video(g, 10 * 1024 * 1024)
