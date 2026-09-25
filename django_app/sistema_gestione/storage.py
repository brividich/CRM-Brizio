from django.conf import settings
from django.core.files.storage import FileSystemStorage

from core.encrypted_storage import EncryptedStorageMixin


class PrivateSistemaGestioneStorage(EncryptedStorageMixin, FileSystemStorage):
    """Storage privato per le copie firmate dei documenti del sistema di gestione.

    Stessa radice privata dei task (``TASKS_PRIVATE_ROOT``, fuori dalla webroot),
    cifratura at-rest con ``DOCUMENT_ENCRYPTION_KEY``. I file si scaricano solo
    dalle view protette del modulo.
    """

    def __init__(self):
        super().__init__(location=settings.TASKS_PRIVATE_ROOT, base_url=None)

    def url(self, name):
        raise NotImplementedError("Le copie firmate si scaricano solo dalle view di sistema_gestione.")
