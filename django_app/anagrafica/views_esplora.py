"""«Esplora la struttura» (05/11/2026): centro di costo → reparto → ruolo → mansione → competenza.

Sola lettura. Vede chi vede la Struttura organizzativa (amministrazione anagrafica o
dati HR): la pagina elenca le persone. Le strade verso costo orario e report compaiono
solo a chi ha quei permessi; decidono comunque le pagine di destinazione.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from .services import esplora_struttura as svc
from .views_mansionario import _nega, _puo_vedere


def _con_filtro(nome_rotta: str, **parametri) -> str:
    return f"{reverse(nome_rotta)}?{urlencode(parametri)}"


def _strade(request, ctx: dict) -> list[dict]:
    """Le altre pagine del portale sul punto scelto, già filtrate quando la pagina lo permette."""
    from .models import ReportModello
    from .reportistica.permessi import can_view
    from .views import _check_hr_permission

    strade = []
    centro, area, ruolo, mansione, voce = (ctx["centro_obj"], ctx["area_obj"], ctx["ruolo_obj"], ctx["mansione_obj"],
                                           ctx["voce_obj"])
    if voce is not None:
        strade.append({"nome": "Catalogo competenze", "url": reverse("anagrafica:mansionario_catalogo"),
                       "sotto": "chi usa questa competenza, rinomina e unione"})
    if mansione is not None:
        strade.append({"nome": "Mansionario della mansione",
                       "url": reverse("anagrafica:mansionario_mansione", args=[mansione.pk]),
                       "sotto": "persone, livelli e valutazioni"})
        strade.append({"nome": "Modifica nella struttura",
                       "url": reverse("anagrafica:mansionario_struttura_mansione", args=[mansione.pk]),
                       "sotto": "ruoli, rischi e competenze"})
    if ruolo is not None:
        strade.append({"nome": "Scheda completa del ruolo",
                       "url": reverse("anagrafica:struttura_org") + f"#scheda-ruolo-{ruolo.pk}",
                       "sotto": "persone, processi e accessi in tutta l'azienda"})
    if area is not None:
        strade.append({"nome": "Capi del reparto", "url": reverse("anagrafica:aree_list") + f"#area-{area.pk}",
                       "sotto": "responsabile e ruolo responsabile"})
        strade.append({"nome": "Persone del reparto",
                       "url": _con_filtro("anagrafica:dipendenti_report", area=area.nome),
                       "sotto": "Report dipendenti filtrato"})
    if centro is not None:
        strade.append({"nome": "Persone del centro di costo",
                       "url": _con_filtro("anagrafica:dipendenti_report", centro_costo=centro.nome),
                       "sotto": "Report dipendenti filtrato"})
        if _check_hr_permission(request):
            strade.append({"nome": "Costo orario del centro",
                           "url": _con_filtro("anagrafica:costo_orario", centro_costo=centro.nome),
                           "sotto": "dipendenti e RML del mese"})
        strade.append({"nome": "Gestisci il centro di costo",
                       "url": reverse("anagrafica:centri_costo") + f"#cc-{centro.pk}", "sotto": "reparti e ruoli previsti"})
    if not (centro or area or ruolo or mansione):
        strade.append({"nome": "Centri di costo", "url": reverse("anagrafica:centri_costo"), "sotto": "collega i reparti"})
        strade.append({"nome": "Struttura organizzativa", "url": reverse("anagrafica:struttura_org"), "sotto": "revisioni e rischi"})
        strade.append({"nome": "Mansionario", "url": reverse("anagrafica:mansionario"), "sotto": "persone e valutazioni"})
    strade.append({"nome": "Prova un cambiamento", "url": reverse("anagrafica:prospetti"),
                   "sotto": "confronto oggi e dopo, prima di cambiare"})
    if can_view(request):
        modello = ReportModello.objects.filter(codice_sistema="centri_costo", is_active=True).first()
        if modello is not None:
            strade.append({"nome": "Report per centro di costo",
                           "url": reverse("anagrafica:reportistica_genera", args=[modello.pk]),
                           "sotto": "organico e costo orario, in Excel"})
    return strade


@login_required
def esplora_struttura(request):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alla struttura organizzativa.")
    from .views import _check_hr_permission

    ctx = svc.costruisci(request.GET, riservati=_check_hr_permission(request))
    testo = " ".join((request.GET.get("q") or "").split())
    risultati = svc.cerca(ctx["dati"], testo) if len(testo) >= 2 else None
    ctx.update({"page_title": "Esplora la struttura", "q": testo, "risultati": risultati, "strade": _strade(request, ctx)})
    ctx.pop("dati")
    # Nella pagina già aperta si cambia solo la parte viva: niente menu da ricaricare.
    if request.GET.get("parziale") == "1":
        return render(request, "anagrafica/partials/_esplora_vivo.html", ctx)
    return render(request, "anagrafica/pages/esplora_struttura.html", ctx)
