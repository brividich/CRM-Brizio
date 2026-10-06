"""Seriali (S/N) delle anomalie: singoli, liste e range.

Nella colonna legacy ``anomalie.seriale`` un blocco di pezzi è salvato come testo
composito leggibile, per esempio ``LCN00005-LCN00010, LCN00020 (7 pezzi)``. Qui
vivono le due direzioni della conversione, usate sia dall'inserimento a blocchi
sia dal controllo duplicati, così il formato resta uno solo.
"""
from __future__ import annotations

import re

# Oltre questa ampiezza un "range" è quasi certamente un errore di battitura:
# lo si tratta come due seriali distinti invece di generare migliaia di token.
MAX_RANGE = 1000

_RANGE_RE = re.compile(r"^(.*?)(\d+)\s*-\s*(.*?)(\d+)$")
_PEZZI_RE = re.compile(r"\s*\(\d+\s*pezz[io]\)\s*$", re.IGNORECASE)


def _range_bounds(item: str) -> tuple[str, int, int, int] | None:
    """``LCN00005-LCN00010`` (o ``LCN00005-10``) -> (prefisso, inizio, fine, cifre)."""
    m = _RANGE_RE.match(item.strip())
    if not m:
        return None
    prefix, a, prefix_b, b = m.group(1), m.group(2), m.group(3), m.group(4)
    if prefix_b and prefix_b.lower() != prefix.lower():
        return None
    na, nb = int(a), int(b)
    if na > nb or nb - na > MAX_RANGE:
        return None
    return prefix, na, nb, len(a)


def espandi_voce(item: str) -> list[str]:
    """Una voce (singolo o range) nei seriali che rappresenta."""
    item = str(item or "").strip()
    if not item:
        return []
    bounds = _range_bounds(item)
    if bounds is None:
        return [item]
    prefix, na, nb, pad = bounds
    return [f"{prefix}{str(i).zfill(pad)}" for i in range(na, nb + 1)]


def normalizza_voci(items) -> list[str]:
    """Pulisce l'elenco di voci digitate (singoli o range), senza doppioni."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        for part in str(raw or "").split(","):
            voce = re.sub(r"\s*-\s*", "-", part.strip())[:100]
            if voce and voce.lower() not in seen:
                seen.add(voce.lower())
                out.append(voce)
    return out


def conta_pezzi(items) -> int:
    seen: set[str] = set()
    for item in items or []:
        for token in espandi_voce(item):
            seen.add(token.lower())
    return len(seen)


def etichetta_blocco(items) -> str:
    """Testo composito per la colonna legacy ``seriale`` (max 200 caratteri)."""
    voci = normalizza_voci(items)
    if not voci:
        return ""
    n = conta_pezzi(voci)
    testo = ", ".join(voci)
    if n > 1:
        testo = f"{testo} ({n} pezzi)"
    return testo[:200]


def espandi_seriale_composito(value: str) -> list[str]:
    """Testo della colonna ``seriale`` -> singoli seriali (liste e range espansi)."""
    base = _PEZZI_RE.sub("", str(value or "")).strip()
    out: list[str] = []
    for part in base.split(","):
        out.extend(espandi_voce(part))
    return out
