"""Centro guide: indice di tutte le guide e pagina guida di un modulo.

Aperte a chi ha fatto l'accesso (rotte condivise in ``core/middleware.py``):
il contenuto non ha dati personali. Le parti per amministratori («Amministratore
e configurazione», «Se qualcosa non va» e le guide ``solo_admin``) si vedono solo
con ``puo_vedere_admin``; per gli altri la rotta risponde 403.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from core import guide_moduli


def _url_sicuro(nome: str, query: str = "") -> str:
    """Nome di rotta → indirizzo; un indirizzo che inizia con «/» resta com'è."""
    if nome.startswith("/"):
        return nome + query
    try:
        return reverse(nome) + query
    except NoReverseMatch:
        return ""


@login_required
@require_GET
def guide_indice(request):
    admin = guide_moduli.puo_vedere_admin(request)
    aree = []
    for area, elenco in guide_moduli.per_area():
        visibili = [g for g in elenco if admin or not g["solo_admin"]]
        if visibili:
            aree.append((area, [dict(g, url_modulo=_url_sicuro(g["url"])) for g in visibili]))
    return render(request, "core/pages/guide_indice.html", {
        "aree": aree,
        "is_admin_guide": admin,
        "totale": sum(len(elenco) for _area, elenco in aree),
    })


@login_required
@require_GET
def guida_modulo(request, slug: str):
    guida = guide_moduli.per_slug(slug)
    if guida is None:
        raise Http404("Guida non trovata")
    admin = guide_moduli.puo_vedere_admin(request)
    if guida["solo_admin"] and not admin:
        raise PermissionDenied("Guida riservata agli amministratori del portale.")

    viste = [(chiave, etichetta) for chiave, etichetta in guide_moduli.VISTE
             if chiave == "uso" or (admin and not guida["solo_admin"] and guida[chiave])]
    vista = request.GET.get("vista", "uso")
    if vista not in dict(viste):
        if vista in ("admin", "problemi") and not admin:
            raise PermissionDenied("Questa parte della guida è riservata agli amministratori del portale.")
        vista = "uso"
    sezioni = guide_moduli.capitoli(guida, vista)
    etichetta_vista = "Indice" if guida["solo_admin"] else dict(guide_moduli.VISTE)[vista]

    if request.GET.get("pdf") == "1":
        from core.guida_pdf import render_guida_pdf

        pdf = render_guida_pdf(
            titolo=f"{guida['titolo']} · {etichetta_vista}",
            sottotitolo=guida["sintesi"],
            sezioni=sezioni,
            generato_da=request.user.get_full_name() or request.user.get_username(),
            generato_il=timezone.localtime().strftime("%d/%m/%Y %H:%M"),
        )
        risposta = HttpResponse(pdf, content_type="application/pdf")
        risposta["Content-Disposition"] = f'inline; filename="guida-{guida["slug"]}-{vista}.pdf"'
        return risposta

    dettaglio = []
    for etichetta, nome, *query in guida["dettaglio"]:
        url = _url_sicuro(nome, query[0] if query else "")
        if url:
            dettaglio.append((etichetta, url))
    return render(request, "core/pages/guida_modulo.html", {
        "guida": guida,
        "sezioni": sezioni,
        "vista": vista,
        "etichetta_vista": etichetta_vista,
        "viste": viste,
        "url_modulo": _url_sicuro(guida["url"]),
        "dettaglio": dettaglio,
        "is_admin_guide": admin,
    })
