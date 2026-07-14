"""Storage privato per i PDF delle schede di sicurezza.

Stesso pattern di `gestione_specifiche.storage`: i file vivono in
``SCHEDE_SICUREZZA_PRIVATE_ROOT`` (fuori webroot), non espongono URL diretti e
si scaricano solo tramite la view protetta. Cifratura a riposo via
``EncryptedStorageMixin``.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.text import get_valid_filename

from core.encrypted_storage import EncryptedStorageMixin


class PrivateSchedaSicurezzaStorage(EncryptedStorageMixin, FileSystemStorage):
    """Storage privato (cifrato) per gli allegati `SchedaSicurezza.pdf`."""

    @property
    def base_location(self):
        return str(settings.SCHEDE_SICUREZZA_PRIVATE_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise NotImplementedError(
            "PDF privato: usa reverse('schede_sicurezza:scheda_download', args=[pk])"
        )


def upload_to_scheda_pdf(instance, filename: str) -> str:
    prodotto_id = instance.prodotto_id or "tmp"
    return f"schede_sicurezza/{prodotto_id}/{get_valid_filename(filename)}"
