from django import template
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def kpi(value, decimals=0):
    """Come ``floatformat``, ma un KPI non calcolato si legge «dato non disponibile» (PROMPT 06 - D)."""
    if not getattr(value, "disponibile", True):
        return str(value)
    return floatformat(value, decimals)


@register.filter
def kpi_ok(value) -> bool:
    return bool(getattr(value, "disponibile", True))


@register.filter
def dict_get(data, key):
    if not isinstance(data, dict):
        return ""
    return data.get(key, "")


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def asset_custom_display(data, field):
    if not isinstance(data, dict) or not field:
        return "-"
    code = getattr(field, "code", "")
    label = getattr(field, "label", "")
    field_type = getattr(field, "field_type", "")

    sentinel = object()
    value = data.get(code, sentinel)
    if value is sentinel:
        value = data.get(label, sentinel)
    if value is sentinel:
        return "-"

    if field_type == "BOOL":
        return "Si" if bool(value) else "No"

    if value in ("", None):
        return "-"
    return value
