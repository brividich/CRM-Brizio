"""Storage privato cifrato per allegati di modulo, con lettura dei file storici.

I nuovi file vanno in ``settings.PRIVATE_ATTACHMENTS_ROOT`` (default
``media_private/``), fuori dalla webroot e cifrati at-rest. I file caricati prima
del passaggio restano in ``MEDIA_ROOT``: si leggono ancora (solo tramite view
protette) ma IIS non li serve piu' (vedi ``denyUrlSequences`` nel web.config).
Nessuna URL pubblica: ``url()`` solleva, il download passa da una view con ACL.
"""
from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible

from core.encrypted_storage import EncryptedStorageMixin


@deconstructible
class PrivateAttachmentStorage(EncryptedStorageMixin, FileSystemStorage):
    def __init__(self, download_hint: str = "", **kwargs):
        self.download_hint = download_hint
        super().__init__(**kwargs)

    @property
    def base_location(self):
        return str(settings.PRIVATE_ATTACHMENTS_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise NotImplementedError(
            f"Allegato privato: niente URL pubblica. {self.download_hint or 'Usa la view di download protetta.'}"
        )

    def _legacy_path(self, name: str | None) -> Path | None:
        if not name:
            return None
        media_root = Path(settings.MEDIA_ROOT).resolve()
        try:
            candidate = (media_root / name).resolve()
        except OSError:
            return None
        if not candidate.is_relative_to(media_root):
            return None
        return candidate

    def exists(self, name):
        legacy_path = self._legacy_path(name)
        try:
            return super().exists(name) or bool(legacy_path and legacy_path.exists())
        except (OSError, SuspiciousFileOperation, ValueError):
            return False

    def open(self, name, mode="rb"):
        try:
            if super().exists(name):
                return super().open(name, mode)
        except (OSError, SuspiciousFileOperation, ValueError):
            pass
        legacy_path = self._legacy_path(name)
        if legacy_path and legacy_path.exists():
            return legacy_path.open(mode)
        raise FileNotFoundError(name)

    def size(self, name):
        try:
            if super().exists(name):
                return super().size(name)
        except (OSError, SuspiciousFileOperation, ValueError):
            pass
        legacy_path = self._legacy_path(name)
        if legacy_path and legacy_path.exists():
            return legacy_path.stat().st_size
        raise FileNotFoundError(name)

    def delete(self, name):
        try:
            if super().exists(name):
                super().delete(name)
        except (OSError, SuspiciousFileOperation, ValueError):
            pass
        legacy_path = self._legacy_path(name)
        if legacy_path and legacy_path.exists():
            try:
                legacy_path.unlink()
            except OSError:
                pass
