"""Testo leggibile dai file che arrivano al Security Center (allegati mail, upload inbox).

Prima ogni allegato veniva decodificato come UTF-8: per un PDF (i report WatchGuard
arrivano così) il parser riceveva lo stream binario compresso, non riconosceva nulla e
la sorgente restava muta. Il PDF va aperto e se ne estrae il testo.
"""
import logging

logger = logging.getLogger(__name__)


def extract_text(filename, data):
    """Ritorna ``(testo, avvisi)`` dal contenuto grezzo di un file.

    Mai un'eccezione: un PDF illeggibile diventa testo vuoto più un avviso, che il
    chiamante conserva nel ``raw_payload`` così da vederlo in pagina.
    """
    data = bytes(data or b"")
    name = str(filename or "").lower()
    if name.endswith(".pdf") or data[:5] == b"%PDF-":
        return _pdf_text(data)
    return _decode_text(data), []


ARCHIVE_MAX_MEMBERS = 100
ARCHIVE_MAX_MEMBER_BYTES = 25 * 1024 * 1024
ARCHIVE_MAX_TOTAL_BYTES = 100 * 1024 * 1024


def is_zip(filename, data):
    name = str(filename or "").lower()
    return name.endswith(".zip") or bytes(data or b"")[:4] == b"PK\x03\x04"


def expand_zip(filename, data):
    """Contenuto di uno ZIP: ``([(nome, bytes), ...], avvisi)``.

    I report programmati di WatchGuard arrivano in un unico ZIP con CSV e PDF dentro: senza
    aprirlo la mail sembrava senza dati. Mai un'eccezione. Difese da ZIP malevoli: numero di
    file, dimensione del singolo e totale dichiarate nell'archivio (anti zip-bomb), nessun
    percorso (si usa solo il nome del file), niente archivi annidati.
    """
    import io
    import zipfile

    members, warnings, total = [], [], 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(bytes(data or b"")))
        infos = [info for info in archive.infolist() if not info.is_dir()]
    except Exception as exc:  # noqa: BLE001 - archivio corrotto
        return [], [f"ZIP illeggibile ({filename}): {str(exc)[:150]}"]
    if len(infos) > ARCHIVE_MAX_MEMBERS:
        warnings.append(f"ZIP con {len(infos)} file: letti solo i primi {ARCHIVE_MAX_MEMBERS}")
        infos = infos[:ARCHIVE_MAX_MEMBERS]
    for info in infos:
        name = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not name or name.startswith("."):
            continue
        if name.lower().endswith((".zip", ".rar", ".7z")):
            warnings.append(f"Archivio annidato ignorato: {name}")
            continue
        if info.file_size > ARCHIVE_MAX_MEMBER_BYTES or total + info.file_size > ARCHIVE_MAX_TOTAL_BYTES:
            warnings.append(f"File troppo grande ignorato: {name} ({info.file_size} byte)")
            continue
        if info.flag_bits & 0x1:
            warnings.append(f"File protetto da password ignorato: {name}")
            continue
        try:
            content = archive.read(info)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"File illeggibile nello ZIP ({name}): {str(exc)[:100]}")
            continue
        total += len(content)
        members.append((name, content))
    return members, warnings


def _pdf_text(data):
    try:
        import fitz  # pymupdf
    except Exception:  # noqa: BLE001 - dipendenza opzionale
        return "", ["Estrazione PDF non disponibile: libreria pymupdf non installata."]
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception as exc:  # noqa: BLE001 - PDF corrotto o cifrato
        logger.warning("Security Center: PDF illeggibile (%s)", exc)
        return "", [f"PDF illeggibile: {str(exc)[:200]}"]
    if not text.strip():
        return "", ["Il PDF non contiene testo estraibile (probabilmente è una scansione)."]
    return text, []


def _decode_text(data):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
