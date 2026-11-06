"""Pagina personale «Non voglio più aggiornamenti su questo OP» (vedi ``silenzia_op``)."""
from __future__ import annotations

from urllib.parse import quote

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from core.audit import log_action

from . import silenzia_op
from .guida import con_guida


@login_required
@csrf_protect
@require_http_methods(["GET", "POST"])
@con_guida
def op_silenzia_page(request):
    """Il GET non cambia niente: i controlli antivirus della posta aprono i link da soli."""
    op = silenzia_op.op_pulito(request.POST.get("op") if request.method == "POST" else request.GET.get("op"))
    if request.method == "POST" and op:
        azione = request.POST.get("azione")
        if azione == "silenzia":
            nome = request.user.get_full_name() or request.user.get_username()
            if silenzia_op.silenzia(op, request.user, nome):
                log_action(request, "anomalie_op_silenziato", "anomalie", {"op_id": op})
        elif azione == "riattiva":
            if silenzia_op.riattiva(op, request.user):
                log_action(request, "anomalie_op_riattivato", "anomalie", {"op_id": op})
        return redirect(f"{reverse('anomalie_op_silenzia')}?op={quote(op, safe='')}")

    silenziati = silenzia_op.op_silenziati_utente(request.user)
    return render(request, "anomalie/pages/op_silenzia.html", {
        "op": op,
        "silenziato": op.lower() in {s.strip().lower() for s in silenziati},
        "silenziati": silenziati,
        "ha_indirizzo": bool(silenzia_op.indirizzi_utente(request.user)),
    })


@login_required
@csrf_protect
@require_POST
def api_op_silenziato_riattiva(request, pk: int):
    """Dal pannello Notifiche: toglie il silenzio di una persona su un OP."""
    from .mail_action_models import AnomaliaOpSilenziata
    from .views import _can_manage_anomalie_config

    if not _can_manage_anomalie_config(request):
        return JsonResponse({"success": False, "error": "Permesso negato"}, status=403)
    riga = AnomaliaOpSilenziata.objects.filter(pk=pk).first()
    if riga is None:
        return JsonResponse({"success": False, "error": "Non trovato"}, status=404)
    log_action(request, "anomalie_op_riattivato", "anomalie", {"op_id": riga.op_id, "email": riga.email})
    riga.delete()
    return JsonResponse({"success": True})
