"""Copia verificata degli artefatti verso il target (e il target secondario).

SHA-256 calcolato in streaming sulla sorgente, scrittura su file temporaneo nella
cartella di destinazione, rinomina, rilettura e confronto. Tre tentativi con
backoff. Lo staging non si cancella finché la copia non è verificata (lo decide
il chiamante con ``remove_source``).
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

CHUNK = 4 * 1024 * 1024


class TransferError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_once(src: Path, dst: Path, expected: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.tmp")
    h = hashlib.sha256()
    with open(src, "rb") as fin, open(tmp, "wb") as fout:
        for chunk in iter(lambda: fin.read(CHUNK), b""):
            h.update(chunk)
            fout.write(chunk)
        fout.flush()
        os.fsync(fout.fileno())
    if h.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise TransferError(f"La sorgente {src.name} è cambiata durante la copia.")
    os.replace(tmp, dst)
    actual = sha256_file(dst)
    if actual != expected:
        raise TransferError(f"Hash diverso dopo la copia di {src.name}: atteso {expected[:16]}…, letto {actual[:16]}…")


def copy_verified(
    src: Path,
    dst: Path,
    *,
    expected_sha256: str | None = None,
    attempts: int = 3,
    backoff_s: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    copier: Callable[[Path, Path, str], None] = _copy_once,
) -> str:
    """Copia ``src`` in ``dst`` verificando l'hash. Restituisce lo SHA-256."""
    src, dst = Path(src), Path(dst)
    expected = expected_sha256 or sha256_file(src)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            copier(src, dst, expected)
            return expected
        except (OSError, TransferError) as exc:
            last = exc
            logger.warning("copia %s → %s tentativo %s/%s fallito: %s", src.name, dst, attempt, attempts, exc)
            if attempt < attempts:
                sleep(backoff_s * attempt)
    raise TransferError(f"Copia di {src.name} non riuscita dopo {attempts} tentativi: {last}")


def write_bytes_verified(data: bytes, dst: Path) -> str:
    """Scrittura atomica di un piccolo file (manifest, indici) con verifica."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    expected = hashlib.sha256(data).hexdigest()
    tmp = dst.with_name(f".{dst.name}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dst)
    if sha256_file(dst) != expected:
        raise TransferError(f"Verifica fallita per {dst.name}")
    return expected
