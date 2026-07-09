"""Query di sola lettura per il report di compliance SDS (nessun modello nuovo).

Funzioni pure: non toccano `request`, non hanno side effect. Consumate dalla
view `schede_sicurezza.views.report_compliance` sia per il rendering HTML sia
per l'export CSV.
"""
from __future__ import annotations

from dataclasses import dataclass


def prodotti_senza_scheda_corrente():
    """QuerySet dei ProdottoChimico attivi senza nessuna SchedaSicurezza corrente."""
    from .models import ProdottoChimico

    return (
        ProdottoChimico.objects.filter(attivo=True)
        .exclude(schede__is_corrente=True)
        .select_related("reparto")
        .order_by("reparto__nome", "nome")
    )
