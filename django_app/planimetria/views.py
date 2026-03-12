"""
App Planimetria — alias/reindirizzamento verso le viste già complete di `assets`.

I modelli reali sono:
  assets.PlantLayout        — planimetria PNG
  assets.PlantLayoutArea    — reparti/zone sulla mappa
  assets.PlantLayoutMarker  → assets.Asset (tipo WORK_MACHINE / CNC) — macchine posizionate
Le viste di gestione e il template interattivo sono già in assets.views.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from admin_portale.decorators import legacy_admin_required


@login_required
def mappa(request):
    """Viewer planimetria: redirect alla vista assets esistente."""
    return redirect("assets:plant_layout_map")


@legacy_admin_required
def editor(request):
    """Editor planimetria (admin): redirect alla vista assets esistente."""
    return redirect("assets:plant_layout_editor")
