"""Eventi ingeriti: elenco con filtri e grafico, dettaglio, promozione ad alert (allarme mancato dal motore)."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from security.models import SecurityAlert, SecurityEscalationRule, SecurityEventRecord, SecuritySource, Severity
from security.permissions import can_view_security_center
from security.services import event_triage as triage


def _denied(request):
    from security.views import _security_center_denied

    return _security_center_denied(request)


@ensure_csrf_cookie
def events_list(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    result = triage.filter_events(request.GET)
    qs, filters = result["qs"], result["filters"]
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    events = triage.decorate(page.object_list)
    query = request.GET.copy()
    query.pop("page", None)
    day_query = query.copy()
    day_query.pop("giorno", None)
    chip_query = query.copy()
    for key in ("giorni", "from", "to", "giorno"):
        chip_query.pop(key, None)
    decision_query = query.copy()
    decision_query.pop("decision", None)
    types = (
        result["all_period_qs"].order_by().values_list("event_type", flat=True).distinct()
    )
    scope = result["all_period_qs"]
    if result["selected_day"]:
        scope = scope.filter(occurred_at__date=result["selected_day"])
    counts = triage.decision_counts(scope)
    decision_rows = [
        {"code": code, "label": label, "count": counts[code], "help": triage.DECISION_HELP[code]}
        for code, label in triage.DECISIONS if code != "diagnostic" or counts[code]
    ]
    return render(request, "security/events_list.html", {
        "page": page,
        "events": events,
        "filters": filters,
        "decision_rows": decision_rows,
        "total_count": sum(counts.values()),
        "chart": triage.daily_chart(result["period_qs"], result["day_from"], result["day_to"], selected=result["selected_day"]),
        "days": result["days"],
        "custom": result["custom"],
        "day_from": result["day_from"],
        "day_to": result["day_to"],
        "selected_day": result["selected_day"],
        "sources": SecuritySource.objects.order_by("name"),
        "severity_choices": Severity.choices,
        "event_types": sorted(set(types)),
        "query": query.urlencode(),
        "day_query": day_query.urlencode(),
        "chip_query": chip_query.urlencode(),
        "decision_query": decision_query.urlencode(),
        "learned_rules": SecurityEscalationRule.objects.select_related("created_by").order_by("-is_active", "-created_at")[:20],
    })


@ensure_csrf_cookie
def event_detail(request, pk, ai=None):
    if not can_view_security_center(request.user):
        return _denied(request)
    event = get_object_or_404(SecurityEventRecord.objects.select_related("source", "report", "asset"), pk=pk)
    event = triage.decorate([event])[0]
    alert = triage.active_alert_for(event)
    alerts = SecurityAlert.objects.filter(event=event).order_by("-created_at")[:5]
    similar = (
        SecurityEventRecord.objects.filter(event_type=event.event_type, source=event.source).exclude(pk=event.pk)
        .order_by("-occurred_at")[:10]
    )
    rules = [rule for rule in SecurityEscalationRule.objects.filter(is_active=True, event_type=event.event_type) if rule.matches(event)]
    return render(request, "security/event_detail.html", {
        "event": event,
        "alert": alert,
        "alerts": alerts,
        "similar": triage.decorate(similar),
        "signature": triage.signature_candidates(event),
        "matching_rules": rules,
        "severity_choices": [c for c in Severity.choices if c[0] != Severity.INFO],
        "default_severity": event.severity if event.severity not in (Severity.INFO, Severity.LOW) else Severity.WARNING,
        "default_title": triage._alert_title(event),
        "ai": ai,
    })


@require_POST
def event_promote(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    event = get_object_or_404(SecurityEventRecord.objects.select_related("source"), pk=pk)
    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "Scrivi perché è un allarme: serve a chi legge l'alert e a far imparare il sistema.")
        return redirect("security:event_detail", pk=pk)
    alert, rule, created = triage.promote_event(
        event, user=request.user, severity=request.POST.get("severity") or Severity.WARNING,
        title=(request.POST.get("title") or "").strip(), reason=reason,
        learn=request.POST.get("learn") == "1", match_keys=request.POST.getlist("match"),
    )
    text = "Alert creato" if created else "L'evento è stato aggiunto all'alert già aperto"
    if rule:
        text += f"; regola appresa «{rule.name}»: d'ora in poi gli eventi simili diventano alert da soli"
    messages.success(request, text + ".")
    return redirect("security:alert_detail", pk=alert.pk)


@require_POST
def event_confirm_ok(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    event = get_object_or_404(SecurityEventRecord, pk=pk)
    triage.confirm_ok(event, user=request.user)
    messages.success(request, "Confermato: l'evento è a posto.")
    return redirect("security:event_detail", pk=pk)


@require_POST
def event_ai_triage(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    event = get_object_or_404(SecurityEventRecord.objects.select_related("source", "report"), pk=pk)
    ai = triage.ai_triage(event, user=request.user, refresh=request.POST.get("refresh") == "1")
    if request.headers.get("HX-Request"):
        return render(request, "security/partials/event_ai_triage.html", {"ai": ai, "event": event})
    return event_detail(request, pk, ai=ai)


@require_POST
def escalation_rule_toggle(request, pk):
    from security.services.configuration import can_manage_security_config

    # Spegnere una regola appresa riduce gli alert: e' configurazione, non lavoro sul singolo evento.
    if not can_manage_security_config(request.user):
        messages.error(request, "Serve il permesso di configurazione del Security Center.")
        return redirect("security:events")
    rule = get_object_or_404(SecurityEscalationRule, pk=pk)
    triage.set_rule_active(rule, not rule.is_active, request.user)
    messages.success(request, f"Regola «{rule.name}» {'riattivata' if rule.is_active else 'disattivata'}.")
    target = request.POST.get("next") or ""
    return redirect(target if target.startswith("/soc/") and "//" not in target else "security:events")
