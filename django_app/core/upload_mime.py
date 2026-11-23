from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath


class UploadMimeValidationError(ValueError):
    """Errore di validazione MIME/estensione/nome file durante upload."""


# ---------------------------------------------------------------------------
# Filename normalization (path traversal / null byte hardening)
# ---------------------------------------------------------------------------

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def safe_filename(raw_name: str | None, *, max_length: int = 200) -> str:
    """Normalizza un nome file uploadato eliminando path traversal e separatori.

    Garanzie:
    - rimuove componenti directory (POSIX e Windows) restituendo solo il basename
    - rimuove null byte e caratteri di controllo
    - rifiuta nomi vuoti, ``"."``, ``".."`` o composti solo da punti/spazi
    - tronca alla lunghezza massima preservando l'estensione

    Ritorna stringa vuota se il nome non e' recuperabile.
    """
    name = str(raw_name or "")
    if not name:
        return ""
    # Rimuovi null byte e caratteri di controllo (NON i separatori: servono a .name)
    name = _CONTROL_CHARS_RE.sub("", name).strip()
    if not name:
        return ""
    # Strip path components sia POSIX sia Windows: .name su entrambi
    posix_name = PurePosixPath(name).name
    win_name = PureWindowsPath(name).name
    # Tieni il piu' corto non vuoto: se uno dei due ha "stripato" un path, e' quello.
    candidate = posix_name if (posix_name and len(posix_name) <= len(win_name)) else win_name
    candidate = candidate or posix_name or win_name
    # Rimuovi eventuali separatori residui (edge case con nomi misti)
    candidate = candidate.replace("\\", "").replace("/", "").strip().strip(".")
    if not candidate or candidate in {".", ".."}:
        return ""
    if len(candidate) > max_length:
        suffix = Path(candidate).suffix[: max(0, max_length // 4)]
        stem_max = max(1, max_length - len(suffix))
        stem = Path(candidate).stem[:stem_max]
        candidate = f"{stem}{suffix}"
    return candidate


def validate_filename(raw_name: str | None, *, label: str | None = None) -> str:
    """Valida e ritorna il nome file normalizzato; alza errore se non valido."""
    cleaned = safe_filename(raw_name)
    if not cleaned:
        display = label or "File"
        raise UploadMimeValidationError(f"{display}: nome file non valido.")
    return cleaned


# ---------------------------------------------------------------------------
# Magic bytes (signature) check senza dipendenze esterne
# ---------------------------------------------------------------------------

# Mappa estensione -> lista di firme accettabili (offset, bytes literal).
# Coprire le estensioni piu' comuni accettate dalle superfici di upload del portale.
_MAGIC_SIGNATURES: dict[str, list[tuple[int, bytes]]] = {
    ".pdf": [(0, b"%PDF-")],
    ".png": [(0, b"\x89PNG\r\n\x1a\n")],
    ".jpg": [(0, b"\xff\xd8\xff")],
    ".jpeg": [(0, b"\xff\xd8\xff")],
    ".gif": [(0, b"GIF87a"), (0, b"GIF89a")],
    ".webp": [(0, b"RIFF")],  # poi controlleremo "WEBP" a offset 8
    ".bmp": [(0, b"BM")],
    # Office moderno (zip-based) e pacchetti zip
    ".zip": [(0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")],
    ".xlsx": [(0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")],
    ".docx": [(0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")],
    ".pptx": [(0, b"PK\x03\x04"), (0, b"PK\x05\x06"), (0, b"PK\x07\x08")],
    # Office legacy (OLE Compound Document)
    ".xls": [(0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")],
    ".doc": [(0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")],
}


def check_magic_signature(uploaded_file, ext: str, *, read_size: int = 16) -> bool:
    """Verifica firma binaria del file rispetto all'estensione.

    Ritorna True se l'estensione non e' coperta dalla mappa (skip non-bloccante)
    o se almeno una firma matcha. Ritorna False se la mappa copre l'estensione
    ma nessuna firma matcha.
    """
    ext_norm = (ext or "").lower()
    signatures = _MAGIC_SIGNATURES.get(ext_norm)
    if not signatures:
        return True  # Nessuna firma nota: non bloccante.
    try:
        head = uploaded_file.read(read_size)
    except Exception:
        return False
    finally:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
    if not head:
        return False
    for offset, sig in signatures:
        if head[offset : offset + len(sig)] == sig:
            # Caso speciale WEBP: header "RIFF" + "WEBP" a offset 8
            if ext_norm == ".webp":
                if head[8:12] == b"WEBP":
                    return True
                continue
            return True
    return False


# ---------------------------------------------------------------------------
# MIME sniffing (libmagic) - retro-compatibile
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Validazione composita
# ---------------------------------------------------------------------------

def validate_extension_and_mime(
    uploaded_file,
    *,
    allowed_extensions: set[str],
    allowed_mimes: set[str],
    max_bytes: int | None = None,
    label: str | None = None,
    allow_empty: bool = True,
) -> str:
    """Valida nome file (no path traversal), estensione, dimensione e MIME reale.

    Ritorna il MIME reale normalizzato in minuscolo.

    Note di compatibilita':
    - i chiamanti esistenti continuano a funzionare: ``allow_empty=True`` di
      default mantiene il comportamento storico (size 0 era accettata in
      assenza di check). I nuovi chiamanti possono passare ``allow_empty=False``
      per bloccare upload vuoti.
    """
    raw_name = getattr(uploaded_file, "name", "") or ""
    display_name = label or safe_filename(raw_name) or "File"

    # Step 1: filename hardening.
    filename = validate_filename(raw_name, label=display_name)

    # Step 2: estensione.
    ext = Path(filename).suffix.lower()
    normalized_allowed = {str(e).lower() for e in allowed_extensions}
    if ext not in normalized_allowed:
        raise UploadMimeValidationError(
            f"{display_name}: formato non consentito ({ext or 'nessuna estensione'})."
        )

    # Step 3: dimensione.
    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0 and not allow_empty:
        raise UploadMimeValidationError(f"{display_name}: file vuoto.")
    if max_bytes is not None and size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        raise UploadMimeValidationError(
            f"{display_name}: supera il limite di {max_mb:.0f} MB."
        )

    # Step 4: MIME via libmagic (fail-closed).
    mime = sniff_upload_mime(uploaded_file)
    if mime not in {str(m).lower() for m in allowed_mimes}:
        raise UploadMimeValidationError(
            f"{display_name}: tipo MIME non consentito ({mime})."
        )
    return mime


# ---------------------------------------------------------------------------
# Validazione per estensione (tabella unica del portale, audit [56])
# ---------------------------------------------------------------------------
#
# libmagic per i formati Office restituisce etichette generiche (``application/zip``
# per un .xlsx, ``application/octet-stream`` per un .docx, ``application/CDFV2`` per
# .doc/.xls/.msg): sono accettate solo per l'estensione giusta **e** se la firma
# binaria coincide (un HTML rinominato .docx non ha la firma ZIP).

_OFFICE_ZIP = {"application/zip", "application/octet-stream"}
_OLE = {"application/cdfv2", "application/x-ole-storage"}
_FIRMA_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FIRMA_ZIP = b"PK\x03\x04"

MIME_PER_ESTENSIONE: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
    ".txt": {"text/plain"},
    ".log": {"text/plain"},
    ".csv": {"text/plain", "text/csv", "application/csv"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"} | _OFFICE_ZIP,
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"} | _OFFICE_ZIP,
    ".doc": {"application/msword"} | _OLE,
    ".xls": {"application/vnd.ms-excel"} | _OLE,
    ".msg": {"application/vnd.ms-outlook", "application/x-msg"} | _OLE,
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"} | _OFFICE_ZIP,
    ".odp": {"application/vnd.oasis.opendocument.presentation"} | _OFFICE_ZIP,
    ".odt": {"application/vnd.oasis.opendocument.text"} | _OFFICE_ZIP,
    ".ods": {"application/vnd.oasis.opendocument.spreadsheet"} | _OFFICE_ZIP,
    ".ppt": {"application/vnd.ms-powerpoint"} | _OLE,
}

# Tipo da registrare quando libmagic dà un'etichetta generica.
MIME_CANONICO = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".msg": "application/vnd.ms-outlook",
}


def firma_coerente(uploaded_file, ext: str) -> bool:
    """La firma binaria corrisponde all'estensione (anche per i contenitori fuori tabella)."""
    if ext in (".pptx", ".odp", ".odt", ".ods", ".msg", ".ppt"):
        attesa = _FIRMA_OLE if ext in (".msg", ".ppt") else _FIRMA_ZIP
        try:
            head = uploaded_file.read(len(attesa))
        finally:
            uploaded_file.seek(0)
        return head == attesa
    return check_magic_signature(uploaded_file, ext)


def valida_per_estensione(uploaded_file, estensioni: set[str], *, max_bytes: int, label: str = "File") -> str:
    """Nome, estensione, dimensione, MIME reale e firma; ritorna il MIME da registrare.

    Solleva ``UploadMimeValidationError`` con un messaggio leggibile se il file non va.
    """
    raw_name = getattr(uploaded_file, "name", "") or ""
    ext = Path(safe_filename(raw_name)).suffix.lower()
    ammessi = MIME_PER_ESTENSIONE.get(ext, set()) if ext in estensioni else set()
    mime = validate_extension_and_mime(
        uploaded_file, allowed_extensions=estensioni, allowed_mimes=ammessi or {"-"},
        max_bytes=max_bytes, label=label, allow_empty=False,
    )
    if not firma_coerente(uploaded_file, ext):
        raise UploadMimeValidationError(f"{label}: il contenuto non corrisponde all'estensione {ext}.")
    return MIME_CANONICO.get(ext, mime) if mime in (_OFFICE_ZIP | _OLE) else mime
