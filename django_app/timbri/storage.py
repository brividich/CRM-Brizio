from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateTimbriStorage(FileSystemStorage):
    """
    Storage per immagini timbri/firme.
    Salva in TIMBRI_PRIVATE_ROOT, una cartella mai esposta dal web server.
    I file vengono serviti esclusivamente dalla view `timbri_serve_image`
    che verifica i permessi ACL prima di restituire il contenuto.
    """

    def __init__(self):
        super().__init__(
            location=settings.TIMBRI_PRIVATE_ROOT,
            base_url=None,  # nessun URL diretto — solo view protetta
        )

    def url(self, name):
        # Non restituisce mai un URL diretto al file.
        # La view deve essere chiamata con l'id dell'immagine.
        raise NotImplementedError(
            "Usa {% url 'timbri:serve_image' image_id %} al posto di .image.url"
        )
