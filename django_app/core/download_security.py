"""Hardening delle risposte che servono file caricati dagli utenti.

Un file caricato non deve mai essere interpretato dal browser come pagina del
portale: un ``.html``/``.svg`` servito inline con il Content-Type dichiarato dal
client esegue script nella sessione di chi lo apre (audit A8). Qui il tipo si
ricava lato server dall'estensione e solo PDF e immagini raster restano inline;
tutto il resto viene scaricato come allegato opaco.
"""
from __future__ import annotations

import mimetypes
from pathlib import PurePath

# Tipi che il browser mostra senza eseguire codice sull'origin del portale.
INLINE_SAFE_MIME_TYPES = frozenset({
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
})

_EXTRA_TYPES = {".webp": "image/webp", ".jfif": "image/jpeg"}


def guess_mime_from_name(filename: str) -> str:
    """Content-Type dedotto dall'estensione del nome file (mai dal client)."""
    ext = PurePath(str(filename or "")).suffix.lower()
    if ext in _EXTRA_TYPES:
        return _EXTRA_TYPES[ext]
    mime, _ = mimetypes.guess_type(f"x{ext}") if ext else (None, None)
    return (mime or "application/octet-stream").lower()


def harden_file_response(response, filename: str, *, inline: bool = True):
    """Imposta Content-Type, Content-Disposition e header di sandbox sicuri.

    ``inline=True`` è solo una preferenza: viene rispettata per i tipi in
    ``INLINE_SAFE_MIME_TYPES``, gli altri sono forzati come allegato.
    """
    mime = guess_mime_from_name(filename)
    safe_inline = inline and mime in INLINE_SAFE_MIME_TYPES
    if safe_inline:
        response["Content-Type"] = mime
    else:
        response["Content-Type"] = "application/octet-stream"
    disposition = response.get("Content-Disposition", "")
    if disposition:
        _, _, params = disposition.partition(";")
        kind = "inline" if safe_inline else "attachment"
        response["Content-Disposition"] = f"{kind};{params}" if params else kind
    elif not safe_inline:
        response["Content-Disposition"] = "attachment"
    response["X-Content-Type-Options"] = "nosniff"
    if not safe_inline:
        # Difesa in profondità se un browser ignorasse l'attachment. Non sui PDF
        # inline: il viewer PDF di Chromium non gira in un documento sandboxed.
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response
