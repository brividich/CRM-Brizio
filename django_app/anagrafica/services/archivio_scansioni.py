"""Archiviazione e registro delle scansioni dei fogli firme.

Il motivo di esistere di questo modulo è il caso in cui la lettura **fallisce**.

Prima, un file che il portale non riusciva a interpretare produceva un messaggio
d'errore e spariva. Chi aveva scansionato non aveva niente da mostrare a
nessuno, e chi doveva capire il perché non aveva niente da guardare: restava
solo la frase «non sono riuscito a leggere la scansione», che non è una
diagnosi.

Da qui la regola: **il file si archivia sempre**, prima ancora di provare a
leggerlo, e il percorso finisce nel registro. Su una lettura riuscita serve a
confrontare la proposta con l'originale; su una fallita è l'unica cosa che
permetta di capire se il foglio era storto, tagliato, sbiadito o semplicemente
di un'altra giornata.

L'archivio è quello privato dell'anagrafica — lo stesso di referti e consegne —
perché un foglio firme è un elenco di nomi con le relative firme autografe. Non
sta in webroot e non si apre da Esplora risorse: si scarica da una view che
applica permessi e lascia traccia.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

__all__ = ["archivia_scansione", "registra_lettura", "apri_archiviata"]

# Estensioni che ci aspettiamo da uno scanner o da un telefono.
ESTENSIONI_NOTE = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def _storage():
    from ..storage import PrivateAnagraficaStorage

    return PrivateAnagraficaStorage()


def _nome_sicuro(nome_file: str) -> str:
    """Nome di file ridotto a qualcosa che non possa fare danni.

    Uno scanner di rete produce nomi con spazi, accenti e talvolta percorsi
    interi; qui interessa solo conservare un'eco leggibile dell'originale.
    """
    nome_file = (nome_file or "").replace("\\", "/").split("/")[-1]
    radice, punto, estensione = nome_file.rpartition(".")
    if not punto:
        radice, estensione = nome_file, ""
    estensione = "." + estensione.lower() if estensione else ""
    if estensione not in ESTENSIONI_NOTE:
        estensione = estensione[:8]

    radice = re.sub(r"[^A-Za-z0-9._-]+", "-", radice).strip("-")[:60]
    return (radice or "scansione") + estensione


def archivia_scansione(contenuto: bytes, nome_file: str = "") -> tuple[str, int]:
    """Salva il file così com'è arrivato. Ritorna ``(percorso, byte)``.

    Il percorso è relativo allo storage privato ed è quello che finisce nel
    registro. Un fallimento qui **non** deve impedire la lettura: se l'archivio
    non è scrivibile è un guaio da segnalare, ma non è un buon motivo per
    buttare via anche la scansione che l'utente stava caricando.
    """
    adesso = datetime.now()
    percorso = "formazione/scansioni/{:%Y/%m}/{:%Y%m%d-%H%M%S}-{}".format(
        adesso, adesso, _nome_sicuro(nome_file)
    )
    try:
        salvato = _storage().save(percorso, ContentFile(contenuto))
    except Exception:
        logger.exception("Archiviazione scansione fallita (%s)", nome_file)
        return "", len(contenuto or b"")
    return salvato, len(contenuto or b"")


def apri_archiviata(percorso: str):
    """File archiviato riaperto per il download, o ``None`` se non c'è più."""
    if not percorso:
        return None
    storage = _storage()
    try:
        if not storage.exists(percorso):
            return None
        return storage.open(percorso, "rb")
    except Exception:
        logger.exception("Riapertura scansione archiviata fallita (%s)", percorso)
        return None


def registra_lettura(
    *,
    request=None,
    lezione=None,
    foglio=None,
    nome_file: str = "",
    percorso: str = "",
    dimensione: int = 0,
    token_digitato: str = "",
    token_letto: str = "",
    esito: str = "OK",
    origine: str = "WEB",
    messaggio: str = "",
    presenze_scritte: int = 0,
    esito_lettura: dict | None = None,
):
    """Scrive una riga nel registro. Non solleva mai.

    Il registro è diagnostica: se scrivere la riga fallisse, far fallire anche
    il caricamento sarebbe assurdo — si perderebbe il lavoro dell'utente per
    salvare un appunto.
    """
    from ..models_formazione import TrainingScanLog

    dati = {
        "lezione": lezione,
        "foglio": foglio,
        "nome_file": (nome_file or "")[:255],
        "percorso": (percorso or "")[:500],
        "dimensione": max(0, int(dimensione or 0)),
        "token_digitato": (token_digitato or "")[:16],
        "token_letto": (token_letto or "")[:16],
        "esito": esito,
        "origine": origine,
        "messaggio": messaggio or "",
        "presenze_scritte": max(0, int(presenze_scritte or 0)),
    }
    if esito_lettura:
        dati["n_righe"] = len(esito_lettura.get("righe") or [])
        dati["n_firmati"] = esito_lettura.get("n_firmati") or 0
        dati["n_dubbie"] = esito_lettura.get("n_dubbie") or 0
        inclinazione = esito_lettura.get("inclinazione")
        if inclinazione is not None:
            dati["inclinazione"] = inclinazione

    utente = getattr(request, "user", None)
    if utente is not None and getattr(utente, "is_authenticated", False):
        dati["creato_da"] = utente

    try:
        return TrainingScanLog.objects.create(**dati)
    except Exception:
        logger.exception("Registrazione lettura scansione fallita (%s)", nome_file)
        return None
