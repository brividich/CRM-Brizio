"""Acquisizione dei fogli di verifica da una cartella di rete («cartella di pescaggio»).

Lo scanner salva i fogli in una cartella condivisa; un lavoro periodico li prende,
legge il QR di ogni pagina, ritrova la verifica stampata dal portale, allega la
scansione e propone i punti segnati. La verifica passa a «da confermare»: la
conferma resta a una persona. Stesso schema dei fogli firme della formazione
(``anagrafica/services/intake_scansioni.py``).

Regole di prudenza:
- un file che sta ancora arrivando non si tocca (dimensione e data di modifica
  stabili, con una sola attesa per tutto il lotto);
- un foglio gia' elaborato non si rilegge: ogni pagina lascia la sua impronta
  (SHA-256 del file + numero di pagina, confermata dalla riga del registro), cosi'
  un passaggio interrotto a meta' riprende dalle pagine mancanti e il file si
  sposta solo quando tutte le pagine hanno la loro riga;
- due passaggi sulla stessa cartella non si sovrappongono (lock condiviso fra
  lavoro periodico e pulsante «Leggi ora»), e un giro si ferma dopo
  ``BUDGET_SECONDI``: il resto lo prende il giro dopo;
- un PDF con piu' fogli si legge pagina per pagina: ogni pagina ha il suo QR;
- una pagina senza QR riconosciuto non si perde: finisce «da smistare» con la sua
  copia, e dalla pagina di acquisizione si associa a mano a una verifica;
- un guasto su un file non ferma gli altri; niente eccezioni verso il lavoro periodico.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from ..models import PeriodicCheckIntakeConfig, PeriodicCheckIntakeLog, PeriodicCheckSession
from . import periodic_checks as checks

logger = logging.getLogger(__name__)

ACCEPTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
STABLE_WAIT_SECONDS = 2.0
# Un giro deve stare sotto il timeout del worker (120 s).
BUDGET_SECONDI = 90.0
LOCK_TTL_SECONDI = 300
_CHIAVE_PAGINA = "assets:periodic_intake:pagina:{}:{}"
_TTL_PAGINA = 90 * 24 * 3600
MESSAGGIO_IN_CORSO = "Un passaggio sulla cartella e' gia' in corso: l'esito compare tra poco."


@contextmanager
def lock_cartella(cartella: str):
    """``True`` se il lock e' preso, ``False`` se un passaggio e' gia' in corso."""
    from django.core.cache import cache

    impronta = hashlib.sha1((cartella or "").strip().lower().encode("utf-8")).hexdigest()[:16]
    chiave = f"intake:lock:verifiche_periodiche:{impronta}"
    try:
        preso = bool(cache.add(chiave, 1, LOCK_TTL_SECONDI))
    except Exception:
        logger.warning("Lock della cartella non disponibile: procedo senza", exc_info=True)
        preso, chiave = True, ""
    try:
        yield preso
    finally:
        if preso and chiave:
            try:
                cache.delete(chiave)
            except Exception:
                logger.warning("Rilascio del lock fallito", exc_info=True)


def _pagina_registrata(sha: str, page: int, page_name: str):
    """La riga del registro di una pagina gia' elaborata, o ``None``.

    La cache ricorda quale riga; il registro conferma che esiste ancora.
    """
    from django.core.cache import cache

    try:
        log_id = cache.get(_CHIAVE_PAGINA.format(sha, page))
    except Exception:
        log_id = None
    if not log_id:
        return None
    return PeriodicCheckIntakeLog.objects.filter(pk=log_id, file_name=page_name[:255], page=page).first()


def _segna_pagina(sha: str, page: int, log: PeriodicCheckIntakeLog) -> None:
    from django.core.cache import cache

    try:
        cache.set(_CHIAVE_PAGINA.format(sha, page), log.pk, _TTL_PAGINA)
    except Exception:
        logger.warning("Impronta della pagina non salvata in cache", exc_info=True)


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


def _process_file_ripresa(data: bytes, name: str, deadline: float) -> tuple[list, list, bool]:
    """Come :func:`process_file`, ma salta le pagine gia' elaborate e rispetta il budget.

    Ritorna ``(righe nuove, righe di tutte le pagine, completo)``: ``completo`` e'
    falso se il budget si e' esaurito prima dell'ultima pagina.
    """
    sha = hashlib.sha256(data).hexdigest()
    pages = split_pages(data, name)
    nuove, tutte = [], []
    for number, page_bytes in pages:
        page_name = _page_name(name, number, len(pages))
        gia = _pagina_registrata(sha, number, page_name)
        if gia is not None:
            tutte.append(gia)
            continue
        if time.monotonic() > deadline:
            return nuove, tutte, False
        log = process_page(page_bytes, page_name, page=number, source="CARTELLA")
        _segna_pagina(sha, number, log)
        nuove.append(log)
        tutte.append(log)
    return nuove, tutte, True


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


def _firma(path: Path):
    try:
        st = path.stat()
        return (st.st_size, st.st_mtime)
    except OSError:
        return None


def _stable_batch(paths: list[Path]) -> list[Path]:
    """I file che hanno finito di arrivare: una sola attesa per tutto il lotto."""
    if not paths:
        return []
    before = {p: _firma(p) for p in paths}
    if STABLE_WAIT_SECONDS:
        time.sleep(STABLE_WAIT_SECONDS)
    return [p for p in paths if before[p] is not None and _firma(p) == before[p]]


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
    """Un passaggio sulla cartella. Non solleva mai. ``force`` ignora «attiva» (pulsante «Leggi ora»).

    Se un altro passaggio sulla stessa cartella e' in corso ritorna subito con
    ``in_corso=True`` senza toccare l'ultimo esito annotato.
    """
    config = config or PeriodicCheckIntakeConfig.load()
    summary = {"esaminati": 0, "pagine": 0, "letti": 0, "da_smistare": 0, "errori": 0, "rimandati": 0}

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
    with lock_cartella(folder) as preso:
        if not preso:
            return {**summary, "riepilogo": MESSAGGIO_IN_CORSO, "in_corso": True}
        return _process_root(config, folder, summary, done, limit)


def _process_root(config, folder: str, summary: dict, done, limit: int | None) -> dict:
    deadline = time.monotonic() + BUDGET_SECONDI
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

    pronti = _stable_batch(candidates[: (limit if limit is not None else config.max_file_per_giro or 25)])
    for index, path in enumerate(pronti):
        if time.monotonic() > deadline:
            summary["rimandati"] += len(pronti) - index
            break
        summary["esaminati"] += 1
        try:
            logs, tutte, completo = _process_file_ripresa(path.read_bytes(), path.name, deadline)
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
        if not completo:
            # Budget finito a meta' file: resta nella cartella, il giro dopo
            # riprende dalle pagine mancanti.
            summary["rimandati"] += len(pronti) - index
            break
        if config.sposta_elaborati:
            ok = all(log.outcome == PeriodicCheckIntakeLog.OUTCOME_READ for log in tutte)
            _move(path, root, "elaborati" if ok else "errori")

    coda = [f"{summary['rimandati']} rimandati al prossimo giro"] if summary["rimandati"] else []
    if not summary["esaminati"]:
        return done(" · ".join(["Nessun file nuovo.", *coda]))
    parts = [f"{summary['esaminati']} file ({summary['pagine']} fogli)", f"{summary['letti']} letti"]
    if summary["da_smistare"]:
        parts.append(f"{summary['da_smistare']} da smistare")
    if summary["errori"]:
        parts.append(f"{summary['errori']} in errore")
    return done(" · ".join(parts + coda))
