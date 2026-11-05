"""Percorsi di rete di programmi e FAI: cosa si accetta e come diventa un link."""
from __future__ import annotations

import re
from urllib.parse import quote, unquote

_UNC = re.compile(r"^\\\\[A-Za-z0-9._-]+(\\[^\\]+)+\\?$")
_LETTERA = re.compile(r"^[A-Za-z]:[\\/]")
_VIETATI = re.compile(r'[\x00-\x1f<>"|]')

MESSAGGIO = "Indica un percorso di rete come \\\\server\\cartella oppure un indirizzo http(s)."


def normalizza_percorso(valore: str | None) -> str:
    """Restituisce il percorso pulito, oppure solleva ``ValueError`` con il motivo.

    Finisce in un link: passano solo percorsi di rete e indirizzi web, mai
    ``javascript:`` o ``data:``.
    """
    testo = (valore or "").strip().strip('"').strip()
    if not testo:
        return ""
    minuscolo = testo.lower()
    if minuscolo.startswith(("http://", "https://")):
        if _VIETATI.search(testo) or " " in testo:
            raise ValueError("L'indirizzo web contiene caratteri non validi.")
        return testo
    if _LETTERA.match(testo):
        raise ValueError(
            "Le lettere di unità cambiano da PC a PC: usa il percorso di rete, come \\\\server\\cartella."
        )
    if minuscolo.startswith("file:"):
        testo = "\\\\" + unquote(testo[5:]).lstrip("/\\").replace("/", "\\")
    elif testo.startswith("//"):
        testo = testo.replace("/", "\\")
    if not _UNC.match(testo) or _VIETATI.search(testo) or ".." in testo.split("\\"):
        raise ValueError(MESSAGGIO)
    return testo


def href_percorso(percorso: str | None) -> str:
    """Link da mettere in pagina: ``file://server/cartella`` per i percorsi di rete."""
    testo = (percorso or "").strip()
    if not testo:
        return ""
    if testo.lower().startswith(("http://", "https://")):
        return testo
    return "file://" + quote(testo.lstrip("\\").replace("\\", "/"), safe="/._-~")
