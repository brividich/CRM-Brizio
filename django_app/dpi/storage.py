from __future__ import annotations

from anagrafica.storage import PrivateAnagraficaStorage


class PrivateDpiDocumentStorage(PrivateAnagraficaStorage):
    """Storage privato (fuori webroot, cifrato at-rest) del raccoglitore documenti DPI.

    Stessa radice dei documenti anagrafica (``ANAGRAFICA_PRIVATE_ROOT``): nessuna
    nuova variabile d'ambiente da configurare al deploy. Accesso solo dalla view
    ``dpi:documento_download``."""

    def url(self, name):
        raise NotImplementedError("Usa reverse('dpi:documento_download', args=[id]).")
