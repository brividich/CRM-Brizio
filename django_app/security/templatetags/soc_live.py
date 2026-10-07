from django import template

register = template.Library()


@register.inclusion_tag("security/partials/live_strip.html", takes_context=True)
def soc_live_strip(context):
    """Barra di stato del SOC, resa subito con la pagina e poi riletta ogni minuto."""
    from security.services.live_status import live_status

    request = context.get("request")
    return {"live": live_status(getattr(request, "user", None)), "request": request}
