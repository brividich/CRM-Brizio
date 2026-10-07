from django import template
from django.template.loader import render_to_string

from core.flash_messages import group, pending_messages

register = template.Library()


@register.simple_tag(takes_context=True)
def flash_messages_fallback(context):
    """Toast dei messaggi che il template della pagina non ha già mostrato."""
    request = context.get("request")
    items = group(pending_messages(request)) if request is not None else []
    return render_to_string("core/components/flash_toasts.html", {"flash_items": items})
