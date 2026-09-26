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
