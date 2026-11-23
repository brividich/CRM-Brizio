"""Scala unica della gravita' nel SOC (audit C2).

Ordine del modello ``Severity``: info < bassa < media < attenzione < alta < critica.
Prima ordinamento degli avvisi, gruppi e scheda asset mettevano «attenzione» sotto «media»,
mentre notifiche, postura, ticket e report la mettevano sopra: lo stesso avviso aveva
priorita' diverse da pagina a pagina. Ogni confronto fra gravita' usa ``rango``.
"""
from __future__ import annotations

from security.models import Severity

RANGO_GRAVITA = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.WARNING: 3,
    Severity.HIGH: 4,
    Severity.CRITICAL: 5,
}


def rango(severity, default: int = 0) -> int:
    """Posizione della gravita' nella scala unica; ``default`` per valori sconosciuti."""
    return RANGO_GRAVITA.get(severity, default)
