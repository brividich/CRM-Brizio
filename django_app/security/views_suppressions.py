"""Soppressioni (manuali e apprese): elenco, scadenze, hit, revoca con motivo."""
from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import SecurityAlertDismissal, SecurityAlertSuppressionRule
from .permissions import can_view_security_center
from .services import soc_settings
from .services.configuration import can_manage_security_config
from .services.learned_suppression import revoke_rule

EXPIRING_DAYS = 14
KIND_FILTERS = {"apprese": "Apprese", "manuali": "Manuali", "tutte": "Tutte"}
STATE_FILTERS = {"attive": "Attive", "in-scadenza": "In scadenza", "scadute": "Scadute o revocate", "tutte": "Tutte"}


def _denied(request):
    from .views import _security_center_denied

    return _security_center_denied(request)


def suppressions_list(request):
    if not can_view_security_center(request.user):
        return _denied(request)
    now = timezone.now()
    kind = request.GET.get("tipo", "tutte")
    kind = kind if kind in KIND_FILTERS else "tutte"
    state = request.GET.get("stato", "attive")
    state = state if state in STATE_FILTERS else "attive"
    qs = SecurityAlertSuppressionRule.objects.select_related("source", "created_by").order_by("-is_active", "expires_at", "-created_at")
    learned_q = Q(owner=SecurityAlertSuppressionRule.LEARNED_OWNER)
    if kind == "apprese":
        qs = qs.filter(learned_q)
    elif kind == "manuali":
        qs = qs.exclude(learned_q)
    live_q = Q(is_active=True) & (Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    if state == "attive":
        qs = qs.filter(live_q)
    elif state == "in-scadenza":
        qs = qs.filter(live_q, expires_at__lte=now + timedelta(days=EXPIRING_DAYS))
    elif state == "scadute":
        qs = qs.exclude(live_q)
    rules = list(qs[:500])
    for rule in rules:
        rule.is_live = rule.is_active and not rule.is_expired
        rule.expiring = bool(rule.is_live and rule.expires_at and rule.expires_at <= now + timedelta(days=EXPIRING_DAYS))
    all_rules = SecurityAlertSuppressionRule.objects.all()
    counts = {
        "learned_active": all_rules.filter(learned_q).filter(live_q).count(),
        "manual_active": all_rules.exclude(learned_q).filter(live_q).count(),
        "expiring": all_rules.filter(live_q, expires_at__lte=now + timedelta(days=EXPIRING_DAYS)).count(),
    }
    return render(request, "security/suppressions.html", {
        "rules": rules, "kind": kind, "state": state, "kind_filters": KIND_FILTERS, "state_filters": STATE_FILTERS,
        "counts": counts, "can_edit": can_manage_security_config(request.user), "expiring_days": EXPIRING_DAYS,
        "learning_enabled": soc_settings.value("soppressione.appresa.attivo"),
        "threshold": soc_settings.value("soppressione.appresa.soglia"),
        "window_days": soc_settings.value("soppressione.appresa.finestra_giorni"),
        "recent_dismissals": SecurityAlertDismissal.objects.select_related("alert", "learned_rule")[:20],
    })


@require_POST
def suppression_revoke(request, pk):
    if not can_view_security_center(request.user):
        return _denied(request)
    if not can_manage_security_config(request.user):
        messages.error(request, "Per revocare una soppressione serve il permesso di configurazione del SOC.")
        return redirect("security:suppressions")
    rule = get_object_or_404(SecurityAlertSuppressionRule, pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, "Scrivi il motivo della revoca.")
        return redirect("security:suppressions")
    if revoke_rule(rule, user=request.user, reason=f"Revocata da {request.user.get_username()}: {reason}"):
        messages.success(request, f"Soppressione «{rule.name}» revocata: le prossime occorrenze torneranno a creare alert.")
    else:
        messages.info(request, "La soppressione era già spenta.")
    return redirect("security:suppressions")
