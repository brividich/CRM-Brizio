from __future__ import annotations

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateAnagraficaStorage(FileSystemStorage):
    """Storage privato per i documenti del dipendente.

    I file (PDF consegne DPI, referti visite mediche, contratti, ecc.) sono
    salvati in ``settings.ANAGRAFICA_PRIVATE_ROOT`` (default ``media_private/``),
    fuori dalla webroot. L'accesso passa SEMPRE per la view protetta
    ``anagrafica:documento_download`` che applica ACL e audit.
    """

    @property
    def base_location(self):
        return str(settings.ANAGRAFICA_PRIVATE_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise NotImplementedError(
            "I documenti dipendente non sono serviti su URL pubblico. "
            "Usa {% url 'anagrafica:documento_download' doc.id %}."
        )
