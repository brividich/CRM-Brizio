from django import template

register = template.Library()


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
