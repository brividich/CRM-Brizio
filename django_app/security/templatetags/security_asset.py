from django import template

from security.permissions import can_view_security_center
from security.services.asset_signals import signals_for_hub_asset

register = template.Library()


@register.inclusion_tag("security/partials/asset_it_overview.html", takes_context=True)
def security_asset_it_overview(context, asset, require_link=False):
    request = context.get("request")
    if not can_view_security_center(getattr(request, "user", None)) or not getattr(asset, "pk", None):
        return {"show": False}
    from security.services.asset_overview import overview_for_hub_asset

    linked = asset.security_assets.count()
    if require_link and not linked:
        return {"show": False}
    if linked:
        data = overview_for_hub_asset(asset)
    else:
        from security.services.configuration import can_manage_security_config

        data = {
            "candidates": unlinked_candidates(asset),
            "can_link": can_manage_security_config(getattr(request, "user", None)),
            "asset": asset,
            # Il tag di inclusione non eredita il contesto: serve al form di conferma.
            "csrf_token": context.get("csrf_token"),
        }
    return {"show": True, "linked": linked, **data}


def unlinked_candidates(asset):
    """Dispositivi SOC non collegati che l'abbinatore assegnerebbe proprio a questo asset."""
    from django.db.models import Q

    from security.models import SecurityAsset
    from security.services.asset_signals import suggest_hub_asset

    ips = [ip for ip in asset.endpoints.exclude(ip__isnull=True).exclude(ip="").values_list("ip", flat=True)]
    name = (asset.name or "").strip()
    query = Q(ip_address__in=ips) if ips else Q()
    if name:
        query |= Q(hostname__iexact=name) | Q(hostname__istartswith=f"{name}.")
    if not query:
        return []
    out = []
    for device in SecurityAsset.objects.filter(query, hub_asset__isnull=True).select_related("source")[:5]:
        suggestion, reason = suggest_hub_asset(device)
        if suggestion is not None and suggestion.pk == asset.pk:
            out.append({"device": device, "reason": reason})
    return out


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
