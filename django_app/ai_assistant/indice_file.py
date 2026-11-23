"""Indice RAG costruito dalla coda task e letto già pronto dal portale.

Prima ogni processo web costruiva da sé l'indice (circa 10.000 brani da tokenizzare,
embeddings dalla cache DB) all'apertura della chat e poi ogni
``OLLAMA_RAG_CACHE_SECONDS``: lavoro Python puro che, col GIL, rallentava ogni altra
pagina di quel processo, moltiplicato per il numero di processi IIS.

Ora lo costruisce il cluster django-q (``tasks.run_ricostruisci_indice_rag``) e lo
salva qui; il processo web lo carica dal file e lo ricarica solo quando il file
cambia. Se i documenti sono cambiati il web continua a rispondere con l'indice del
file e chiede una ricostruzione alla coda (una sola ogni ``_RICHIESTA_SECONDI``).

Il file contiene un pickle: è firmato con HMAC (``SECRET_KEY``) e scritto nello storage
privato (non servito da IIS); un file non firmato o alterato viene ignorato.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import pickle
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

_FORMATO = b"HUBRAG1\n"
_RICHIESTA_CHIAVE = "ai_assistant:indice_rag:ricostruzione_richiesta"
_RICHIESTA_SECONDI = 600


def attivo() -> bool:
    return bool(getattr(settings, "OLLAMA_RAG_INDEX_FILE_ENABLED", True))


def percorso() -> Path:
    configurato = str(getattr(settings, "OLLAMA_RAG_INDEX_FILE", "") or "").strip()
    if configurato:
        return Path(configurato)
    return Path(settings.MEDIA_ROOT).parent / "media_private" / "rag" / "indice_rag.bin"


def impronta_firma(signature: Any) -> str:
    """Impronta stabile della firma dei documenti (tuple di percorsi/date/dimensioni)."""
    return hashlib.sha256(repr(signature).encode("utf-8", errors="replace")).hexdigest()


def _hmac(dati: bytes) -> bytes:
    return hmac.new(str(settings.SECRET_KEY).encode("utf-8"), dati, hashlib.sha256).digest()


def salva(index: Any, signature: Any) -> Path:
    """Scrive l'indice in modo atomico (file temporaneo + ``os.replace``)."""
    destinazione = percorso()
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    corpo = pickle.dumps(
        {"firma": impronta_firma(signature), "index": index}, protocol=pickle.HIGHEST_PROTOCOL
    )
    temporaneo = destinazione.with_name(f"{destinazione.name}.{os.getpid()}.tmp")
    with open(temporaneo, "wb") as fh:
        fh.write(_FORMATO)
        fh.write(_hmac(corpo))
        fh.write(corpo)
    os.replace(temporaneo, destinazione)
    # Impronta a parte: il cluster decide se ricostruire senza rileggere tutto l'indice.
    _file_firma().write_text(impronta_firma(signature), encoding="ascii")
    return destinazione


def _file_firma() -> Path:
    return percorso().with_suffix(".firma")


def firma_su_file() -> str:
    try:
        return _file_firma().read_text(encoding="ascii").strip()
    except OSError:
        return ""


def mtime() -> float | None:
    try:
        return percorso().stat().st_mtime
    except OSError:
        return None


def carica() -> tuple[str, Any] | None:
    """``(impronta firma, indice)`` dal file, o None se manca, è alterato o illeggibile."""
    try:
        dati = percorso().read_bytes()
    except OSError:
        return None
    testa = len(_FORMATO)
    if not dati.startswith(_FORMATO) or len(dati) < testa + 32:
        logger.warning("Indice RAG su file con formato sconosciuto: ignorato")
        return None
    firma_hmac, corpo = dati[testa:testa + 32], dati[testa + 32:]
    if not hmac.compare_digest(firma_hmac, _hmac(corpo)):
        logger.warning("Indice RAG su file con firma non valida: ignorato")
        return None
    try:
        contenuto = pickle.loads(corpo)  # noqa: S301 - file firmato HMAC, scritto dal cluster
    except Exception:
        logger.exception("Indice RAG su file non leggibile")
        return None
    return str(contenuto.get("firma") or ""), contenuto.get("index")


def richiedi_ricostruzione() -> bool:
    """Accoda una ricostruzione al cluster, al massimo una ogni ``_RICHIESTA_SECONDI``."""
    from django.core.cache import cache

    try:
        if not cache.add(_RICHIESTA_CHIAVE, "1", _RICHIESTA_SECONDI):
            return False
        from django_q.tasks import async_task

        async_task(
            "ai_assistant.tasks.run_ricostruisci_indice_rag",
            q_options={"timeout": 900},
        )
        return True
    except Exception:
        logger.warning("Ricostruzione dell'indice RAG non accodata", exc_info=True)
        return False
