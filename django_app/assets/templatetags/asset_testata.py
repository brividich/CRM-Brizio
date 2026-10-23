"""Testata dell'asset uguale in Asset, Contatori e SOC: chi è, com'è messo e dove si vede.

``{% load asset_testata %}{% asset_testata asset "contatori" %}``: identità dell'asset, i riquadri
del cruscotto (``asset_kpis.device_kpis``, gli stessi della scheda asset) e i collegamenti alle
altre pagine dello stesso apparato. Il secondo argomento è il modulo che la mostra: il suo
collegamento non compare. Sola lettura, nessuna interrogazione agli apparati.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from django import template
from django.urls import reverse

register = template.Library()
logger = logging.getLogger(__name__)

SIGLE = {"printer": "STA", "network": "NET", "workstation": "PC", "server": "SRV", "vm": "VM", "generic": "IT"}


def _collegamenti(request, asset, modulo):
    from assets.services.it_coverage import can_view_snmp, can_view_soc

    out = []
    if modulo != "assets":
        out.append({"label": "Scheda asset", "url": reverse("assets:asset_view", args=[asset.pk]), "modulo": "assets"})
    if modulo != "contatori" and can_view_snmp(request):
        from contatori.models import DispositivoSNMP, Macchina

        mfc = Macchina.objects.filter(asset=asset).only("pk").first()
        disp = None if mfc else DispositivoSNMP.objects.filter(asset=asset).only("pk").first()
        if mfc:
            out.append({"label": "Stampante MFC", "url": reverse("contatori:macchina", args=[mfc.pk]), "modulo": "contatori"})
        elif disp:
            out.append({"label": "Monitoraggio", "url": reverse("contatori:snmp_dispositivo", args=[disp.pk]), "modulo": "contatori"})
    if modulo != "security" and can_view_soc(request):
        nome = asset.security_assets.values_list("hostname", flat=True).first()
        if not nome:
            from assets.models import DispositivoIntune

            nome = DispositivoIntune.objects.filter(asset=asset, presente=True).values_list("nome", flat=True).first()
        if nome:
            out.append({"label": "Sicurezza (SOC)", "url": reverse("security:pc_detail") + "?" + urlencode({"nome": nome}),
                        "modulo": "security"})
    return out


@register.inclusion_tag("assets/partials/asset_testata.html", takes_context=True)
def asset_testata(context, asset, modulo=""):
    request = context.get("request")
    if asset is None or request is None:
        return {"asset": None}
    from assets.services.asset_kpis import device_kpis

    url = reverse("assets:asset_view", args=[asset.pk])
    try:
        kpis = device_kpis(request, asset)
        collegamenti = _collegamenti(request, asset, modulo)
    except Exception:  # noqa: BLE001 - la testata non deve mai rompere la pagina che la ospita
        logger.exception("Testata asset %s non calcolata", asset.pk)
        kpis, collegamenti = None, []
    tiles = []
    for tile in (kpis or {}).get("tiles", []):
        href = tile.get("href") or ""
        # Le ancore dei riquadri sono della scheda asset: fuori da lì portano alla scheda.
        tiles.append({**tile, "href": url + href if href.startswith("#") and modulo != "assets" else href})
    profilo = (kpis or {}).get("profile", "")
    fatti = [f for f in (
        ("Categoria", getattr(asset.asset_category, "name", "") if asset.asset_category_id else asset.get_asset_type_display()),
        ("Reparto", asset.reparto),
        ("Modello", " ".join(x for x in (asset.manufacturer, asset.model) if x)),
        ("Seriale", asset.serial_number or ""),
    ) if f[1]]
    return {
        "asset": asset, "url": url, "tiles": tiles, "titolo_kpi": (kpis or {}).get("title", ""),
        "sigla": SIGLE.get(profilo, "IT"), "fatti": fatti,
        "collegamenti": collegamenti, "modulo": modulo,
    }


@register.inclusion_tag("assets/partials/asset_altri_moduli.html", takes_context=True)
def asset_altri_moduli(context, asset):
    """Solo i collegamenti allo stesso apparato in Contatori e SOC (per la scheda asset, che ha già la sua testata)."""
    request = context.get("request")
    try:
        collegamenti = _collegamenti(request, asset, "assets") if asset is not None and request is not None else []
    except Exception:  # noqa: BLE001
        logger.exception("Collegamenti dell'asset %s non calcolati", getattr(asset, "pk", None))
        collegamenti = []
    return {"collegamenti": collegamenti}
