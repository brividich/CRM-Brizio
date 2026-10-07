"""Registro incidenti (NIS2 / GDPR): elenco, scheda, modifica, notifiche, PDF."""
from datetime import datetime, timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import SecurityIncidentForm
from .models import SecurityIncident, SecurityRemediationTicket
from .permissions import can_view_security_center
from .services import incidents as svc


def _denied(request):
    from security.views import _security_center_denied

    return _security_center_denied(request)


def _decorate(incident, now):
    incident.next_deadline = svc.next_open_deadline(incident, now)
    incident.deadline_list = svc.deadlines(incident, now)
    return incident


def incidents_list(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    rows = SecurityIncident.objects.select_related("owner")
    status = request.GET.get("status", "active")
    if status == "active":
        rows = rows.filter(status__in=svc.ACTIVE_STATUSES)
    elif status in dict(SecurityIncident.STATUS_CHOICES):
        rows = rows.filter(status=status)
    scope = request.GET.get("scope", "")
    if scope == "nis2":
        rows = rows.filter(is_significant=True)
    elif scope == "gdpr":
        rows = rows.filter(personal_data_breach=True)
    year = request.GET.get("year", "")
    if year.isdigit():
        rows = rows.filter(detected_at__year=int(year))
    query = request.GET.get("q", "").strip()
    if query:
        rows = rows.filter(Q(title__icontains=query) | Q(code__icontains=query) | Q(csirt_reference__icontains=query))
    now = timezone.now()
    total = rows.count()
    incidents = [_decorate(incident, now) for incident in rows[:300]]
    years = sorted({d.year for d in SecurityIncident.objects.dates("detected_at", "year")}, reverse=True)
    return render(request, "security/incidents_list.html", {
        "incidents": incidents,
        "total": total,
        "filters": {"status": status, "scope": scope, "year": year, "q": query},
        "status_choices": SecurityIncident.STATUS_CHOICES,
        "years": years,
        "urgent": svc.urgent_incidents(now),
    })


def incident_create(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    if request.method == "POST":
        form = SecurityIncidentForm(request.POST)
        if form.is_valid():
            data = {name: value for name, value in form.cleaned_data.items()}
            incident = svc.create_incident(request.user, **data)
            messages.success(request, f"Incidente {incident.code} registrato.")
            return redirect("security:incident_detail", pk=incident.pk)
    else:
        form = SecurityIncidentForm(initial={"detected_at": timezone.localtime().replace(second=0, microsecond=0), "owner": request.user.pk})
    return render(request, "security/incident_form.html", {"form": form, "incident": None})


@require_POST
def incident_from_case(request, case_pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    case = get_object_or_404(SecurityRemediationTicket, pk=case_pk)
    existing = case.incidents.order_by("-detected_at").first()
    if existing:
        messages.info(request, f"Il ticket è già collegato all'incidente {existing.code}.")
        return redirect("security:incident_detail", pk=existing.pk)
    incident = svc.create_from_case(case, request.user)
    messages.success(request, f"Incidente {incident.code} aperto dal ticket #{case.pk}: valuta se è significativo.")
    return redirect("security:incident_edit", pk=incident.pk)


def incident_detail(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    incident = get_object_or_404(SecurityIncident.objects.select_related("owner", "created_by", "significance_assessed_by"), pk=pk)
    now = timezone.now()
    _decorate(incident, now)
    linkable = (
        SecurityRemediationTicket.objects.exclude(incidents=incident).order_by("-updated_at")[:50]
    )
    return render(request, "security/incident_detail.html", {
        "incident": incident,
        "criteria_labels": [svc.SIGNIFICANCE_LABELS.get(code, code) for code in incident.significance_criteria or []],
        "tickets": incident.tickets.order_by("-updated_at"),
        "alerts": incident.alerts.select_related("source").order_by("-created_at")[:50],
        "logs": incident.logs.all()[:200],
        "milestone_choices": [(key, label) for key, (_field, label) in svc.MILESTONES.items()],
        "linkable_tickets": linkable,
        "now_local": timezone.localtime(now).strftime("%Y-%m-%dT%H:%M"),
    })


def incident_edit(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    incident = get_object_or_404(SecurityIncident, pk=pk)
    if request.method == "POST":
        before = svc.snapshot(incident)
        form = SecurityIncidentForm(request.POST, instance=incident)
        if form.is_valid():
            incident = form.save()
            changes = svc.save_changes(incident, before, request.user)
            messages.success(request, f"Incidente aggiornato ({len(changes)} modifiche)." if changes else "Nessuna modifica.")
            return redirect("security:incident_detail", pk=incident.pk)
    else:
        form = SecurityIncidentForm(instance=incident)
    return render(request, "security/incident_form.html", {"form": form, "incident": incident})


def _parse_local_datetime(value):
    value = (value or "").strip()
    if not value:
        return timezone.now()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return timezone.make_aware(datetime.strptime(value, fmt), timezone.get_current_timezone())
        except ValueError:
            continue
    return None


@require_POST
def incident_milestone(request, pk, key):
    if not can_view_security_center(request.user):
        return _denied(request)
    incident = get_object_or_404(SecurityIncident, pk=pk)
    if key not in svc.MILESTONES:
        messages.error(request, "Notifica sconosciuta.")
        return redirect("security:incident_detail", pk=pk)
    if request.POST.get("clear"):
        svc.clear_milestone(incident, key, request.user)
        messages.info(request, "Data di invio annullata.")
        return redirect("security:incident_detail", pk=pk)
    when = _parse_local_datetime(request.POST.get("sent_at"))
    if when is None or when > timezone.now() + timedelta(minutes=5):
        messages.error(request, "Data di invio non valida (non può essere nel futuro).")
        return redirect("security:incident_detail", pk=pk)
    svc.record_milestone(incident, key, request.user, when=when, reference=request.POST.get("reference", "").strip())
    messages.success(request, f"{svc.MILESTONES[key][1]}: invio registrato.")
    return redirect("security:incident_detail", pk=pk)


@require_POST
def incident_note(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    incident = get_object_or_404(SecurityIncident, pk=pk)
    if svc.add_note(incident, request.user, request.POST.get("body", "")):
        messages.success(request, "Nota aggiunta.")
    return redirect("security:incident_detail", pk=pk)


@require_POST
def incident_link_case(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    incident = get_object_or_404(SecurityIncident, pk=pk)
    case_id = request.POST.get("ticket", "")
    if case_id.isdigit():
        case = get_object_or_404(SecurityRemediationTicket, pk=int(case_id))
        svc.link_case(incident, case, request.user)
        messages.success(request, f"Ticket #{case.pk} collegato.")
    return redirect("security:incident_detail", pk=pk)


def _pdf_response(content, filename):
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def incident_pdf(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    from security.services.soc_pdf import render_incident_pdf

    incident = get_object_or_404(SecurityIncident.objects.select_related("owner"), pk=pk)
    return _pdf_response(render_incident_pdf(incident), f"{incident.code or incident.pk}.pdf")


def incidents_register_pdf(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    from security.services.soc_pdf import render_incident_register_pdf

    year = request.GET.get("year", "")
    rows = SecurityIncident.objects.select_related("owner").order_by("detected_at")
    if year.isdigit():
        rows = rows.filter(detected_at__year=int(year))
    label = year if year.isdigit() else "completo"
    return _pdf_response(render_incident_register_pdf(list(rows), label), f"registro-incidenti-{label}.pdf")
