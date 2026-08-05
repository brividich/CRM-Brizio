"""Task pesanti del modulo carichi (eseguibili async via django-q2).

La saturazione e' un calcolo aggregato: lo si puo' precalcolare con django-q2 e
servirlo dalla cache. Le viste usano `saturazione_finestra` (cache-backed con
fallback live), cosi' funzionano anche senza cluster q2 attivo.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.cache import cache
from django.utils import timezone

from .saturazione import calcola_saturazione

_CACHE_PREFIX = "gcm_saturazione"
_CACHE_TTL = 600  # 10 minuti


def _cache_key(start: date, giorni_n: int) -> str:
    return f"{_CACHE_PREFIX}:{start.isoformat()}:{giorni_n}"


def _calcola(start: date, giorni_n: int) -> dict:
    from .models import Macchina, Pianificazione

    giorni = []
    d = start
    while len(giorni) < giorni_n:        # solo giorni lavorativi, come le viste
        if d.weekday() < 5:
            giorni.append(d)
        d += timedelta(days=1)
    fine = giorni[-1]
    macchine = list(Macchina.objects.filter(attivo=True))
    pians = Pianificazione.objects.filter(
        data__range=(start, fine), macchina__in=macchine or [0]
    ).only("macchina_id", "ore")
    return calcola_saturazione(macchine, pians, giorni)


def saturazione_finestra(start: date, giorni_n: int, *, usa_cache: bool = True) -> dict:
    """Ritorna la saturazione della finestra; usa la cache se disponibile."""
    key = _cache_key(start, giorni_n)
    if usa_cache:
        cached = cache.get(key)
        if cached is not None:
            return cached
    result = _calcola(start, giorni_n)
    cache.set(key, result, timeout=_CACHE_TTL)
    return result


def aggiorna_saturazione_cache(start_iso: str | None = None, giorni_n: int = 21) -> dict:
    """Task django-q2: precalcola e mette in cache la saturazione della finestra."""
    start = date.fromisoformat(start_iso) if start_iso else (
        timezone.localdate() - timedelta(days=timezone.localdate().weekday())
    )
    result = _calcola(start, giorni_n)
    cache.set(_cache_key(start, giorni_n), result, timeout=_CACHE_TTL)
    return {"ok": True, "start": start.isoformat(), "giorni": giorni_n,
            "totale_perc": result["totale"]["perc"]}
