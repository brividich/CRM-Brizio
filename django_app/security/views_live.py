"""Barra di stato live, anteprime a pannello, azioni massive e controlli AI del SOC."""
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import SecurityAlert, SecurityEventRecord, SecurityIncident, SecurityRemediationTicket, Severity
from .permissions import can_view_security_center


def _denied(request):
    from security.views import _security_center_denied

    return _security_center_denied(request)


def _ids(request, name):
    return [int(v) for v in request.POST.getlist(name) if str(v).isdigit()]


def _back(request, default):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return default


# --- Barra di stato ------------------------------------------------------------------------

def live_strip(request):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    from .services.live_status import live_status

    return render(request, "security/partials/live_strip.html", {"live": live_status(request.user)})


# --- Anteprime -----------------------------------------------------------------------------

def preview(request, kind, pk=None):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    now = timezone.now()
    if kind == "alert":
        from .services.alert_lifecycle import ACTIVE_ALERT_STATUSES

        alert = get_object_or_404(SecurityAlert.objects.select_related("source", "event", "event__asset"), pk=pk)
        return render(request, "security/partials/preview_alert.html", {
            "alert": alert, "active": alert.status in ACTIVE_ALERT_STATUSES,
            "rule": (alert.decision_trace or {}).get("rule") or (alert.decision_trace or {}).get("decision") or "—",
            "logs": alert.action_logs.order_by("-created_at")[:5],
            "case": alert.linked_remediation_tickets.order_by("-updated_at").first() or alert.tickets.order_by("-updated_at").first(),
        })
    if kind == "ticket":
        from .services.cases import ACTIVE_CASE_STATUSES, case_alerts, case_timeline

        case = get_object_or_404(SecurityRemediationTicket.objects.select_related("source", "assignee"), pk=pk)
        tasks = list(case.tasks.all())
        return render(request, "security/partials/preview_ticket.html", {
            "case": case, "alerts": case_alerts(case)[:5], "tasks": tasks, "tasks_open": sum(1 for t in tasks if not t.done),
            "timeline": case_timeline(case)[:5], "active": case.status in ACTIVE_CASE_STATUSES,
        })
    if kind == "incident":
        from .services.incidents import deadlines

        incident = get_object_or_404(SecurityIncident.objects.select_related("owner"), pk=pk)
        return render(request, "security/partials/preview_incident.html", {
            "incident": incident, "deadlines": deadlines(incident, now), "logs": incident.logs.all()[:4],
            "tickets": incident.tickets.order_by("-updated_at")[:4],
        })
    if kind == "event":
        event = get_object_or_404(SecurityEventRecord.objects.select_related("source", "asset", "report"), pk=pk)
        from .templatetags.security_i18n import ui_label

        payload = [(ui_label(k), v) for k, v in (event.payload or {}).items() if not isinstance(v, (dict, list)) and k not in {"dedup_hash", "raw_body_hash", "fingerprint"}][:12]
        return render(request, "security/partials/preview_event.html", {"event": event, "payload": payload, "alerts": event.alerts.all()[:3]})
    if kind == "pc":
        from .services.pc_overview import pc_overview

        name = request.GET.get("nome", "").strip()
        data = pc_overview(name) if name else None
        if data is None:
            raise Http404("Nessun dato SOC per questo dispositivo.")
        return render(request, "security/partials/preview_pc.html", {"pc": data, "name_q": quote(data["name"])})
    raise Http404("Anteprima non disponibile.")


# --- Controlli AI --------------------------------------------------------------------------

@require_POST
def incident_ai_check(request, pk):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    from .services.ai_explain import check_incident

    incident = get_object_or_404(SecurityIncident.objects.select_related("owner"), pk=pk)
    ai = check_incident(incident, user=request.user, refresh=request.POST.get("refresh") == "1")
    return render(request, "security/partials/ai_explanation.html", {"ai": ai})


@require_POST
def pc_ai_check(request):
    if not can_view_security_center(request.user):
        return HttpResponseForbidden("Accesso negato")
    from .services.ai_explain import check_pc
    from .services.pc_overview import pc_overview

    data = pc_overview(request.POST.get("nome", "").strip())
    if data is None:
        raise Http404("Nessun dato SOC per questo dispositivo.")
    ai = check_pc(data, user=request.user, refresh=request.POST.get("refresh") == "1")
    return render(request, "security/partials/ai_explanation.html", {"ai": ai})


# --- Azioni massive ------------------------------------------------------------------------

@require_POST
def tickets_bulk(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services.cases import CASE_STATUSES, assign_case, set_case_status

    back = _back(request, "security:tickets_list")
    cases = list(SecurityRemediationTicket.objects.filter(pk__in=_ids(request, "ticket_ids")))
    if not cases:
        messages.error(request, "Nessun ticket selezionato.")
        return redirect(back)
    action = request.POST.get("action", "")
    done = 0
    if action in ("assign_me", "assign"):
        if action == "assign_me":
            user = request.user
        else:
            uid = request.POST.get("assignee", "")
            user = get_user_model().objects.filter(pk=int(uid), is_active=True).first() if uid.isdigit() else None
            if user is None:
                messages.error(request, "Scegli a chi assegnare i ticket.")
                return redirect(back)
        for case in cases:
            if case.assignee_id != user.pk:
                assign_case(case, user, user=request.user)
                done += 1
        messages.success(request, f"{done} ticket assegnati a {user.get_full_name() or user.get_username()}.")
        return redirect(back)
    status = request.POST.get("status", "")
    if action == "status" and status in CASE_STATUSES:
        reason = request.POST.get("reason", "").strip()
        closing = status in ("resolved", "closed", "false_positive")
        if closing and not reason:
            messages.error(request, "Per chiudere più ticket insieme scrivi l'esito: resta nella traccia di ognuno.")
            return redirect(back)
        skipped = 0
        for case in cases:
            if case.status == status:
                continue
            try:
                set_case_status(case, status, user=request.user, reason=reason, close_alerts=closing and request.POST.get("close_alerts") == "1")
                done += 1
            except Exception:  # noqa: BLE001 - es. riapertura in conflitto con un caso attivo
                skipped += 1
        messages.success(request, f"Stato aggiornato su {done} ticket" + (f"; {skipped} non modificabili." if skipped else "."))
        return redirect(back)
    messages.error(request, "Azione non supportata.")
    return redirect(back)


@require_POST
def incidents_bulk(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import incidents as svc

    back = _back(request, "security:incidents")
    incidents = list(SecurityIncident.objects.filter(pk__in=_ids(request, "incident_ids")))
    if not incidents:
        messages.error(request, "Nessun incidente selezionato.")
        return redirect(back)
    action = request.POST.get("action", "")
    done = 0
    for incident in incidents:
        before = svc.snapshot(incident)
        if action == "owner_me":
            incident.owner = request.user
        elif action == "status" and request.POST.get("status") in dict(SecurityIncident.STATUS_CHOICES):
            incident.status = request.POST["status"]
        else:
            messages.error(request, "Azione non supportata.")
            return redirect(back)
        incident.save()
        done += bool(svc.save_changes(incident, before, request.user))
    messages.success(request, f"{done} incident{'e aggiornato' if done == 1 else 'i aggiornati'}.")
    return redirect(back)


@require_POST
def events_bulk(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from .services import event_triage as triage

    back = _back(request, "security:events")
    events = list(SecurityEventRecord.objects.filter(pk__in=_ids(request, "event_ids")).select_related("source"))
    if not events:
        messages.error(request, "Nessun evento selezionato.")
        return redirect(back)
    action = request.POST.get("action", "")
    if action == "ok":
        for event in events:
            triage.confirm_ok(event, user=request.user)
        messages.success(request, f"{len(events)} eventi confermati a posto.")
        return redirect(back)
    if action == "promote":
        reason = request.POST.get("reason", "").strip()
        if not reason:
            messages.error(request, "Scrivi perché sono allarmi: resta nell'alert e insegna al sistema.")
            return redirect(back)
        severity = request.POST.get("severity") if request.POST.get("severity") in dict(Severity.choices) else Severity.WARNING
        created = 0
        for event in events:
            _alert, _rule, was_created = triage.promote_event(event, user=request.user, severity=severity, reason=reason, learn=False)
            created += bool(was_created)
        messages.success(request, f"{created} alert creati da {len(events)} eventi (gli altri sono finiti in alert già aperti).")
        return redirect(back)
    messages.error(request, "Azione non supportata.")
    return redirect(back)


@require_POST
def backup_bulk_case(request):
    """Un ticket per i PC selezionati nella pagina Backup, con un'attività per PC."""
    if not can_view_security_center(request.user):
        return _denied(request)
    from .models import BackupJobRecord
    from .services.cases import open_manual_case

    names = [n.strip() for n in request.POST.getlist("devices") if n.strip()][:100]
    back = _back(request, "security:backup")
    if not names:
        messages.error(request, "Nessun PC selezionato.")
        return redirect(back)
    last = BackupJobRecord.objects.select_related("source").order_by("-created_at").first()
    if last is None:
        messages.error(request, "Nessun report di backup: impossibile collegare il ticket a una sorgente.")
        return redirect(back)
    title = request.POST.get("title", "").strip() or (f"Backup da sistemare: {names[0]}" if len(names) == 1 else f"Backup da sistemare su {len(names)} PC")
    case = open_manual_case(
        source=last.source, title=title, user=request.user, assignee=request.user, severity=Severity.WARNING,
        description="PC selezionati dalla pagina Backup: " + ", ".join(names),
        tasks=[f"Verificare e ripristinare il backup di {name}" for name in names],
    )
    messages.success(request, f"Ticket #{case.pk} aperto con {len(names)} PC e assegnato a te.")
    return redirect("security:case_detail", pk=case.pk)


