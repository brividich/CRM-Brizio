"""Lettore di badge al Banco consegne: verifica della lettura e prova per la consegna.

Il browser manda il messaggio grezzo del lettore, il server ne controlla forma e byte di
controllo, trova la persona e rilascia una prova firmata: breve, personale e usabile una
sola volta. La consegna con badge accetta solo quella. I numeri di badge non arrivano
alla pagina e non si conservano.
"""
from __future__ import annotations

import re
import secrets

from django.core import signing
from django.core.cache import cache

SALE = "dpi.banco.badge"
DURATA_PROVA_SECONDI = 120
ERRORI_MASSIMI = 20
FINESTRA_ERRORI_SECONDI = 600
_MESSAGGIO = re.compile(rb"\x02(\d{1,20})\x03(.)\r", re.DOTALL)


def codice_badge(valore: str) -> str:
    """Il lettore manda gli zeri a sinistra, in Anagrafica il badge e' senza."""
    valore = (valore or "").strip()
    return (valore.lstrip("0") or "0") if valore.isdigit() else valore


def codice_da_messaggio(esadecimale: str) -> str:
    """Codice del messaggio del lettore ("" se non e' un messaggio valido)."""
    try:
        dati = bytes.fromhex((esadecimale or "")[:128])
    except ValueError:
        return ""
    trovato = _MESSAGGIO.fullmatch(dati)
    if not trovato:
        return ""
    controllo = 0
    for byte in dati[:-2]:
        controllo ^= byte
    if controllo != trovato.group(2)[0]:
        return ""
    return codice_badge(trovato.group(1).decode("ascii"))


def crea_prova(utente_id: int, legacy_id: int) -> str:
    return signing.dumps({"u": utente_id, "p": legacy_id, "n": secrets.token_hex(8)}, salt=SALE)


def usa_prova(prova: str, utente_id: int, legacy_id: int | None) -> bool:
    """Vera una sola volta: stessa persona, stesso operatore, entro la durata."""
    if not legacy_id:
        return False
    try:
        dati = signing.loads(prova, salt=SALE, max_age=DURATA_PROVA_SECONDI)
    except signing.BadSignature:
        return False
    if dati.get("u") != utente_id or dati.get("p") != legacy_id:
        return False
    return bool(cache.add(f"dpi_badge_prova_usata:{dati.get('n')}", 1, DURATA_PROVA_SECONDI * 2))


def troppi_errori(utente_id: int) -> bool:
    return (cache.get(f"dpi_badge_errori:{utente_id}") or 0) >= ERRORI_MASSIMI


def conta_errore(utente_id: int) -> None:
    chiave = f"dpi_badge_errori:{utente_id}"
    if not cache.add(chiave, 1, FINESTRA_ERRORI_SECONDI):
        try:
            cache.incr(chiave)
        except ValueError:
            cache.set(chiave, 1, FINESTRA_ERRORI_SECONDI)
