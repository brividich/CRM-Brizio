"""Accessi negati: l'elenco dei 403 e l'azione che li risolve.

La logica (spiegazione, scrittura dei grant, audit, verifica dell'esito) sta in
:mod:`core.acl_resolution`; qui c'e' solo il guscio HTTP. L'azione e' la stessa
sia dal pannello sia dalla pagina 403 durante l'impersonazione, per questo non
usa ``legacy_admin_required``: impersonando, ``request.user`` e' la persona
impersonata e l'amministratore reale va cercato dietro di lei.
"""
from __future__ import annotations

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from core.acl_resolution import (
    ACTION_RESET,
    SCOPE_USER,
    acting_admin,
    apply_resolution,
    describe_access,
    flash_to_forbidden,
    ignore_denial,
    unresolvable_reason,
)
from core.legacy_models import UtenteLegacy
from core.models import AclDenialEvent

from .decorators import legacy_admin_required

FILTRI = ("aperti", "decisi", "tutti")
_MESSAGE_LEVELS = {"success": messages.SUCCESS, "warning": messages.WARNING, "error": messages.ERROR}


def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _safe_next(request) -> str:
    value = str(request.POST.get("next") or "").strip()
    if (
        value.startswith("/")
        and not value.startswith("//")
        and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    ):
        return value
    return reverse("admin_portale:accessi_negati")


@legacy_admin_required
def accessi_negati(request):
    filtro = str(request.GET.get("stato") or "aperti").strip().lower()
    if filtro not in FILTRI:
        filtro = "aperti"

    events_qs = AclDenialEvent.objects.all()
    if filtro == "aperti":
        events_qs = events_qs.filter(status=AclDenialEvent.STATUS_OPEN)
    elif filtro == "decisi":
        events_qs = events_qs.exclude(status=AclDenialEvent.STATUS_OPEN)
    page = Paginator(events_qs.order_by("-last_seen_at", "-id"), 30).get_page(request.GET.get("page"))
    events = list(page.object_list)

    try:
        users = {int(u.id): u for u in UtenteLegacy.objects.filter(id__in={int(e.legacy_user_id) for e in events})}
    except DatabaseError:
        users = {}

    rows = []
    for event in events:
        person = users.get(int(event.legacy_user_id))
        name = str(getattr(person, "nome", "") or "").strip() or f"Utente #{event.legacy_user_id}"
        access = None
        unresolvable = ""
        if person is None:
            unresolvable = "L'utente non esiste più."
        elif event.permission_code:
            access = describe_access(legacy_user=person, permission_code=event.permission_code)
            if not access["resolvable"]:
                unresolvable = "Il permesso di questa pagina è stato disattivato o rimosso dal catalogo."
        else:
            unresolvable = unresolvable_reason({"decision_source": event.decision_source}, person=name) or (
                "Questa pagina non è collegata a un permesso del nuovo sistema."
            )
        rows.append(
            {
                "event": event,
                "person_name": name,
                "access": access,
                "unresolvable": unresolvable,
                "is_open": event.status == AclDenialEvent.STATUS_OPEN,
            }
        )

    try:
        open_count = AclDenialEvent.objects.filter(status=AclDenialEvent.STATUS_OPEN).count()
    except DatabaseError:
        open_count = 0

    return render(
        request,
        "admin_portale/pages/accessi_negati.html",
        {
            "page_title": "Accessi negati",
            "rows": rows,
            "page_obj": page,
            "filtro": filtro,
            "open_count": open_count,
            "next_url": request.get_full_path(),
        },
    )


@csrf_protect
@require_POST
def accessi_negati_azione(request):
    if not acting_admin(request):
        return render(
            request,
            "core/pages/forbidden.html",
            {"page_title": "Accesso negato", "acl_view": {}},
            status=403,
        )

    next_url = _safe_next(request)
    origin = str(request.POST.get("origin") or "").strip()
    action = str(request.POST.get("action") or "").strip().lower()

    if action == "ignore":
        event = AclDenialEvent.objects.filter(pk=_int_or_none(request.POST.get("event_id"))).first()
        if event is not None:
            ignore_denial(request, event)
            messages.success(request, "Segnalazione ignorata: resta consultabile fra quelle decise.")
        return redirect(next_url)

    scope = str(request.POST.get("scope") or "").strip().lower()
    if action == ACTION_RESET:
        scope = SCOPE_USER

    legacy_user = None
    legacy_user_id = _int_or_none(request.POST.get("legacy_user_id"))
    if legacy_user_id:
        try:
            legacy_user = UtenteLegacy.objects.filter(id=legacy_user_id).first()
        except DatabaseError:
            legacy_user = None

    result = apply_resolution(
        request,
        legacy_user=legacy_user,
        permission_code=str(request.POST.get("permission_code") or ""),
        scope=scope,
        action=action,
    )

    if origin == "forbidden":
        # Se ora la pagina si apre, la conferma e' la pagina stessa; altrimenti
        # il messaggio deve comparire sul 403, che i messages non raggiungono.
        if not (result["ok"] and result["allowed_now"]):
            flash_to_forbidden(request, result)
    else:
        messages.add_message(request, _MESSAGE_LEVELS.get(result["level"], messages.INFO), result["message"])
    return redirect(next_url)
