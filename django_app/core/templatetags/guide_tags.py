"""Pulsante «?» della barra in alto: apre la guida del modulo in cui ci si trova."""
from django import template
from django.urls import reverse

from core import guide_moduli

register = template.Library()


@register.simple_tag(takes_context=True)
def guida_corrente(context) -> dict:
    request = context.get("request")
    path = getattr(request, "path", "") or ""
    guida = guide_moduli.per_path(path)
    if guida is None or guida["solo_admin"]:
        return {"url": reverse("guide_indice"), "titolo": "Centro guide"}
    return {"url": reverse("guida_modulo", args=[guida["slug"]]), "titolo": f"Guida · {guida['titolo']}"}
