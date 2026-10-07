from django import template
from django.template.loader import render_to_string

from core.flash_messages import pending_messages

register = template.Library()


@register.simple_tag(takes_context=True)
def flash_messages_fallback(context):
    """Toast dei messaggi che il template della pagina non ha già mostrato."""
    request = context.get("request")
    if request is None:
        return ""
    items = pending_messages(request)
    return render_to_string("core/components/flash_toasts.html", {"flash_items": items})
