from __future__ import annotations

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from .services import resolve_request_module_name


def monitoring_ui(request) -> dict[str, dict[str, object]]:
    enabled = bool(getattr(settings, "MONITORING_ENABLED", True))
    resolver_match = getattr(request, "resolver_match", None)

    try:
        report_url = reverse("monitoring:report_problem") if enabled else ""
    except NoReverseMatch:
        report_url = ""

    return {
        "monitoring_ui": {
            "enabled": enabled,
            "report_url": report_url,
            "route_name": getattr(resolver_match, "view_name", "") or "",
            "module_name": resolve_request_module_name(request),
        }
    }
