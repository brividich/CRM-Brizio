"""Viste del modulo Automazioni — Funzioni e costanti condivise dai pilastri del modulo (un solo punto di lookup per i test).

Spacchettamento di ``automazioni/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import json
from datetime import datetime

from django.utils import timezone

from core.audit import log_action

from ..models import (
    AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE,
    AutomationDeliveryEndpoint,
    list_teams_flow_endpoints,
)
from ..source_registry import (
    AUTOMAZIONI_ACL_ACTIONS,
    AUTOMAZIONI_MODULE_CODE,
)




def _base_context() -> dict[str, object]:
    return {
        "automazioni_module_code": AUTOMAZIONI_MODULE_CODE,
        "acl_action_contract": AUTOMAZIONI_ACL_ACTIONS,
    }


def _get_filter_value(request, key: str) -> str:
    return str(request.GET.get(key) or "").strip()


def _json_pretty(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, dict):
        return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    try:
        parsed = json.loads(value)
        return json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError, json.JSONDecodeError):
        return str(value)


def _string_value(value) -> str:
    return str(value or "").strip()


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return _string_value(value).lower() in {"1", "true", "on", "yes"}


def _get_active_teams_flow_endpoints():
    """Restituisce la lista degli endpoint Teams Flow attivi per i template."""
    endpoints, _warning = _get_teams_flow_endpoints_context(active_only=True)
    return endpoints


def _get_teams_flow_endpoints_context(*, active_only: bool | None = None) -> tuple[list[AutomationDeliveryEndpoint], str]:
    endpoints, unavailable = list_teams_flow_endpoints(active_only=active_only)
    return (
        endpoints,
        AUTOMATION_DELIVERY_ENDPOINT_UNAVAILABLE_MESSAGE if unavailable else "",
    )


def _format_display_datetime(value) -> str:
    if not value:
        return "-"
    parsed = value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return "-"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return raw
    if isinstance(parsed, datetime):
        if parsed.year < 1901:
            return "-"
        current_tz = timezone.get_current_timezone()
        if timezone.is_naive(parsed):
            # Alcuni backend/driver restituiscono datetime naive pur usando USE_TZ.
            # Li trattiamo come orario del progetto prima della formattazione finale.
            parsed = timezone.make_aware(parsed, current_tz)
        parsed = timezone.localtime(parsed, current_tz)
        return parsed.strftime("%d-%m-%Y %H:%M:%S")
    return str(parsed)


# Nomi importati che i pilastri chiamano come ``_helpers.X`` (un solo bersaglio per mock.patch).
_VIA_HELPERS = (log_action)
