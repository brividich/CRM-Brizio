"""Template filter per la presentazione delle notifiche in-app.

Uso nei template::

    {% load notifiche_extras %}
    {% with m=n.tipo|notifica_meta %}
      <span class="notify-ico notify-tono-{{ m.tono }}">{{ m.icona }}</span> {{ m.label }}
    {% endwith %}
"""
from __future__ import annotations

from django import template

from core.notifiche_meta import notifica_meta as _notifica_meta

register = template.Library()


@register.filter(name="notifica_meta")
def notifica_meta(tipo):
    """Ritorna il dict {label, icona, tono} per il tipo notifica (default se ignoto)."""
    return _notifica_meta(tipo)
