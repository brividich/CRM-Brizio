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


@register.filter(name="quando_notifica")
def quando_notifica(momento):
    """«adesso», «12 min fa», «3 ore fa», «ieri 14:05», oltre «12/11 09:30»."""
    if not momento:
        return ""
    from django.utils import timezone

    ora = timezone.localtime()
    locale = timezone.localtime(momento)
    secondi = (ora - locale).total_seconds()
    if secondi < 60:
        return "adesso"
    if secondi < 3600:
        return f"{int(secondi // 60)} min fa"
    if locale.date() == ora.date():
        ore = int(secondi // 3600)
        return "1 ora fa" if ore == 1 else f"{ore} ore fa"
    if (ora.date() - locale.date()).days == 1:
        return f"ieri {locale:%H:%M}"
    return f"{locale:%d/%m %H:%M}"
