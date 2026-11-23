"""Validazione lato server dei documenti caricati in anagrafica (attestati, materiale
corsi, fascicolo dipendente, documenti degli enti formativi).

Il tipo si decide dal **contenuto**, mai dal Content-Type dichiarato dal browser,
e senza ripieghi: se la verifica non riesce, l'upload è rifiutato.

libmagic legge i primi byte e per i formati Office restituisce etichette
generiche (``application/zip`` per un .xlsx, ``application/octet-stream`` per
un .docx, ``application/CDFV2`` per .doc/.xls/.msg): sono accettate solo per
l'estensione giusta **e** se la firma binaria del file coincide (un HTML
rinominato .docx non ha la firma ZIP).
"""
from __future__ import annotations

from core.upload_limits import DOCUMENT_MAX_BYTES
from core.upload_mime import MIME_PER_ESTENSIONE, UploadMimeValidationError, valida_per_estensione  # noqa: F401


def valida_documento(uploaded_file, estensioni: set[str], *, label: str = "File") -> str:
    """Ritorna il MIME da registrare; solleva ``UploadMimeValidationError`` se non ammesso.

    La tabella dei tipi e il controllo della firma sono quelli unici di ``core.upload_mime``.
    """
    return valida_per_estensione(uploaded_file, estensioni, max_bytes=DOCUMENT_MAX_BYTES, label=label)
