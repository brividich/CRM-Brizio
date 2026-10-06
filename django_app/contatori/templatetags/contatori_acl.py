from django import template

from ..permessi import puo_gestire as _puo_gestire

register = template.Library()


@register.simple_tag(takes_context=True)
def puo_gestire(context):
    """Uso: {% load contatori_acl %}{% puo_gestire as g %} poi {% if g %}…{% endif %}."""
    request = context.get("request")
    return bool(request and _puo_gestire(request))
