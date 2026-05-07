from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage


class PrivateAssetAdministrativeDeadlineStorage(FileSystemStorage):
    """
    Storage privato per gli allegati dei completamenti scadenze asset.
    I nuovi file vengono salvati in ASSETS_PRIVATE_ROOT e non espongono URL diretti.
    I file legacy rimasti in MEDIA_ROOT restano leggibili solo tramite view protetta.
    """

    @property
    def base_location(self):
        return str(settings.ASSETS_PRIVATE_ROOT)

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
            "Usa reverse('assets:admin_deadline_attachment_download', args=[id]) al posto di .file.url"
        )
