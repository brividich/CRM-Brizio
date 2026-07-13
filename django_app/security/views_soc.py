"""Viste aggiuntive dell'innesto SOC IT - CN (non presenti nell'app SC-AI originale).

Tenute separate dal grande `views.py` di SC-AI per isolamento dell'innesto.
"""
from django.shortcuts import render

from security.models import SecurityAsset


def assets_list(request):
    """Elenco dei SecurityAsset con l'eventuale Asset HUB collegato (fase D2)."""
    assets = (
        SecurityAsset.objects.select_related("source", "hub_asset").order_by("hostname")
    )
    n_tot = assets.count()
    n_linked = assets.exclude(hub_asset__isnull=True).count()
    return render(
        request,
        "security/soc_assets.html",
        {"assets": assets, "n_tot": n_tot, "n_linked": n_linked},
    )
