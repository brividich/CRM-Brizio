"""Informativa privacy del chiosco: chi l'ha già accettata non la rilegge a ogni ingresso.

La versione è l'impronta del testo (``_informativa_testo.html``): se il testo cambia, la versione
cambia e tutti la rileggono e la spuntano di nuovo al primo ingresso successivo.
"""
from __future__ import annotations

import functools
import hashlib

from django.utils import timezone

TEMPLATE = "fornitori/chiosco/_informativa_testo.html"


@functools.lru_cache(maxsize=1)
def versione() -> str:
    from django.template.loader import render_to_string

    testo = " ".join(render_to_string(TEMPLATE).split())
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()[:16]


def gia_accettata(ospite) -> bool:
    """L'ospite ha accettato la versione in vigore."""
    return bool(ospite is not None and not ospite.anonimizzato and ospite.informativa_letta_il
                and ospite.informativa_versione == versione())


def registra(ospite, ip: str = "") -> list[str]:
    """Segna la lettura adesso (senza salvare); ritorna i campi da salvare."""
    ospite.informativa_letta_il, ospite.informativa_ip = timezone.now(), (ip or "")[:45]
    ospite.informativa_versione = versione()
    return ["informativa_letta_il", "informativa_ip", "informativa_versione"]
