"""Profili di layout: quale veste grafica usa il report che si sta generando.

:meth:`core.pdf.PdfTheme.from_branding` chiama :func:`profilo_corrente` e
sovrappone i campi non vuoti del profilo al template PDF globale. Il report in
corso si ricava dalla route della richiesta (thread-local di
``core.audit_middleware``) → voce del catalogo → assegnazione. Così i moduli
che usano ``core.pdf`` ricevono il profilo senza modifiche.

Ordine di precedenza: assegnazione della **voce** → assegnazione del
**modulo** → nessun profilo (template globale). Un profilo disattivato non
si applica.

Fuori da una richiesta (task pianificati, comandi) si può passare la voce
in modo esplicito: ``PdfTheme.from_branding(voce="assets.pianificati")``.
"""
from __future__ import annotations

import logging

from django.db import DatabaseError

from core.report_centro import catalogo

logger = logging.getLogger(__name__)

_CACHE_ATTR = "_report_centro_profilo_cache"
_NESSUNO = object()


def _richiesta_corrente():
    from core.audit_middleware import get_current_request

    return get_current_request()


def voce_corrente(request=None):
    request = request if request is not None else _richiesta_corrente()
    match = getattr(request, "resolver_match", None)
    view_name = str(getattr(match, "view_name", "") or "")
    return catalogo.voce_per_route(view_name) if view_name else None


def profilo_per_voce(voce):
    """Il profilo attivo assegnato alla voce o al suo modulo, oppure ``None``."""
    if voce is None:
        return None
    from core.models import ReportAssegnazioneLayout

    try:
        assegnazioni = {
            (a.ambito, a.chiave): a.profilo
            for a in ReportAssegnazioneLayout.objects.select_related("profilo").filter(
                chiave__in=[voce.chiave, voce.modulo], profilo__is_active=True
            )
        }
    except DatabaseError:
        logger.warning("Profili layout report non leggibili: uso il template globale.", exc_info=True)
        return None
    return (
        assegnazioni.get((ReportAssegnazioneLayout.AMBITO_VOCE, voce.chiave))
        or assegnazioni.get((ReportAssegnazioneLayout.AMBITO_MODULO, voce.modulo))
    )


def forza_profilo(request, profilo) -> None:
    """Impone un profilo alla richiesta (anteprima dal Centro report)."""
    setattr(request, _CACHE_ATTR, profilo)
    request._report_profilo_layout = getattr(profilo, "nome", "") or ""


def profilo_corrente(voce_chiave: str | None = None):
    """Profilo da applicare al report in costruzione (``None`` = template globale).

    Con ``voce_chiave`` la voce è esplicita; altrimenti si deduce dalla
    richiesta corrente. Il risultato è memorizzato sulla richiesta: i
    generatori che costruiscono il tema più volte fanno una sola query.
    """
    if voce_chiave:
        return profilo_per_voce(catalogo.voce_per_chiave(voce_chiave))
    request = _richiesta_corrente()
    if request is None:
        return None
    cached = getattr(request, _CACHE_ATTR, _NESSUNO)
    if cached is not _NESSUNO:
        return cached
    profilo = profilo_per_voce(voce_corrente(request))
    try:
        setattr(request, _CACHE_ATTR, profilo)
        # Letto dal registro emissioni: traccia quale veste ha avuto il file.
        request._report_profilo_layout = profilo.nome if profilo is not None else ""
    except AttributeError:
        pass
    return profilo
