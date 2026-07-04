from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage

from core.encrypted_storage import EncryptedStorageMixin


class HubLinkStorage(EncryptedStorageMixin, FileSystemStorage):
    """Storage privato cifrato per i documenti della Bacheca (Documenti & Collegamenti).

    I file sono salvati in ``settings.HUB_BACHECA_PRIVATE_ROOT`` (default
    ``media_private/``), fuori dalla webroot, cifrati at-rest via
    ``DOCUMENT_ENCRYPTION_KEY``. L'accesso passa SEMPRE per la view protetta
    ``dashboard:hub_link_download`` (ACL per-voce + audit).
    """

    @property
    def base_location(self):
        return str(settings.HUB_BACHECA_PRIVATE_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise NotImplementedError(
            "I documenti della bacheca non sono serviti su URL pubblico. "
            "Usa {% url 'hub_link_download' link.id %}."
        )
