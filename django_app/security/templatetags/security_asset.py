from django import template

from security.permissions import can_view_security_center
from security.services.asset_signals import signals_for_hub_asset

register = template.Library()


@register.inclusion_tag("security/partials/asset_card.html", takes_context=True)
def security_asset_card(context, asset):
    """Scheda «Sicurezza e backup» nella pagina di un asset HUB.

    Compare solo a chi puo' vedere il Security Center e solo se a quell'asset e' collegato
    almeno un dispositivo dei report: la visibilita' del menu non e' un confine di sicurezza,
    quindi il controllo e' qui, lato server.
    """
    request = context.get("request")
    user = getattr(request, "user", None)
    if not can_view_security_center(user) or not getattr(asset, "pk", None):
        return {"show": False}
    data = signals_for_hub_asset(asset)
    linked = asset.security_assets.count()
    return {"show": bool(linked), "asset": asset, "linked": linked, **data}
