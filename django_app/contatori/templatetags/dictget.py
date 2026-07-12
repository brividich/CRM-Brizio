from django import template
register = template.Library()


@register.filter
def get(d, key):
    """Accesso a dizionario per chiave nei template: {{ mydict|get:key }}."""
    try:
        return d.get(key)
    except AttributeError:
        return None
