from django.conf import settings
from django.core.files.storage import FileSystemStorage

from core.encrypted_storage import EncryptedStorageMixin


class PrivateTasksStorage(EncryptedStorageMixin, FileSystemStorage):
    """Storage privato per allegati KICK-OFF/Task e documenti VRF.

    Salva in ``TASKS_PRIVATE_ROOT`` (fuori dalla webroot, mai servita da IIS) e
    cifra at-rest con AES-256 Fernet (``DOCUMENT_ENCRYPTION_KEY``). L'accesso passa
    solo dalle view protette ``tasks:task_attachment_download`` e
    ``tasks:project_vrf_download`` (scope OWN/TEAM + permessi modulo).
    """

    def __init__(self):
        super().__init__(location=settings.TASKS_PRIVATE_ROOT, base_url=None)

    def url(self, name):
        raise NotImplementedError(
            "Gli allegati/VRF dei task non sono serviti su URL pubblico. "
            "Usa le view tasks:task_attachment_download / tasks:project_vrf_download."
        )
