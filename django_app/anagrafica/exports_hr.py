"""Export tabellari delle liste «Cataloghi / HR» di anagrafica.

Le spec sono registrate all'import del modulo (vedi `anagrafica/exports.py`).

Copertura:
- ``aree`` / ``reparti``     → pagina «Aree & Reparti» (`/anagrafica/aree/`)
- ``ruoli_aziendali``        → `/anagrafica/ruoli-aziendali/`
- ``ruoli_operativi``        → `/anagrafica/ruoli-operativi/`
- ``ratei``                  → `/anagrafica/ratei/`
- ``retribuzioni_globale``   → `/anagrafica/retribuzioni/globale/`
- ``visite_mediche`` / ``visite_mediche_copertura`` → `/anagrafica/visite-mediche/`

Privacy/GDPR: ratei, retribuzioni e visite mediche sono dati sensibili. Oltre al
gate ACL sul path della lista (chi non vede la lista non esporta) le tre spec
riusano lo *stesso* controllo applicativo delle rispettive view
(`_check_hr_permission` / `_can_view_visite_mediche`). Le colonne esportate sono
solo quelle già visibili a schermo: per le visite mediche NON vengono esportati
esito/giudizio di idoneità né prescrizioni.

Gli export XLSX dedicati già esistenti (`ratei_export`,
`retribuzioni_globale_export`, `visite_mediche_export_scadenze/copertura`)
restano invariati: qui si riusa la stessa logica di filtri/query per non far
divergere i due canali.
"""
from __future__ import annotations

from typing import Callable

from django.http import HttpRequest

from anagrafica.exports import ExportSpec, acl_gate, register  # noqa: F401


# ── Helper condivisi ─────────────────────────────────────────────────────────

def _hr_gate(list_path: str) -> Callable[[HttpRequest], bool]:
    """ACL della lista + permesso HR applicativo (dati retributivi riservati)."""
    acl = acl_gate(list_path)

    def _check(request: HttpRequest) -> bool:
        from anagrafica.views import _check_hr_permission

        if not acl(request):
            return False
        return bool(_check_hr_permission(request))

    return _check


def _visite_gate() -> Callable[[HttpRequest], bool]:
    """ACL della dashboard + permesso applicativo sulle visite mediche."""
    acl = acl_gate("/anagrafica/visite-mediche/")

    def _check(request: HttpRequest) -> bool:
        from anagrafica.views import _can_view_visite_mediche

        if not acl(request):
            return False
        return bool(_can_view_visite_mediche(request))

    return _check


def _nomi_legacy(legacy_ids=None) -> dict:
    """{legacy_anagrafica_id: 'Cognome Nome'} dall'anagrafica legacy."""
    from core.legacy_models import AnagraficaDipendente

    nomi: dict = {}
    try:
        qs = AnagraficaDipendente.objects.values("id", "cognome", "nome")
        if legacy_ids is not None:
            qs = qs.filter(id__in=list(legacy_ids))
        for row in qs:
            try:
                lid = int(row.get("id") or 0)
            except (TypeError, ValueError):
                continue
            nome = f'{(row.get("cognome") or "").strip()} {(row.get("nome") or "").strip()}'.strip()
            if lid:
                nomi[lid] = nome or f"#{lid}"
    except Exception:  # tabella legacy non raggiungibile → si degrada a vuoto
        return {}
    return nomi


def _si_no(value) -> str:
    return "Si" if value else "No"


# ── Aree aziendali (pagina «Aree & Reparti») ─────────────────────────────────
# La pagina non ha filtri in querystring: `filtered` == `full`.

def _aree_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import AreaAziendale

    aree = list(
        AreaAziendale.objects.select_related("reparto").order_by("reparto__nome", "nome")
    )
    responsabili = _nomi_legacy({a.responsabile_legacy_id for a in aree if a.responsabile_legacy_id})

    rows: list[dict] = []
    for area in aree:
        rows.append({
            "nome": area.nome or "",
            "reparto": area.reparto.nome if area.reparto_id else "",
            "descrizione": area.descrizione or "",
            "responsabile": responsabili.get(area.responsabile_legacy_id or 0, ""),
            "stato": "Attivo" if area.is_active else "Inattivo",
        })
    return rows


register(ExportSpec(
    key="aree",
    title="Aree aziendali",
    sheet_title="Aree aziendali",
    columns=[
        ("Area aziendale", "nome"),
        ("Reparto", "reparto"),
        ("Descrizione", "descrizione"),
        ("Responsabile", "responsabile"),
        ("Stato", "stato"),
    ],
    dataset=_aree_rows,
    permission=acl_gate("/anagrafica/aree/"),
))


# ── Reparti (stessa pagina, livello padre della gerarchia) ───────────────────

def _reparti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import Reparto

    reparti = list(Reparto.objects.prefetch_related("aree_aziendali").order_by("nome"))
    capi = _nomi_legacy({r.caporeparto_legacy_id for r in reparti if r.caporeparto_legacy_id})

    rows: list[dict] = []
    for rep in reparti:
        aree = list(rep.aree_aziendali.all())
        rows.append({
            "nome": rep.nome or "",
            "descrizione": rep.descrizione or "",
            "caporeparto": capi.get(rep.caporeparto_legacy_id or 0, ""),
            "aree": ", ".join(a.nome for a in sorted(aree, key=lambda x: x.nome or "")),
            "n_aree": len(aree),
            "stato": "Attivo" if rep.is_active else "Inattivo",
        })
    return rows


register(ExportSpec(
    key="reparti",
    title="Reparti",
    sheet_title="Reparti",
    columns=[
        ("Reparto", "nome"),
        ("Descrizione", "descrizione"),
        ("Caporeparto", "caporeparto"),
        ("Aree aziendali", "aree"),
        ("N. aree", "n_aree"),
        ("Stato", "stato"),
    ],
    dataset=_reparti_rows,
    permission=acl_gate("/anagrafica/aree/"),
))


# ── Ruoli aziendali (catalogo) ───────────────────────────────────────────────

def _ruoli_aziendali_rows(request: HttpRequest, scope: str) -> list[dict]:
    # Catalogo unico: anche l'export legacy legge i Ruoli, non più la tabella
    # `RuoloAziendale` congelata alla migration 0085.
    from anagrafica.models import RuoloOperativo

    return [
        {
            "nome": r.nome or "",
            "descrizione": r.descrizione or "",
            "stato": "Attivo" if r.is_active else "Inattivo",
        }
        for r in RuoloOperativo.objects.all().order_by("nome")
    ]


register(ExportSpec(
    key="ruoli_aziendali",
    title="Catalogo ruoli aziendali",
    sheet_title="Ruoli aziendali",
    columns=[
        ("Nome", "nome"),
        ("Descrizione", "descrizione"),
        ("Stato", "stato"),
    ],
    dataset=_ruoli_aziendali_rows,
    permission=acl_gate("/anagrafica/ruoli-aziendali/"),
))


# ── Ruoli operativi (catalogo, con n. assegnazioni) ──────────────────────────

def _ruoli_operativi_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import RuoloOperativo

    return [
        {
            "nome": r.nome or "",
            "descrizione": r.descrizione or "",
            "n_assegnati": r.n_assegnati,
            "stato": "Attivo" if r.is_active else "Inattivo",
        }
        for r in RuoloOperativo.objects.annotate(n_assegnati=Count("assegnazioni")).order_by("nome")
    ]


register(ExportSpec(
    key="ruoli_operativi",
    title="Catalogo ruoli operativi",
    sheet_title="Ruoli operativi",
    columns=[
        ("Ruolo", "nome"),
        ("Descrizione", "descrizione"),
        ("Dipendenti assegnati", "n_assegnati"),
        ("Stato", "stato"),
    ],
    dataset=_ruoli_operativi_rows,
    permission=acl_gate("/anagrafica/ruoli-operativi/"),
))


# ── Ratei ferie/ROL/ex-festività ─────────────────────────────────────────────
# Filtri replicati da `views.ratei_list` / `views.ratei_export`:
#   ?periodo=YYYY-MM-DD · ?dipendente=<CF> (multi, con compat ?cf=) ·
#   ?reparto=<nome> (multi) · ?allerta=1

def _ratei_maps() -> tuple[dict, dict, dict]:
    """(cf → nome, cf → reparto, legacy_id → reparto), stessa risoluzione della view."""
    from anagrafica.models import (
        DipendenteAnagraficaAziendale,
        DipendenteAnagraficaCivile,
        SaldoCedolino,
    )

    cf_civile_legacy: dict = {}
    for c in DipendenteAnagraficaCivile.objects.exclude(codice_fiscale="").values(
        "codice_fiscale", "legacy_anagrafica_id"
    ):
        cf_u = (c["codice_fiscale"] or "").strip().upper()
        if cf_u:
            cf_civile_legacy[cf_u] = c["legacy_anagrafica_id"]

    cf_to_legacy: dict = {}
    for row in SaldoCedolino.objects.values("tax_code", "legacy_anagrafica_id").distinct():
        cf = (row["tax_code"] or "").strip()
        if not cf or cf in cf_to_legacy:
            continue
        cf_to_legacy[cf] = row["legacy_anagrafica_id"] or cf_civile_legacy.get(cf.upper())

    legacy_ids = sorted({lid for lid in cf_to_legacy.values() if lid})
    id_to_nome = _nomi_legacy(legacy_ids)

    # Reparto: AnagraficaDipendente.reparto → fallback DipendenteAnagraficaAziendale.area
    id_to_reparto: dict = {}
    try:
        from core.legacy_models import AnagraficaDipendente

        id_to_reparto = {
            d["id"]: (d["reparto"] or "").strip()
            for d in AnagraficaDipendente.objects.filter(id__in=legacy_ids).values("id", "reparto")
        }
    except Exception:
        id_to_reparto = {}
    for lid, area in (
        DipendenteAnagraficaAziendale.objects
        .filter(legacy_anagrafica_id__in=legacy_ids)
        .exclude(area="")
        .values_list("legacy_anagrafica_id", "area")
    ):
        if not id_to_reparto.get(lid):
            id_to_reparto[lid] = (area or "").strip()

    cf_to_nome: dict = {}
    cf_to_reparto: dict = {}
    for cf, lid in cf_to_legacy.items():
        cf_to_nome[cf.upper()] = (id_to_nome.get(lid) if lid else None) or cf
        cf_to_reparto[cf.upper()] = id_to_reparto.get(lid, "") if lid else ""
    return cf_to_nome, cf_to_reparto, id_to_reparto


def _ratei_filtri(request: HttpRequest) -> dict:
    filtro_dipendenti = request.GET.getlist("dipendente")
    if not filtro_dipendenti:
        cf_compat = (request.GET.get("cf") or "").strip().upper()
        if cf_compat:
            filtro_dipendenti = [cf_compat]
    return {
        "periodo": request.GET.get("periodo", ""),
        "dipendenti": filtro_dipendenti,
        "reparti": request.GET.getlist("reparto"),
        "allerta": request.GET.get("allerta", "") == "1",
    }


def _ratei_rows(request: HttpRequest, scope: str) -> list[dict]:
    from datetime import date as _date

    from anagrafica.models import SaldoCedolino
    from anagrafica.ratei_alert import filtro_allerta_q, soglie_ratei

    cf_to_nome, cf_to_reparto, id_to_reparto = _ratei_maps()
    qs = SaldoCedolino.objects.all().order_by("-data_competenza", "tax_code")

    if scope == "filtered":
        f = _ratei_filtri(request)
        if f["periodo"]:
            try:
                anno, mese, giorno = f["periodo"].split("-")
                qs = qs.filter(data_competenza=_date(int(anno), int(mese), int(giorno)))
            except (ValueError, AttributeError):
                pass
        if f["reparti"]:
            # Stesso criterio della view: filtro sui legacy_anagrafica_id del reparto.
            ids_in_reparto = [lid for lid, rep in id_to_reparto.items() if rep in f["reparti"]]
            qs = qs.filter(legacy_anagrafica_id__in=ids_in_reparto)
        if f["dipendenti"]:
            qs = qs.filter(tax_code__in=f["dipendenti"])
        if f["allerta"]:
            qs = qs.filter(filtro_allerta_q(soglie_ratei()))

    rows: list[dict] = []
    for s in qs:
        cf_u = (s.tax_code or "").upper()
        if s.anzianita_anni is not None:
            anz = f"{s.anzianita_anni}a"
            if s.anzianita_mesi:
                anz += f" {s.anzianita_mesi}m"
        else:
            anz = ""
        rows.append({
            "dipendente": cf_to_nome.get(cf_u, s.tax_code or ""),
            "reparto": cf_to_reparto.get(cf_u, ""),
            "periodo": s.data_competenza.strftime("%m-%Y") if s.data_competenza else "",
            "anzianita": anz,
            "ferie_anni_prec": s.ferie_anni_prec,
            "ferie_maturati": s.ferie_maturati,
            "ferie_goduti": s.ferie_goduti,
            "ferie_residui": s.ferie_residui,
            "rol_anni_prec": s.rol_anni_prec,
            "rol_maturati": s.rol_maturati,
            "rol_goduti": s.rol_goduti,
            "rol_residui": s.rol_residui,
            "ex_fest_anni_prec": s.ex_fest_anni_prec,
            "ex_fest_maturati": s.ex_fest_maturati,
            "ex_fest_goduti": s.ex_fest_goduti,
            "ex_fest_residui": s.ex_fest_residui,
        })
    return rows


def _ratei_filters(request: HttpRequest) -> str:
    f = _ratei_filtri(request)
    parts: list[str] = []
    if f["periodo"]:
        parts.append(f"Periodo: {f['periodo']}")
    if f["dipendenti"]:
        parts.append(f"Dipendenti: {len(f['dipendenti'])} selezionati")
    if f["reparti"]:
        parts.append("Reparti: " + ", ".join(f["reparti"]))
    if f["allerta"]:
        parts.append("Solo allerta ferie")
    return " · ".join(parts)


register(ExportSpec(
    key="ratei",
    title="Ratei ferie / ROL / ex-festività",
    sheet_title="Ratei",
    columns=[
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Periodo", "periodo"),
        ("Anzianità", "anzianita"),
        ("Ferie anni prec.", "ferie_anni_prec"),
        ("Ferie maturate", "ferie_maturati"),
        ("Ferie godute", "ferie_goduti"),
        ("Ferie residue", "ferie_residui"),
        ("ROL anni prec.", "rol_anni_prec"),
        ("ROL maturati", "rol_maturati"),
        ("ROL goduti", "rol_goduti"),
        ("ROL residui", "rol_residui"),
        ("Ex-fest. anni prec.", "ex_fest_anni_prec"),
        ("Ex-fest. maturate", "ex_fest_maturati"),
        ("Ex-fest. godute", "ex_fest_goduti"),
        ("Ex-fest. residue", "ex_fest_residui"),
    ],
    dataset=_ratei_rows,
    filters_label=_ratei_filters,
    permission=_hr_gate("/anagrafica/ratei/"),
))


# ── Retribuzioni — vista globale ─────────────────────────────────────────────
# Riusa `views._retribuzioni_globale_context` / `_retribuzioni_globale_rows`, cioè
# esattamente la pipeline della pagina e del suo export XLSX (filtri: dipendente
# multi, reparto multi, sesso, livello multi, periodo).
# La tabella a schermo è un pivot con colonne dinamiche (una per voce
# retributiva): l'ExportSpec ha colonne statiche, quindi le stesse celle sono
# emesse in formato lungo (una riga per dipendente+mese+voce valorizzata).

def _retribuzioni_request(request: HttpRequest, scope: str):
    if scope == "full":
        from types import SimpleNamespace

        from django.http import QueryDict

        return SimpleNamespace(GET=QueryDict())
    return request


def _retribuzioni_globale_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import VoceRetributiva
    from anagrafica.views import (
        _retribuzioni_globale_context,
        _retribuzioni_globale_rows as _pivot_rows,
    )

    req = _retribuzioni_request(request, scope)
    ctx = _retribuzioni_globale_context(req)
    pivot = _pivot_rows(ctx, ctx["group_rows"])
    colonne = ctx["colonne"]
    cat_labels = dict(VoceRetributiva.CATEGORIA_CHOICES)

    rows: list[dict] = []
    for r in pivot:
        periodo = r["data_competenza"].strftime("%m-%Y") if r["data_competenza"] else ""
        for col, cella in zip(colonne, r["celle"]):
            if cella["importo"] is None:
                continue
            rows.append({
                "dipendente": r["nome"],
                "periodo": periodo,
                "reparto": r["reparto"],
                "livello": r["livello"],
                "sesso": r["sesso"],
                "categoria": cat_labels.get(col["categoria"], col["categoria"]),
                "voce": col["label"],
                "importo": cella["importo"],
            })
    return rows


def _retribuzioni_globale_filters(request: HttpRequest) -> str:
    parts: list[str] = []
    dipendenti = [c for c in request.GET.getlist("dipendente") if c.strip()]
    reparti = request.GET.getlist("reparto")
    sesso = (request.GET.get("sesso") or "").strip()
    livelli = [v.strip() for v in request.GET.getlist("livello") if v.strip()]
    periodo = request.GET.get("periodo", "")
    if periodo:
        parts.append(f"Periodo: {periodo}")
    if dipendenti:
        parts.append(f"Dipendenti: {len(dipendenti)} selezionati")
    if reparti:
        parts.append("Reparti: " + ", ".join(reparti))
    if sesso:
        parts.append(f"Sesso: {sesso}")
    if livelli:
        parts.append("Livelli: " + ", ".join(livelli))
    return " · ".join(parts)


register(ExportSpec(
    key="retribuzioni_globale",
    title="Retribuzioni — vista globale",
    sheet_title="Retribuzioni",
    columns=[
        ("Dipendente", "dipendente"),
        ("Periodo", "periodo"),
        ("Reparto", "reparto"),
        ("Livello", "livello"),
        ("Sesso", "sesso"),
        ("Categoria", "categoria"),
        ("Voce retributiva", "voce"),
        ("Importo", "importo"),
    ],
    dataset=_retribuzioni_globale_rows,
    filters_label=_retribuzioni_globale_filters,
    permission=_hr_gate("/anagrafica/retribuzioni/globale/"),
))


# ── Visite mediche — scadute / in scadenza ───────────────────────────────────
# Filtro replicato da `views.visite_mediche_dashboard`: ?scad=mese_corrente |
# prossimo_mese | tutti (default: scadenza ≤ 60 giorni).
# Colonne = quelle a schermo. Nessun esito/giudizio sanitario né prescrizione.

def _visite_scad_queryset(filtro: str):
    import calendar as _cal
    from datetime import date as _date, timedelta as _timedelta

    from django.utils import timezone

    from anagrafica.models import VisitaMedica

    oggi = timezone.localdate()
    if filtro == "mese_corrente":
        _, ld = _cal.monthrange(oggi.year, oggi.month)
        qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False,
            data_scadenza__range=[oggi.replace(day=1), oggi.replace(day=ld)],
        )
    elif filtro == "prossimo_mese":
        pm_y = oggi.year + 1 if oggi.month == 12 else oggi.year
        pm_m = 1 if oggi.month == 12 else oggi.month + 1
        _, ld = _cal.monthrange(pm_y, pm_m)
        qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False,
            data_scadenza__range=[_date(pm_y, pm_m, 1), _date(pm_y, pm_m, ld)],
        )
    else:
        qs = VisitaMedica.objects.filter(
            data_scadenza__isnull=False,
            data_scadenza__lte=oggi + _timedelta(days=60),
        )
    return oggi, qs.select_related("tipo").order_by("data_scadenza")


def _visite_mediche_rows(request: HttpRequest, scope: str) -> list[dict]:
    filtro = (request.GET.get("scad") or "").strip() if scope == "filtered" else "tutti"
    if filtro not in ("mese_corrente", "prossimo_mese"):
        filtro = "tutti"

    oggi, qs = _visite_scad_queryset(filtro)
    visite = list(qs)
    nomi = _nomi_legacy({v.legacy_anagrafica_id for v in visite})

    rows: list[dict] = []
    for v in visite:
        giorni = (v.data_scadenza - oggi).days if v.data_scadenza else None
        if giorni is None:
            stato = ""
        elif giorni < 0:
            stato = f"Scaduta da {abs(giorni)}g"
        else:
            stato = f"Tra {giorni}g"
        rows.append({
            "dipendente": nomi.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}"),
            "tipo": v.tipo.nome if v.tipo_id else "",
            "ultima_visita": v.data_svolgimento.strftime("%d-%m-%Y") if v.data_svolgimento else "",
            "scadenza": v.data_scadenza.strftime("%d-%m-%Y") if v.data_scadenza else "",
            "stato": stato,
        })
    return rows


def _visite_mediche_filters(request: HttpRequest) -> str:
    filtro = (request.GET.get("scad") or "").strip()
    labels = {
        "mese_corrente": "Scadenze del mese corrente",
        "prossimo_mese": "Scadenze del prossimo mese",
    }
    return labels.get(filtro, "Scadute o in scadenza entro 60 giorni")


register(ExportSpec(
    key="visite_mediche",
    title="Visite mediche — scadute o in scadenza",
    sheet_title="Scadenze",
    columns=[
        ("Dipendente", "dipendente"),
        ("Tipo", "tipo"),
        ("Ultima visita", "ultima_visita"),
        ("Scadenza", "scadenza"),
        ("Stato", "stato"),
    ],
    dataset=_visite_mediche_rows,
    filters_label=_visite_mediche_filters,
    permission=_visite_gate(),
))


# ── Visite mediche — copertura per tipologia ─────────────────────────────────
# Seconda tabella della stessa dashboard (nessun filtro in querystring).

def _visite_copertura_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count
    from django.utils import timezone

    from anagrafica.models import DipendenteRuoloOperativo, TipoVisitaMedica, VisitaMedica

    oggi = timezone.localdate()
    valide_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in VisitaMedica.objects.filter(data_scadenza__gte=oggi)
        .order_by().values("tipo_id").annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }
    scadute_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in VisitaMedica.objects.filter(data_scadenza__lt=oggi)
        .order_by().values("tipo_id").annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }

    rows: list[dict] = []
    for t in TipoVisitaMedica.objects.filter(is_active=True).prefetch_related("ruoli_operativi"):
        ruoli_ids = [r.id for r in t.ruoli_operativi.all()]
        if ruoli_ids:
            richiesti = set(
                DipendenteRuoloOperativo.objects
                .filter(ruolo_id__in=ruoli_ids)
                .values_list("legacy_anagrafica_id", flat=True)
            )
        else:
            richiesti = set()
        coperti = set(
            VisitaMedica.objects
            .filter(tipo=t, data_scadenza__gte=oggi)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        rows.append({
            "tipologia": t.nome or "",
            "periodicita": t.durata_mesi,
            "obbligatoria": _si_no(t.obbligatoria),
            "ruoli": ", ".join(sorted(r.nome for r in t.ruoli_operativi.all())),
            "valide": valide_per_tipo.get(t.pk, 0),
            "scadute": scadute_per_tipo.get(t.pk, 0),
            "richiesti": len(richiesti),
            "coperti": len(richiesti & coperti),
            "mancanti": len(richiesti - coperti),
        })
    return rows


register(ExportSpec(
    key="visite_mediche_copertura",
    title="Visite mediche — copertura per tipologia",
    sheet_title="Copertura",
    columns=[
        ("Tipologia", "tipologia"),
        ("Periodicità (mesi)", "periodicita"),
        ("Obbligatoria", "obbligatoria"),
        ("Ruoli collegati", "ruoli"),
        ("Valide", "valide"),
        ("Scadute", "scadute"),
        ("Richiesti (ruoli)", "richiesti"),
        ("Coperti (ruoli)", "coperti"),
        ("Mancanti (ruoli)", "mancanti"),
    ],
    dataset=_visite_copertura_rows,
    permission=_visite_gate(),
))
