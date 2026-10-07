"""Limite unico per l'upload di documenti e allegati.

Il valore nasce da ``UPLOAD_MAX_FILE_MB`` nel ``.env`` (default 100 MB) ed e'
condiviso da tutti i moduli che caricano documenti: assets, anagrafica,
anomalie, tickets, tasks, DPI, SDS, diario preposto, RENTRI, fornitori,
notizie, sistema di gestione, bacheca.

Restano fuori, con il loro limite dedicato: loghi e immagini di branding,
import Excel/CSV, upload anonimi dalla landing QR pubblica.

Ricordare che IIS applica un tetto sull'intera richiesta
(``maxAllowedContentLength`` nel ``web.config``): deve essere >= a questo
valore, altrimenti IIS rifiuta il file prima che arrivi a Django.
"""

from django.conf import settings

_DEFAULT_MB = 100

DOCUMENT_MAX_MB = int(getattr(settings, "UPLOAD_MAX_FILE_MB", _DEFAULT_MB) or _DEFAULT_MB)
DOCUMENT_MAX_BYTES = DOCUMENT_MAX_MB * 1024 * 1024
