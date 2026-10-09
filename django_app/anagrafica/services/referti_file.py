"""Validazione lato server dei file di referto (audit A8).

Un referto è un dato sanitario: si accettano solo PDF, PNG e JPEG, verificati
dal contenuto (non dal Content-Type dichiarato dal browser). Il tipo salvato su
``DocumentoDipendente.tipo_mime`` è quello rilevato.
"""
from __future__ import annotations

from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

ESTENSIONI = {".pdf", ".png", ".jpg", ".jpeg"}
MIME = {"application/pdf", "image/png", "image/jpeg"}
MAX_BYTES = 100 * 1024 * 1024


def valida_referto(uploaded_file, *, label: str = "Referto") -> str:
    """Ritorna il MIME reale; solleva ``UploadMimeValidationError`` se non ammesso."""
    return validate_extension_and_mime(
        uploaded_file, allowed_extensions=ESTENSIONI, allowed_mimes=MIME,
        max_bytes=MAX_BYTES, label=label, allow_empty=False,
    )


__all__ = ["valida_referto", "UploadMimeValidationError", "ESTENSIONI", "MIME"]
