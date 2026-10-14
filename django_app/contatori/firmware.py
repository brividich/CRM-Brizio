"""Versione firmware dei dispositivi SNMP: estrazione, storico e invio all'inventario del SOC.

Fonti, dalla piu' affidabile:

1. una sonda di testo il cui nome contiene «firmware» (preset Kyocera, iLO, ...);
2. il sysDescr, dove molti apparati scrivono la versione («... Version 15.2(4)E10»,
   «... Firmware 2.5.1»).

Lo storico tiene una riga per versione (prima e ultima volta vista): un cambio di
firmware resta tracciato anche quando il dispositivo lo riporta indietro.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_FW_NOME = re.compile(r"\b(firmware|fw)\b", re.IGNORECASE)
_VERSIONE = r"v?([0-9][0-9A-Za-z._\-()]*[0-9A-Za-z)])"
_PATTERN_DESCR = (
    re.compile(r"\b(?:firmware|fw)(?:\s+version)?\s*[:=]?\s*" + _VERSIONE, re.IGNORECASE),
    re.compile(r"\bversion\s*[:=]?\s*" + _VERSIONE, re.IGNORECASE),
    re.compile(r"\bver\.?\s*[:=]?\s*" + _VERSIONE, re.IGNORECASE),
)


def _pulisci(valore) -> str:
    return " ".join(str(valore or "").split())[:80]


def da_sys_description(sys_description: str) -> str:
    """Versione firmware scritta nel sysDescr, o stringa vuota."""
    testo = str(sys_description or "")
    for pattern in _PATTERN_DESCR:
        trovato = pattern.search(testo)
        if trovato:
            return _pulisci(trovato.group(1))
    return ""


def estrai(sys_description: str, esiti) -> tuple[str, str]:
    """``(versione, fonte)`` da sonde (``[{"sonda", "testo", ...}]``) e sysDescr."""
    for esito in esiti:
        sonda = esito.get("sonda")
        testo = _pulisci(esito.get("testo"))
        if sonda is not None and testo and _FW_NOME.search(sonda.nome or ""):
            return testo, f"sonda «{sonda.nome}»"
    versione = da_sys_description(sys_description)
    return (versione, "sysDescr") if versione else ("", "")


def registra(dispositivo, versione: str, fonte: str, quando) -> list[str]:
    """Aggiorna firmware corrente e storico; ritorna i campi del dispositivo da salvare."""
    from .models import FirmwareSNMP

    if not versione:
        return []
    riga = dispositivo.firmware_storico.filter(versione=versione).order_by("-ultimo_rilevamento").first()
    if riga is None:
        FirmwareSNMP.objects.create(dispositivo=dispositivo, versione=versione, fonte=fonte,
                                    primo_rilevamento=quando, ultimo_rilevamento=quando)
    else:
        FirmwareSNMP.objects.filter(pk=riga.pk).update(ultimo_rilevamento=quando)
    dispositivo.firmware = versione
    dispositivo.firmware_fonte = fonte
    dispositivo.firmware_rilevato_il = quando
    return ["firmware", "firmware_fonte", "firmware_rilevato_il"]


def invia_al_soc(dispositivo) -> None:
    """Pubblica il firmware nell'inventario software del SOC (per il confronto con le CVE)."""
    try:
        from security.services.firmware_inventory import sincronizza_dispositivo

        sincronizza_dispositivo(dispositivo)
    except Exception:  # noqa: BLE001 - il polling non deve fallire per l'inventario SOC
        logger.exception("Firmware del dispositivo %s non inviato all'inventario SOC", dispositivo.pk)
