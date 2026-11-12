from django import template

from anomalie.codice import codice_anomalia

register = template.Library()


@register.filter(name="codice_anomalia")
def codice_anomalia_filter(value):
    """``{{ a.id|codice_anomalia }}`` → ``AN-00123``."""
    return codice_anomalia(value)
