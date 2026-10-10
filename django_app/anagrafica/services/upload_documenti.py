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

from pathlib import Path

from core.upload_mime import UploadMimeValidationError, check_magic_signature, validate_extension_and_mime
from core.upload_limits import DOCUMENT_MAX_BYTES

_OFFICE_ZIP = {"application/zip", "application/octet-stream"}
_OLE = {"application/cdfv2", "application/x-ole-storage"}
_FIRMA_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

MIME_PER_ESTENSIONE: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"} | _OFFICE_ZIP,
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"} | _OFFICE_ZIP,
    ".doc": {"application/msword"} | _OLE,
    ".xls": {"application/vnd.ms-excel"} | _OLE,
    ".msg": {"application/vnd.ms-outlook", "application/x-msg"} | _OLE,
}

# Tipo registrato sul documento quando libmagic dà un'etichetta generica.
_MIME_CANONICO = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".msg": "application/vnd.ms-outlook",
}


def _firma_ok(uploaded_file, ext: str) -> bool:
    if ext == ".msg":  # non è nella tabella core: contenitore OLE
        try:
            head = uploaded_file.read(8)
        finally:
            uploaded_file.seek(0)
        return head == _FIRMA_OLE
    return check_magic_signature(uploaded_file, ext)


def valida_documento(uploaded_file, estensioni: set[str], *, label: str = "File") -> str:
    """Ritorna il MIME da registrare; solleva ``UploadMimeValidationError`` se non ammesso."""
    ext = Path(getattr(uploaded_file, "name", "") or "").suffix.lower()
    ammessi = MIME_PER_ESTENSIONE.get(ext, set()) if ext in estensioni else set()
    mime = validate_extension_and_mime(
        uploaded_file, allowed_extensions=estensioni, allowed_mimes=ammessi or {"-"},
        max_bytes=DOCUMENT_MAX_BYTES, label=label, allow_empty=False,
    )
    if not _firma_ok(uploaded_file, ext):
        raise UploadMimeValidationError(f"{label}: il contenuto non corrisponde all'estensione {ext}.")
    return _MIME_CANONICO.get(ext, mime) if mime in (_OFFICE_ZIP | _OLE) else mime


__all__ = ["valida_documento", "UploadMimeValidationError", "MIME_PER_ESTENSIONE"]
