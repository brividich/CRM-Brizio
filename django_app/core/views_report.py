"""«I miei report»: i report del catalogo che l'utente può lanciare e i suoi scaricamenti."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.shortcuts import render
from django.utils import timezone

from core.models import ReportEmissione
from core.report_centro import catalogo
from core.report_centro.accesso import voci_accessibili

GIORNI_STORICO = 90
MAX_STORICO = 30


def _miei_scaricamenti(request) -> list[dict]:
    legacy_user = getattr(request, "legacy_user", None)
    if legacy_user is None:
        from core.legacy_utils import get_legacy_user

        legacy_user = get_legacy_user(request.user)
    legacy_id = getattr(legacy_user, "id", None)
    if not legacy_id:
        return []
    try:
        righe = list(
            ReportEmissione.objects.filter(
                legacy_user_id=legacy_id,
                created_at__gte=timezone.now() - timedelta(days=GIORNI_STORICO),
            ).order_by("-created_at", "-id")[:MAX_STORICO]
        )
    except DatabaseError:
        return []
    return [{"e": e, "voce": catalogo.voce_per_chiave(e.report_chiave)} for e in righe]


def _ricevuti_per_mail(request) -> list[dict]:
    from core.models import ReportPianificazione
    from core.report_centro.pianificazione import descrivi_frequenza

    try:
        elenco = list(ReportPianificazione.objects.filter(destinatari=request.user, attiva=True).order_by("nome"))
    except DatabaseError:
        return []
    righe = []
    for p in elenco:
        voce = catalogo.voce_per_chiave(p.voce_chiave)
        variante = voce.variante(p.variante) if voce else None
        righe.append({"p": p, "voce": voce, "variante": variante, "frequenza": descrivi_frequenza(p)})
    return righe


@login_required
def miei_report(request):
    if request.GET.get("guida") == "1":
        return render(request, "core/pages/miei_report_guida.html", {"page_title": "Guida · I miei report"})
    gruppi = voci_accessibili(request)
    return render(
        request,
        "core/pages/miei_report.html",
        {
            "page_title": "I miei report",
            "gruppi": gruppi,
            "totale_voci": sum(len(g["righe"]) for g in gruppi),
            "scaricamenti": _miei_scaricamenti(request),
            "ricevuti": _ricevuti_per_mail(request),
            "giorni_storico": GIORNI_STORICO,
        },
    )
