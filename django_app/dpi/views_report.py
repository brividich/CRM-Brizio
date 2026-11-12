"""Pagine di report: conformita' di tutte le persone e registro delle consegne."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from anagrafica.services import centro_filtro
from core.excel_export import make_xlsx_response
from core.table_pdf import render_table_pdf

from . import report as report_dpi
from .models import CategoriaDPI, RichiestaDPI
from .views import _dipendenti_attivi, _int_or_none, _is_gestore, _scope_report, log_action

RIGHE_PER_PAGINA = 50
FORMATI = ("xlsx", "pdf")


def _categorie():
    return CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome")


def _parametri_pagina(request):
    parametri = request.GET.copy()
    parametri.pop("page", None)
    parametri.pop("export", None)
    return parametri


def _esporta(request, formato: str, *, nome: str, titolo: str, filtri: str, colonne: list, righe: list, azione: str):
    log_action(request, azione, "dpi", {"formato": formato, "righe": len(righe), "filtri": filtri})
    oggi = timezone.localdate()
    if formato == "pdf":
        sottotitolo = f"{filtri} · generato il {oggi:%d-%m-%Y}" if filtri else f"Generato il {oggi:%d-%m-%Y}"
        response = HttpResponse(
            render_table_pdf(title=titolo, headers=colonne, rows=righe, subtitle=sottotitolo), content_type="application/pdf"
        )
        response["Content-Disposition"] = f'attachment; filename="{nome}-{oggi:%Y%m%d}.pdf"'
        return response
    return make_xlsx_response(
        filename=f"{nome}-{oggi:%Y%m%d}.xlsx", columns=colonne, rows=righe, sheet_title=titolo[:31], title=titolo, filters_label=filtri or None,
    )


@login_required
def report_persone(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    q = request.GET.get("q", "").strip()
    reparto = request.GET.get("reparto", "").strip()
    esito = request.GET.get("esito", "").strip()
    if esito not in dict(report_dpi.FILTRI_ESITO):
        esito = ""
    categoria_id = _int_or_none(request.GET.get("categoria_id"))

    tutti = _dipendenti_attivi(request)
    reparti = sorted({str(d.get("reparto") or "").strip() for d in tutti} - {""}, key=str.casefold)
    scelti = tutti
    if q:
        testo = q.casefold()
        scelti = [d for d in scelti if any(testo in str(d.get(k) or "").casefold() for k in ("nominativo", "reparto", "mansione", "matricola"))]
    if reparto:
        scelti = [d for d in scelti if str(d.get("reparto") or "").strip() == reparto]
    filtro_centro = centro_filtro.leggi(request)
    scelti = [d for d in scelti if filtro_centro.contiene(d.get("id"))]

    dati = report_dpi.conformita(scelti, categoria_id=categoria_id)
    persone = report_dpi.filtra_esito(dati["persone"], esito)

    formato = request.GET.get("export", "")
    if formato in FORMATI:
        filtri = " · ".join(x for x in (
            q and f"Ricerca: {q}", reparto and f"Reparto: {reparto}", filtro_centro.etichetta, esito and dict(report_dpi.FILTRI_ESITO)[esito],
        ) if x)
        centri = centro_filtro.centro_per_persona()
        return _esporta(
            request, formato, nome="conformita-dpi", titolo="Conformità DPI delle persone", filtri=filtri,
            colonne=["Persona", "Reparto", "Centro di costo", "Mansione", "Esito", "Da sistemare"],
            righe=[[p["nominativo"], p.get("reparto") or "", centri.get(int(p["id"]), ""), p.get("mansione") or "", p["esito_etichetta"], report_dpi.testo_da_sistemare(p)] for p in persone],
            azione="DPI_CONFORMITA_PERSONE_EXPORT",
        )

    pagina = Paginator(persone, RIGHE_PER_PAGINA).get_page(request.GET.get("page"))
    for p in pagina.object_list:
        p["testo_da_sistemare"] = report_dpi.testo_da_sistemare(p)
    categorie = list(_categorie())
    filtro_kpi = _parametri_pagina(request)
    filtro_kpi.pop("esito", None)
    return render(request, "dpi/pages/report_persone.html", {
        "filtro_centro": filtro_centro, "is_gestore": True, "page_obj": pagina, "conteggi": dati["conteggi"], "errore_requisiti": dati["errore_requisiti"],
        "q": q, "reparto": reparto, "esito": esito, "categoria_id": categoria_id, "reparti": reparti, "categorie": categorie,
        "filtri_esito": report_dpi.FILTRI_ESITO, "querystring": _parametri_pagina(request).urlencode(),
        "querystring_base": filtro_kpi.urlencode(), "nessuna_categoria": not categorie,
    })


def _data(valore: str | None, predefinita: date) -> date:
    try:
        return date.fromisoformat((valore or "").strip())
    except ValueError:
        return predefinita


@login_required
def report_consegne(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")

    fine = _data(request.GET.get("a"), timezone.localdate())
    inizio = _data(request.GET.get("da"), fine - timedelta(days=90))
    q = request.GET.get("q", "").strip()
    reparto = request.GET.get("reparto", "").strip()
    categoria_id = _int_or_none(request.GET.get("categoria_id"))
    etichette = dict(report_dpi.FILTRI_RICEVUTA)
    ricevuta = request.GET.get("ricevuta", "").strip()
    if ricevuta not in etichette:
        ricevuta = ""

    scope = _scope_report(request)
    filtro_centro = centro_filtro.leggi(request)
    qs, totali, conteggi = report_dpi.consegne(
        da=inizio, a=fine, scope=scope, reparto=reparto, categoria_id=categoria_id, q=q, esito_ricevuta=ricevuta,
        filtro_centro=filtro_centro,
    )

    formato = request.GET.get("export", "")
    if formato in FORMATI:
        filtri = " · ".join(x for x in (
            f"Dal {inizio:%d-%m-%Y} al {fine:%d-%m-%Y}", q and f"Ricerca: {q}", reparto and f"Reparto: {reparto}", filtro_centro.etichetta, ricevuta and etichette[ricevuta],
        ) if x)
        centri = centro_filtro.centro_per_persona()
        righe = [[
            f"{c.data_consegna:%d-%m-%Y}", c.richiesta.numero, c.richiesta.richiedente_nome, c.richiesta.richiedente_reparto,
            centri.get(c.richiesta.richiedente_legacy_id, ""),
            c.richiesta.categoria.nome, report_dpi.descrizione_dpi(c.richiesta), c.richiesta.quantita, c.consegnato_da_nome,
            etichette[report_dpi.ricevuta(c)], f"{c.data_scadenza_stimata:%d-%m-%Y}" if c.data_scadenza_stimata else "",
        ] for c in qs]
        return _esporta(
            request, formato, nome="registro-consegne-dpi", titolo="Registro consegne DPI", filtri=filtri,
            colonne=["Data", "Richiesta", "Persona", "Reparto", "Centro di costo", "Categoria", "DPI", "Pezzi", "Consegnato da", "Ricevuta", "Scadenza"],
            righe=righe, azione="DPI_REGISTRO_CONSEGNE_EXPORT",
        )

    pagina = Paginator(qs, RIGHE_PER_PAGINA).get_page(request.GET.get("page"))
    for c in pagina.object_list:
        c.ricevuta_chiave = report_dpi.ricevuta(c)
        c.ricevuta_etichetta = etichette[c.ricevuta_chiave]
        c.dpi_descrizione = report_dpi.descrizione_dpi(c.richiesta)
    reparti_qs = RichiestaDPI.objects.exclude(richiedente_reparto="")
    if scope is not None:
        reparti_qs = reparti_qs.filter(richiedente_legacy_id__in=list(scope))
    filtro_kpi = _parametri_pagina(request)
    filtro_kpi.pop("ricevuta", None)
    return render(request, "dpi/pages/report_consegne.html", {
        "filtro_centro": filtro_centro, "is_gestore": True, "page_obj": pagina, "totali": totali,
        "stati_ricevuta": [{"chiave": k, "etichetta": v, "n": conteggi[k]} for k, v in report_dpi.FILTRI_RICEVUTA],
        "da": inizio, "a": fine, "q": q, "reparto": reparto, "categoria_id": categoria_id, "ricevuta": ricevuta,
        "reparti": sorted(set(reparti_qs.values_list("richiedente_reparto", flat=True)), key=str.casefold),
        "categorie": _categorie(), "querystring": _parametri_pagina(request).urlencode(), "querystring_base": filtro_kpi.urlencode(),
    })
