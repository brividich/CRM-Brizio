"""Stanza «Sapere»: indice dei cataloghi, pagina di un catalogo, copertine.

Rotte condivise (``core/middleware._ACL_SHARED_ROUTE_NAMES``): aperte a chi ha
fatto l'accesso, la visibilità di cataloghi e voci è filtrata qui per ruolo
(``core.sapere``). Le copertine passano solo da ``sapere_copertina``, che
applica le stesse regole del catalogo o della risorsa a cui appartengono.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from core import sapere
from core.hub_bacheca import link_visible_to_role
from core.models import Catalogo, CatalogoVoce, HubLink


@login_required
@require_GET
def sapere_cataloghi(request):
    ident = sapere.identita(request)
    cataloghi = sapere.schede_cataloghi(ident)
    try:
        from procedure_refresh.libreria import catalogo_sapere, puo_aprire_libreria

        if puo_aprire_libreria(request):
            cataloghi = [catalogo_sapere(), *cataloghi]
    except Exception:
        pass
    return render(request, "dashboard/pages/sapere_cataloghi.html", {
        "page_title": "Cataloghi",
        "cataloghi": cataloghi,
        "is_admin": ident.is_admin,
    })


@login_required
@require_GET
def sapere_catalogo(request, slug: str):
    ident = sapere.identita(request)
    catalogo = get_object_or_404(Catalogo.objects.prefetch_related("role_accesses"), slug=slug)
    if not sapere.catalogo_visibile(catalogo, ident):
        raise Http404("Catalogo non trovato")
    altri = [c for c in sapere.schede_cataloghi(ident) if c["id"] != catalogo.pk]
    return render(request, "dashboard/pages/sapere_catalogo.html", {
        "page_title": catalogo.titolo,
        "catalogo": sapere.scheda_catalogo(catalogo, ident, con_voci=True),
        "altri_cataloghi": altri,
        "is_admin": ident.is_admin,
    })


def _oggetto_copertina(tipo: str, pk: int, ident):
    """Oggetto con la copertina richiesta, se l'utente può vederlo; altrimenti None."""
    if tipo == "risorsa":
        link = get_object_or_404(HubLink.objects.prefetch_related("role_accesses"), pk=pk)
        return link if (ident.is_admin or link_visible_to_role(link, ident.role_id, False)) else None
    if tipo == "catalogo":
        cat = get_object_or_404(Catalogo.objects.prefetch_related("role_accesses"), pk=pk)
        return cat if (ident.is_admin or sapere.catalogo_visibile(cat, ident)) else None
    if tipo == "voce":
        voce = get_object_or_404(CatalogoVoce.objects.select_related("catalogo"), pk=pk)
        return voce if (ident.is_admin or sapere.catalogo_visibile(voce.catalogo, ident)) else None
    return None


@login_required
@require_GET
def sapere_copertina(request, tipo: str, pk: int):
    ident = sapere.identita(request)
    obj = _oggetto_copertina(tipo, pk, ident)
    if obj is None or not obj.copertina:
        raise Http404()
    risposta = FileResponse(obj.copertina.open("rb"), content_type="image/jpeg")
    risposta["Cache-Control"] = "private, max-age=86400"
    risposta["X-Content-Type-Options"] = "nosniff"
    return risposta
