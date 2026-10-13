"""Indirizzi MAC in forma unica ``aa:bb:cc:dd:ee:ff``.

Usata dal MAC dichiarato del punto rete (``AssetEndpoint.mac``) e dal MAC letto
via SNMP (``ifPhysAddress``, che arriva come 6 byte grezzi): confrontabili solo
se normalizzati allo stesso modo.
"""
from __future__ import annotations

import re

_HEX = re.compile(r"[0-9a-f]")


def normalizza_mac(valore) -> str:
    """MAC normalizzato, oppure ``""`` se il valore non e' un MAC valido o e' tutto zero."""
    if valore is None:
        return ""
    if isinstance(valore, (bytes, bytearray)):
        if len(valore) != 6:
            # Alcuni agent rendono il MAC come testo ASCII invece che come byte.
            try:
                return normalizza_mac(bytes(valore).decode("ascii"))
            except UnicodeDecodeError:
                return ""
        cifre = bytes(valore).hex()
    else:
        testo = str(valore).strip().lower()
        if testo.startswith("0x"):
            testo = testo[2:]
        cifre = "".join(_HEX.findall(testo))
        # Solo separatori ammessi oltre alle cifre: niente testo arbitrario.
        if len(cifre) != 12 or re.sub(r"[0-9a-f:\-\. ]", "", testo):
            return ""
    if len(cifre) != 12 or set(cifre) == {"0"}:
        return ""
    return ":".join(cifre[i:i + 2] for i in range(0, 12, 2))
