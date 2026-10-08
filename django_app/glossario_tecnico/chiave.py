"""Normalizzazione delle varianti del glossario (chiave univoca di confronto)."""

from __future__ import annotations

import re
import unicodedata


def normalizza_chiave(testo: str) -> str:
    """Minuscolo, accenti tolti, spazi singoli. I simboli (⌴, ⌀, ⊥) restano: sono
    varianti a pieno titolo. «Lamatura», «LAMATURA » e «lamatùra» danno la stessa chiave."""
    testo = unicodedata.normalize("NFKD", str(testo or ""))
    testo = "".join(ch for ch in testo if not unicodedata.combining(ch))
    testo = unicodedata.normalize("NFC", testo).casefold()
    return re.sub(r"\s+", " ", testo).strip()
