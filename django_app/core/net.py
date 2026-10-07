"""IP del client: unica regola per audit, rate limit e log.

``X-Forwarded-For`` lo scrive chiunque: lo si legge SOLO se la connessione arriva
da un proxy in ``settings.TRUSTED_PROXY_IPS``. In quel caso si scorre la catena da
destra (l'ultimo indirizzo l'ha aggiunto il proxy fidato) e si prende il primo IP
che non e' a sua volta un proxy fidato: i valori a sinistra sono scelti dal client.
"""
from __future__ import annotations

from django.conf import settings


def client_ip(request) -> str | None:
    if request is None:
        return None
    remote_addr = (request.META.get("REMOTE_ADDR") or "").strip() or None
    trusted: set[str] = set(getattr(settings, "TRUSTED_PROXY_IPS", set()) or set())
    if not remote_addr or remote_addr not in trusted:
        return remote_addr
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if hop not in trusted:
            return hop[:45]
    return remote_addr
