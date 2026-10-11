"""Automatismi di risoluzione: registro delle regole di rientro, simulazione, interruttori.

Sotto ``/soc/admin/config/``: serve il permesso di configurazione del SOC (anche per simulare,
perché la simulazione registra quando è stata eseguita e sblocca l'accensione).
"""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .permissions import can_view_security_center
from .services import auto_resolution
from .services.configuration import can_manage_security_config


def _guard(request):
    if not can_view_security_center(request.user):
        from .views import _security_center_denied

        return _security_center_denied(request)
    if not can_manage_security_config(request.user):
        messages.error(request, "Gli automatismi si gestiscono con il permesso di configurazione del SOC.")
        return redirect("security:dashboard")
    return None


def _rule(code):
    if code not in auto_resolution.REGISTRY:
        raise Http404
    return auto_resolution.REGISTRY[code]


def automation_page(request):
    denied = _guard(request)
    if denied:
        return denied
    return render(request, "security/automation_rules.html", {
        "rows": auto_resolution.registry_rows(),
        "global_enabled": auto_resolution.auto_resolve_enabled(),
        "simulation": request.session.pop("soc_autoresolve_simulation", None),
        "simulation_days": auto_resolution.SIMULATION_DAYS,
        "valid_days": auto_resolution.SIMULATION_VALID_DAYS,
        "vpn_days": auto_resolution.vpn_days(),
    })


@require_POST
def automation_simulate(request, code):
    denied = _guard(request)
    if denied:
        return denied
    _rule(code)
    result = auto_resolution.simulate(code, actor=request.user)
    request.session["soc_autoresolve_simulation"] = result
    return redirect("security:automation")


@require_POST
def automation_toggle(request, code):
    denied = _guard(request)
    if denied:
        return denied
    rule = _rule(code)
    enable = request.POST.get("enabled") == "1"
    try:
        auto_resolution.set_rule_enabled(code, enable, actor=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Regola «{rule.label}» {'accesa' if enable else 'spenta'}.")
    if code == "vpn_within_limits" and request.POST.get("giorni", "").isdigit():
        from .services.configuration import set_setting

        set_setting("autoresolve.vpn_within_limits.giorni", max(1, min(30, int(request.POST["giorni"]))), actor=request.user,
                    category="automatismi", description="Giorni nei limiti per chiudere un alert VPN")
    return redirect("security:automation")
