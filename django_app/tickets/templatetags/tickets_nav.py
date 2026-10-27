"""Voci della subnav dei ticket che dipendono dalla persona."""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def vede_altri_ticket(context):
    """Mostra la sezione «Ticket» (ticket di altri) a chi il ruolo li fa vedere."""
    request = context.get("request")
    if request is None:
        return False
    from tickets.views import puo_vedere_altri_ticket

    return puo_vedere_altri_ticket(request)
