"""Storage privato per gli allegati delle specifiche.

Stesso pattern di `assets.storage`: i file vivono in
``GESTIONE_SPECIFICHE_PRIVATE_ROOT`` (fuori webroot), non espongono URL diretti
e si scaricano solo tramite la view protetta. Cifratura a riposo via
``EncryptedStorageMixin``.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.text import get_valid_filename

from core.encrypted_storage import EncryptedStorageMixin


class PrivateSpecificaStorage(EncryptedStorageMixin, FileSystemStorage):
    """Storage privato (cifrato) per gli allegati `Specifica.allegato`."""

    @property
    def base_location(self):
        return str(settings.GESTIONE_SPECIFICHE_PRIVATE_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise NotImplementedError(
            "Allegato privato: usa reverse('gestione_specifiche:allegato_download', args=[pk])"
        )


def specifica_allegato_storage() -> PrivateSpecificaStorage:
    """Callable di storage (referenziata per import-path nelle migrazioni)."""
    return PrivateSpecificaStorage()


def upload_to_specifica(instance, filename: str) -> str:
    safe_code = get_valid_filename(getattr(instance, "codice", "") or "spec")
    return f"gestione_specifiche/{safe_code}/{get_valid_filename(filename)}"
