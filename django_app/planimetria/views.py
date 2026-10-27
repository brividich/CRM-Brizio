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


@login_required
def mappa(request):
    """Viewer planimetria: redirect alla vista assets esistente."""
    return redirect("assets:plant_layout_map")


@login_required
def editor(request):
    """Editor planimetria: redirect alla vista assets esistente.

    Nessun permesso proprio: decide quello dell'editor di Asset (la pagina di
    arrivo), così non esistono due permessi diversi per la stessa pagina."""
    return redirect("assets:plant_layout_editor")
