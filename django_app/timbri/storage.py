from django.conf import settings
from django.core.files.storage import FileSystemStorage

from core.encrypted_storage import EncryptedStorageMixin


class PrivateTimbriStorage(EncryptedStorageMixin, FileSystemStorage):
    """
    Storage per immagini timbri/firme.
    Salva in TIMBRI_PRIVATE_ROOT, mai esposta dal web server.
    I file vengono serviti esclusivamente dalla view `timbri_serve_image`
    che verifica i permessi ACL prima di restituire il contenuto.
    I file sono cifrati at rest con AES-256 Fernet (DOCUMENT_ENCRYPTION_KEY).
    """

    def __init__(self):
        super().__init__(
            location=settings.TIMBRI_PRIVATE_ROOT,
            base_url=None,
        )

    def url(self, name):
        raise NotImplementedError(
            "Usa {% url 'timbri:serve_image' image_id %} al posto di .image.url"
        )
