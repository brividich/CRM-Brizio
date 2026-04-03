from __future__ import annotations

from pathlib import Path


class UploadMimeValidationError(ValueError):
    """Errore di validazione MIME/estensione durante upload file."""


def sniff_upload_mime(uploaded_file, *, read_size: int = 2048) -> str:
    """Rileva il MIME reale del file usando libmagic (fail-closed)."""
    try:
        import magic  # type: ignore
    except ImportError as exc:  # pragma: no cover - gestito nei test via patch
        raise UploadMimeValidationError(
            "Validazione MIME non disponibile sul server. Upload bloccato."
        ) from exc

    try:
        head = uploaded_file.read(read_size)
        raw_mime = magic.from_buffer(head, mime=True)
    except Exception as exc:  # pragma: no cover - dipende da runtime libmagic
        raise UploadMimeValidationError(
            "Impossibile verificare il tipo MIME del file. Upload bloccato."
        ) from exc
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass

    mime = str(raw_mime or "").split(";", 1)[0].strip().lower()
    if not mime:
        raise UploadMimeValidationError(
            "Tipo MIME non determinabile. Upload bloccato."
        )
    return mime


def validate_extension_and_mime(
    uploaded_file,
    *,
    allowed_extensions: set[str],
    allowed_mimes: set[str],
    max_bytes: int | None = None,
    label: str | None = None,
) -> str:
    """Valida estensione, dimensione (opzionale) e MIME reale.

    Ritorna il MIME reale normalizzato in minuscolo.
    """
    filename = Path(getattr(uploaded_file, "name", "") or "").name
    display_name = label or filename or "File"
    if not filename:
        raise UploadMimeValidationError(f"{display_name}: nome file non valido.")

    ext = Path(filename).suffix.lower()
    if ext not in allowed_extensions:
        raise UploadMimeValidationError(
            f"{display_name}: formato non consentito ({ext or 'nessuna estensione'})."
        )

    if max_bytes is not None:
        size = int(getattr(uploaded_file, "size", 0) or 0)
        if size > max_bytes:
            max_mb = max_bytes / (1024 * 1024)
            raise UploadMimeValidationError(
                f"{display_name}: supera il limite di {max_mb:.0f} MB."
            )

    mime = sniff_upload_mime(uploaded_file)
    if mime not in allowed_mimes:
        raise UploadMimeValidationError(
            f"{display_name}: tipo MIME non consentito ({mime})."
        )
    return mime
