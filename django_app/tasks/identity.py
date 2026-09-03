"""Normalizzazione dell'identita' anagrafica delle commesse KICK-OFF."""
from __future__ import annotations


def normalize_part_number(value: str | None) -> str:
    """Normalizza il P/N con maiuscole e spazi interni collassati."""
    return " ".join(str(value or "").strip().upper().split())


def normalize_client_name(value: str | None) -> str:
    """Normalizza gli spazi della ragione sociale preservandone il case."""
    return " ".join(str(value or "").strip().split())
