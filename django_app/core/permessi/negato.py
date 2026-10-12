"""Risposta unica quando i ruoli non consentono un'azione.

Pagina: messaggio in chiaro (cosa e' successo, a chi rivolgersi), mai un errore
tecnico. API/AJAX: JSON 403, mai un redirect HTML.
"""
from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import render

MESSAGGIO_CONTATTO = (
    "Se ti serve per il tuo lavoro, rivolgiti al reparto IT: "
    "indica la pagina e l'operazione che volevi fare."
)


def _vuole_json(request) -> bool:
    accept = (request.headers.get("Accept") or "").lower()
    content_type = (request.headers.get("Content-Type") or "").lower()
    return (
        "application/json" in accept
        or "application/json" in content_type
        or (request.headers.get("X-Requested-With") or "").lower() == "xmlhttprequest"
        or "/api/" in (request.path or "")
    )


def risposta_negata(request, messaggio: str = "", *, pagina: str = ""):
    testo = messaggio or "Il tuo ruolo non consente questa operazione."
    if _vuole_json(request):
        return JsonResponse(
            {"ok": False, "reason": "forbidden", "error": testo, "contatto": MESSAGGIO_CONTATTO},
            status=403,
        )
    return render(
        request,
        "core/pages/forbidden.html",
        {
            "page_title": "Accesso negato",
            "acl_view": {"page_label": pagina, "messaggio_ruoli": testo},
        },
        status=403,
    )
