from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage

from core.encrypted_storage import EncryptedStorageMixin


class PrivateDiarioPrepostoStorage(EncryptedStorageMixin, FileSystemStorage):
    """
    Storage privato per gli allegati delle segnalazioni del Diario Preposto.

    I nuovi file vengono salvati in ``DIARIO_PREPOSTO_PRIVATE_ROOT`` e non
    espongono URL diretti pubblici. I file legacy rimasti in ``MEDIA_ROOT``
    continuano a essere leggibili solo tramite la view di download protetta.
    """

    @property
    def base_location(self):
        return str(settings.DIARIO_PREPOSTO_PRIVATE_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

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

    def url(self, name):
        raise NotImplementedError(
            "Usa reverse('diario_preposto:allegato_download', args=[id]) al posto di .file.url"
        )

    def delete(self, name):
        # Rimuove sia dal nuovo storage privato sia dal path legacy in MEDIA_ROOT.
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
