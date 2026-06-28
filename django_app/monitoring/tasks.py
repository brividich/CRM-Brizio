"""Task django-q del modulo monitoring."""
from __future__ import annotations

from monitoring import health


def run_ai_readiness_alert(**kwargs) -> dict:
    """Entry point schedulato: readiness AI (+ servizi) con alert email su degrado.

    Fail-safe per design (i singoli check catturano le eccezioni); l'invio mail è
    rate-limited e solo-al-cambio-stato dentro ``health.run_ai_readiness_alert``.
    """
    include_services = bool(kwargs.get("include_services", True))
    return health.run_ai_readiness_alert(include_services=include_services)
