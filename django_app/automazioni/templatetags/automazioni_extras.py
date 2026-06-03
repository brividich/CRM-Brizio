"""Template filters per la UI del modulo automazioni.

Forniscono micro-icone per operatori e action_type, classi CSS per status run
e calcolo della percentuale di durata per le sparkbar — usati in rule_detail,
run_log_list e rule_list.
"""

from __future__ import annotations

from django import template

register = template.Library()


# ─── Mappe operatori → simbolo compatto ────────────────────────────────────────
_OP_SYMBOLS = {
    "equals": "=",
    "not_equals": "≠",
    "changed": "↻",
    "changed_to": "→",
    "changed_from": "←",
    "greater_than": ">",
    "greater_than_or_equal": "≥",
    "less_than": "<",
    "less_than_or_equal": "≤",
    "contains": "∋",
    "not_contains": "∌",
    "starts_with": "▸",
    "ends_with": "◂",
    "is_empty": "∅",
    "is_not_empty": "✓",
    "is_null": "○",
    "is_not_null": "●",
    "is_true": "✓",
    "is_false": "✗",
    "in": "∈",
    "not_in": "∉",
    "days_from_now_lte": "≤d",
    "days_from_now_gte": "≥d",
    "days_span_gt": ">Δd",
    "days_span_gte": "≥Δd",
}


# ─── Mappe action_type → simbolo + categoria ───────────────────────────────────
_ACTION_SYMBOLS = {
    "send_email": "✉",
    "send_teams_message": "💬",
    "send_teams_chat": "💬",
    "send_approval": "✅",
    "update_record": "✎",
    "update_trigger_record": "✎",
    "insert_record": "⊕",
    "create_task": "✓",
    "create_anomalia": "!",
    "create_ticket": "🎫",
    "delay": "⏱",
    "delay_schedule": "⏰",
    "for_each": "↻",
    "branch": "⑂",
    "do_until": "∞",
    "http_request": "🌐",
    "update_dashboard_metric": "📊",
    "log_audit": "📝",
}

_CONTROL_FLOW = {"for_each", "branch", "do_until", "delay", "delay_schedule"}
_SIDE_EFFECT = {"update_record", "update_trigger_record", "insert_record", "create_task",
                "create_anomalia", "create_ticket", "update_dashboard_metric", "http_request"}


@register.filter(name="automazioni_op_symbol")
def automazioni_op_symbol(operator: str) -> str:
    if not operator:
        return "?"
    return _OP_SYMBOLS.get(str(operator).lower(), "?")


@register.filter(name="automazioni_action_symbol")
def automazioni_action_symbol(action_type: str) -> str:
    if not action_type:
        return "?"
    return _ACTION_SYMBOLS.get(str(action_type).lower(), "▸")


@register.filter(name="automazioni_action_chip_class")
def automazioni_action_chip_class(action_type: str) -> str:
    """Restituisce la classe CSS della categoria per `auto-icon-chip`."""
    code = (action_type or "").lower()
    if code in _CONTROL_FLOW:
        return "is-control"
    if code in _SIDE_EFFECT:
        return "is-side"
    return "is-action"


# ─── Run log status → classe CSS ──────────────────────────────────────────────
_RUN_STATUS_CLASS = {
    "ok": "is-ok",
    "success": "is-ok",
    "failed": "is-fail",
    "error": "is-fail",
    "skipped": "is-skip",
    "skip": "is-skip",
    "pending": "is-pending",
    "running": "is-pending",
}


@register.filter(name="automazioni_run_status_class")
def automazioni_run_status_class(status: str) -> str:
    return _RUN_STATUS_CLASS.get((status or "").lower(), "is-pending")


# ─── Percentuale durata su max (per sparkbar) ─────────────────────────────────
@register.filter(name="automazioni_dur_pct")
def automazioni_dur_pct(value, max_value) -> int:
    """Restituisce la percentuale 0-100 di `value` su `max_value` (intero).

    Una durata sotto il 5% del massimo viene comunque mostrata almeno al 5%,
    per garantire visibilità sulla sparkbar.
    """
    try:
        v = float(value or 0)
        m = float(max_value or 0)
    except (TypeError, ValueError):
        return 0
    if m <= 0:
        return 0
    pct = max(5.0, min(100.0, (v / m) * 100.0))
    return int(pct)
