"""Acquisizione dei fogli di verifica da una cartella di rete («cartella di pescaggio»).

Lo scanner salva i fogli in una cartella condivisa; un lavoro periodico li prende,
legge il QR di ogni pagina, ritrova la verifica stampata dal portale, allega la
scansione e propone i punti segnati. La verifica passa a «da confermare»: la
conferma resta a una persona. Stesso schema dei fogli firme della formazione
(``anagrafica/services/intake_scansioni.py``).

Regole di prudenza:
- un file che sta ancora arrivando non si tocca (dimensione stabile);
- un PDF con piu' fogli si legge pagina per pagina: ogni pagina ha il suo QR;
- una pagina senza QR riconosciuto non si perde: finisce «da smistare» con la sua
  copia, e dalla pagina di acquisizione si associa a mano a una verifica;
- un guasto su un file non ferma gli altri; niente eccezioni verso il lavoro periodico.
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from ..models import PeriodicCheckIntakeConfig, PeriodicCheckIntakeLog, PeriodicCheckSession
from . import periodic_checks as checks

logger = logging.getLogger(__name__)

ACCEPTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
STABLE_WAIT_SECONDS = 2.0


def split_pages(data: bytes, name: str) -> list[tuple[int, bytes]]:
    """Pagine di un PDF come PDF da una pagina; un'immagine resta com'e'."""
    if not (data[:4] == b"%PDF" or name.lower().endswith(".pdf")):
        return [(1, data)]
    import fitz

    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.page_count <= 1:
            return [(1, data)]
        pages = []
        for index in range(doc.page_count):
            single = fitz.open()
            single.insert_pdf(doc, from_page=index, to_page=index)
            pages.append((index + 1, single.tobytes(deflate=True)))
            single.close()
        return pages


def _page_name(name: str, page: int, total: int) -> str:
    if total <= 1:
        return name
    stem, suffix = os.path.splitext(name)
    return f"{stem}-p{page}{suffix or '.pdf'}"


def _log(**kwargs) -> PeriodicCheckIntakeLog:
    scan = kwargs.pop("scan_bytes", None)
    log = PeriodicCheckIntakeLog(**kwargs)
    if scan is not None:
        log.scan.save(kwargs.get("file_name") or "scansione.pdf", ContentFile(scan), save=False)
    log.save()
    return log


def process_page(data: bytes, name: str, *, page: int = 1, source: str = "CARTELLA", user=None) -> PeriodicCheckIntakeLog:
    """Una pagina: QR -> verifica -> lettura. Ritorna la riga del registro."""
    from core.qr import leggi_codici

    base = {"file_name": name[:255], "page": page, "source": source}
    session = None
    token = ""
    for code in leggi_codici(data, name):
        found = checks.session_for_token(code)
        if found is not None:
            session, token = found, found.sheet_token
            break
    if session is None:
        return _log(**base, outcome=PeriodicCheckIntakeLog.OUTCOME_UNMATCHED, scan_bytes=data,
                    message="Nessun QR di un foglio di verifica riconosciuto: da associare a mano.")
    base.update({"token": token, "session": session})
    if session.status == PeriodicCheckSession.STATUS_CONFIRMED:
        return _log(**base, outcome=PeriodicCheckIntakeLog.OUTCOME_UNMATCHED, scan_bytes=data,
                    message="La verifica di questo foglio e' gia' confermata: la scansione non e' stata riletta.")
    try:
        reading = checks.read_scan_into(session, data, name=name, user=user)
    except checks.LayoutError as exc:
        return _log(**base, outcome=PeriodicCheckIntakeLog.OUTCOME_ERROR, scan_bytes=data, message=str(exc)[:500])
    proposti = len(reading.get("proposti", {}))
    message = (f"{proposti} punti segnati proposti da confermare." if reading.get("ok")
               else "Scansione allegata ma non allineata alla planimetria: punti da inserire a mano.")
    return _log(**base, outcome=PeriodicCheckIntakeLog.OUTCOME_READ, message=message)


def process_file(data: bytes, name: str, *, source: str = "CARTELLA", user=None) -> list[PeriodicCheckIntakeLog]:
    pages = split_pages(data, name)
    return [
        process_page(page_bytes, _page_name(name, number, len(pages)), page=number, source=source, user=user)
        for number, page_bytes in pages
    ]


def assign(log: PeriodicCheckIntakeLog, session: PeriodicCheckSession, *, user=None) -> dict:
    """Associa a mano una scansione da smistare a una verifica e la legge."""
    if not log.scan:
        raise checks.LayoutError("La copia della scansione non e' piu' disponibile.")
    with log.scan.open("rb") as handle:
        data = handle.read()
    reading = checks.read_scan_into(session, data, name=log.file_name, user=user)
    log.session = session
    log.outcome = PeriodicCheckIntakeLog.OUTCOME_ASSIGNED
    log.message = f"Associata a mano: {len(reading.get('proposti', {}))} punti proposti."[:500]
    log.handled_by = user if getattr(user, "is_authenticated", False) else None
    log.handled_at = timezone.now()
    log.save(update_fields=["session", "outcome", "message", "handled_by", "handled_at"])
    return reading


def discard(log: PeriodicCheckIntakeLog, *, user=None) -> None:
    log.outcome = PeriodicCheckIntakeLog.OUTCOME_DISCARDED
    log.handled_by = user if getattr(user, "is_authenticated", False) else None
    log.handled_at = timezone.now()
    log.save(update_fields=["outcome", "handled_by", "handled_at"])


def _stable(path: Path) -> bool:
    try:
        before = path.stat().st_size
        time.sleep(STABLE_WAIT_SECONDS)
        return path.stat().st_size == before
    except OSError:
        return False


def _move(path: Path, root: Path, folder: str) -> None:
    try:
        target_dir = root / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        if target.exists():
            stem, suffix = os.path.splitext(path.name)
            target = target_dir / f"{stem}-{int(time.time())}{suffix}"
        shutil.move(str(path), str(target))
    except Exception:
        logger.exception("Spostamento della scansione fallita (%s)", path)


def process_folder(config: PeriodicCheckIntakeConfig | None = None, *, limit: int | None = None,
                   force: bool = False) -> dict:
    """Un passaggio sulla cartella. Non solleva mai. ``force`` ignora «attiva» (pulsante «Leggi ora»)."""
    config = config or PeriodicCheckIntakeConfig.load()
    summary = {"esaminati": 0, "pagine": 0, "letti": 0, "da_smistare": 0, "errori": 0}

    def done(text: str) -> dict:
        try:
            config.ultima_esecuzione = timezone.now()
            config.ultimo_esito = text
            config.save(update_fields=["ultima_esecuzione", "ultimo_esito"])
        except Exception:
            logger.exception("Annotazione dell'ultimo passaggio fallita")
        return {**summary, "riepilogo": text}

    if not config.attiva and not force:
        return {**summary, "riepilogo": "Acquisizione da cartella spenta."}
    folder = (config.cartella or "").strip()
    if not folder:
        return done("Nessuna cartella configurata.")
    root = Path(folder)
    try:
        if not root.is_dir():
            return done(f"Cartella non raggiungibile: {folder}")
        candidates = sorted(
            (p for p in root.iterdir() if p.is_file() and p.suffix.lower() in ACCEPTED_SUFFIXES),
            key=lambda p: p.name,
        )
    except OSError:
        logger.exception("Acquisizione verifiche: cartella non leggibile")
        return done(f"Cartella non leggibile: {folder}")

    for path in candidates[: (limit if limit is not None else config.max_file_per_giro or 25)]:
        if not _stable(path):
            continue
        summary["esaminati"] += 1
        try:
            logs = process_file(path.read_bytes(), path.name)
        except Exception:
            logger.exception("Acquisizione verifiche: file non elaborato (%s)", path)
            summary["errori"] += 1
            if config.sposta_elaborati:
                _move(path, root, "errori")
            continue
        summary["pagine"] += len(logs)
        summary["letti"] += sum(1 for log in logs if log.outcome == PeriodicCheckIntakeLog.OUTCOME_READ)
        summary["da_smistare"] += sum(1 for log in logs if log.outcome == PeriodicCheckIntakeLog.OUTCOME_UNMATCHED)
        summary["errori"] += sum(1 for log in logs if log.outcome == PeriodicCheckIntakeLog.OUTCOME_ERROR)
        if config.sposta_elaborati:
            ok = all(log.outcome == PeriodicCheckIntakeLog.OUTCOME_READ for log in logs)
            _move(path, root, "elaborati" if ok else "errori")

    if not summary["esaminati"]:
        return done("Nessun file nuovo.")
    parts = [f"{summary['esaminati']} file ({summary['pagine']} fogli)", f"{summary['letti']} letti"]
    if summary["da_smistare"]:
        parts.append(f"{summary['da_smistare']} da smistare")
    if summary["errori"]:
        parts.append(f"{summary['errori']} in errore")
    return done(" · ".join(parts))
