"""Guida d'uso del modulo Asset dentro il portale (``/assets/guida/``).

Binding ACL v2 su ``assets_view`` (migrazione 0127): chi vede gli asset legge la
guida. I paragrafi che descrivono azioni riservate dicono se l'utente corrente ha
il permesso, cosi' la guida risponde anche alla domanda «perche' non vedo il
pulsante?».
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .services import mfc_stats
from .services.storico_asset import giorni_retention
from .views_asset_qr import MAX_ETICHETTE, can_manage_public_qr
from .views_report_catalog import can_schedule_email


def _puo_leggere_ora(request: HttpRequest) -> bool:
    from contatori.permessi import puo_gestire

    return bool(puo_gestire(request))


@login_required
@require_GET
def guida(request: HttpRequest) -> HttpResponse:
    from .services import report_catalog
    from .views import _assets_shell_context

    return render(request, "assets/pages/guida.html", {
        **_assets_shell_context(request),
        "page_title": "Asset — guida",
        "puo_link_pubblico": can_manage_public_qr(request),
        "puo_pianificare": can_schedule_email(request),
        "puo_leggere_ora": _puo_leggere_ora(request),
        "max_etichette": MAX_ETICHETTE,
        "soglia_consumabili": mfc_stats.giorni_soglia_consumabili(),
        "soglia_contatori": mfc_stats.giorni_soglia_contatori(),
        "mesi_trend": mfc_stats.MESI_TREND,
        "retention_giorni": giorni_retention(),
        "report": list(report_catalog.definizioni().values()),
    })
