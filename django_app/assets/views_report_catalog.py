"""Catalogo report asset (PROMPT 06 - D): report del catalogo, filtri salvati, invio pianificato.

Route sotto ``/assets/reports/catalogo/`` con binding ACL v2 su ``assets_reports``
(migrazione 0126). Pianificare un invio email richiede in piu' ``admin_assets`` o
l'azione ``assets/asset_report_email``; i destinatari vengono filtrati per permesso
sia al salvataggio sia a ogni invio.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from core.acl import user_can_modulo_action
from core.audit import log_action

from .models import AssetSavedReport
from .services import report_catalog


def _context(request, **kwargs):
    from .views import _assets_shell_context

    return {**_assets_shell_context(request), **kwargs}


def can_schedule_email(request) -> bool:
    from .views import _is_assets_admin

    if _is_assets_admin(request):
        return True
    return bool(
        user_can_modulo_action(request, "assets", "admin_assets")
        or user_can_modulo_action(request, "assets", "asset_report_email")
    )


def _definizione(code: str):
    definizione = report_catalog.definizioni().get(code)
    if definizione is None:
        raise Http404("Report non disponibile.")
    return definizione


def _pk(raw) -> int:
    """Id da querystring/POST: un valore non numerico e' un 404, non un 500."""
    value = str(raw or "").strip()
    if not value.isascii() or not value.isdigit() or len(value) > 12:
        raise Http404("Report salvato non trovato.")
    return int(value)


def _salvati_visibili(user):
    return AssetSavedReport.objects.filter(Q(owner=user) | Q(condiviso=True)).select_related("owner")


@login_required
@require_GET
def catalog(request: HttpRequest) -> HttpResponse:
    return render(request, "assets/pages/report_catalog.html", _context(
        request,
        page_title="Catalogo report asset",
        definizioni=list(report_catalog.definizioni().values()),
        esistenti=report_catalog.report_esistenti(),
        salvati=_salvati_visibili(request.user).order_by("report_code", "nome"),
    ))


@login_required
@require_GET
def run(request: HttpRequest, code: str) -> HttpResponse:
    definizione = _definizione(code)
    if not report_catalog.accesso_extra(code, request.user):
        return HttpResponse("Serve anche l'accesso al modulo Contatori.", status=403)
    salvato = None
    if request.GET.get("salvato"):
        salvato = get_object_or_404(_salvati_visibili(request.user), pk=_pk(request.GET.get("salvato")), report_code=code)
        filtri = report_catalog.filtri_da_richiesta(definizione, salvato.filtri or {})
    else:
        filtri = report_catalog.filtri_da_richiesta(definizione, request.GET)
    risultato = definizione.esegui(filtri)
    formato = request.GET.get("formato")
    if formato in ("xlsx", "pdf"):
        data, nome, ctype = report_catalog.esporta(definizione, risultato, filtri, formato, request.user)
        log_action(request, "asset_report_export", "assets", {"report": code, "formato": formato, "righe": len(risultato.righe)})
        response = HttpResponse(data, content_type=ctype)
        response["Content-Disposition"] = f'attachment; filename="{nome}"'
        response["X-Content-Type-Options"] = "nosniff"
        return response
    User = get_user_model()
    return render(request, "assets/pages/report_run.html", _context(
        request,
        page_title=definizione.titolo,
        definizione=definizione,
        risultato=risultato,
        filtri=filtri,
        filtri_label=report_catalog.etichetta_filtri(definizione, filtri),
        estrazione=report_catalog.intestazione_estrazione(request.user),
        salvato=salvato,
        puo_modificare_salvato=bool(salvato and salvato.owner_id == request.user.id),
        destinatari_ids=set(salvato.destinatari.values_list("pk", flat=True)) if salvato else set(),
        can_schedule=can_schedule_email(request),
        utenti=User.objects.filter(is_active=True).exclude(email="").order_by("last_name", "first_name", "username")[:500]
        if can_schedule_email(request) else [],
        freq_choices=AssetSavedReport.FREQ_CHOICES,
        format_choices=AssetSavedReport.FORMAT_CHOICES,
        querystring=request.GET.urlencode(),
    ))


def _destinatari_ammessi(code: str, utenti) -> tuple[list, list]:
    ammessi, esclusi = [], []
    for utente in utenti:
        (ammessi if report_catalog.destinatario_ammesso(code, utente) else esclusi).append(utente)
    return ammessi, esclusi


@login_required
@require_POST
def save(request: HttpRequest, code: str) -> HttpResponse:
    definizione = _definizione(code)
    salvato = None
    if request.POST.get("salvato_id"):
        salvato = get_object_or_404(AssetSavedReport, pk=_pk(request.POST["salvato_id"]), owner=request.user, report_code=code)
    nome = (request.POST.get("nome") or "").strip()[:120]
    if not nome:
        messages.error(request, "Dai un nome al report da salvare.")
        return redirect(reverse("assets:report_catalog_run", args=[code]) + "?" + request.POST.get("querystring", ""))
    salvato = salvato or AssetSavedReport(owner=request.user, report_code=code)
    salvato.nome = nome
    salvato.filtri = report_catalog.filtri_da_richiesta(definizione, request.POST)
    salvato.condiviso = bool(request.POST.get("condiviso"))
    frequenza = request.POST.get("frequenza") or ""
    if frequenza and not can_schedule_email(request):
        if (request.headers.get("X-Requested-With") or "").lower() == "xmlhttprequest":
            return JsonResponse({"ok": False, "error": "Permesso negato per l'invio pianificato."}, status=403)
        messages.error(request, "Non hai il permesso di pianificare invii email dei report.")
        frequenza = ""
    salvato.frequenza = frequenza if frequenza in dict(AssetSavedReport.FREQ_CHOICES) else ""
    salvato.formato = request.POST.get("formato") if request.POST.get("formato") in dict(AssetSavedReport.FORMAT_CHOICES) else "xlsx"
    salvato.prossimo_invio = report_catalog.prossimo_invio(salvato.frequenza) if salvato.frequenza else None
    salvato.save()
    if salvato.frequenza:
        User = get_user_model()
        ids = [int(v) for v in request.POST.getlist("destinatari") if str(v).isdigit()][:100]
        ammessi, esclusi = _destinatari_ammessi(code, User.objects.filter(pk__in=ids, is_active=True))
        salvato.destinatari.set(ammessi)
        if esclusi:
            messages.warning(request, f"{len(esclusi)} destinatari esclusi: non hanno accesso a questo report.")
    else:
        salvato.destinatari.clear()
    log_action(request, "asset_report_salvato", "assets",
               {"report": code, "salvato_id": salvato.pk, "condiviso": salvato.condiviso, "frequenza": salvato.frequenza})
    messages.success(request, f"Report «{salvato.nome}» salvato.")
    return redirect(reverse("assets:report_catalog_run", args=[code]) + f"?salvato={salvato.pk}")


@login_required
@require_POST
def delete(request: HttpRequest, pk: int) -> HttpResponse:
    salvato = get_object_or_404(AssetSavedReport, pk=pk, owner=request.user)
    log_action(request, "asset_report_salvato_eliminato", "assets", {"report": salvato.report_code, "salvato_id": salvato.pk})
    salvato.delete()
    messages.success(request, "Report salvato eliminato.")
    return redirect("assets:report_catalog")
