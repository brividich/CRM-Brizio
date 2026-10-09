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


# ---------------------------------------------------------------------------
# Sniff del contenuto (non solo del nome): per i dati sanitari (referti).
# ---------------------------------------------------------------------------

REFERTO_INLINE_MIME_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})

_FIRME = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def sniff_head(head: bytes) -> str:
    """Tipo reale dai primi byte (solo PDF/PNG/JPEG); stringa vuota se altro."""
    for firma, mime in _FIRME:
        if head.startswith(firma):
            return mime
    return ""


def harden_sniffed_response(response, filename: str, head: bytes, *,
                            inline_types: frozenset = REFERTO_INLINE_MIME_TYPES):
    """Come :func:`harden_file_response`, ma decide dal **contenuto**.

    Inline solo se i primi byte sono di un tipo ammesso *e* coincidono con
    l'estensione del nome: un ``.pdf`` che contiene HTML, o un ``.svg``, esce
    come allegato opaco con ``Content-Security-Policy: sandbox``.
    """
    reale = sniff_head(head or b"")
    if reale and reale in inline_types and guess_mime_from_name(filename) == reale:
        response["Content-Type"] = reale
        disposition = response.get("Content-Disposition", "")
        _, _, params = disposition.partition(";")
        response["Content-Disposition"] = f"inline;{params}" if params else "inline"
        response["X-Content-Type-Options"] = "nosniff"
        if reale != "application/pdf":
            response["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self'"
        return response
    response["Content-Type"] = "application/octet-stream"
    disposition = response.get("Content-Disposition", "")
    _, _, params = disposition.partition(";")
    response["Content-Disposition"] = f"attachment;{params}" if params else "attachment"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


def read_head(fh, n: int = 16) -> bytes:
    """Legge i primi byte di un file aperto e torna all'inizio (fail-safe: b"")."""
    try:
        head = fh.read(n) or b""
        fh.seek(0)
        return head if isinstance(head, bytes) else b""
    except Exception:
        return b""
