"""Scadenzario Globale Unificato (`/scadenze`).

Vista aggregatrice cross-modulo: compone i provider per dominio
(`dashboard.scadenze_providers`) in un'unica tabella con filtri trasversali
(tipo/sorgente, stato, reparto) ed export CSV. Ogni sorgente rispetta l'ACL
del proprio modulo (gating dentro il provider).
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from core.csv_export import BOM, CSV_CONTENT_TYPE, safe_csv_writer
from django.shortcuts import render
from django.utils import timezone

from .scadenze_providers import (
    ORIZZONTE_GIORNI,
    PROVIDERS,
    SOURCE_LABELS,
    collect_all,
)

# Filtro stato → predicato sui giorni.
_STATI = {
    "scaduta": lambda g: g is not None and g < 0,
    "30": lambda g: g is not None and 0 <= g <= 30,
    "60": lambda g: g is not None and 0 <= g <= 60,
    "90": lambda g: g is not None and 0 <= g <= 90,
}


_VISTE = ("mese", "agenda", "elenco")
_MESI = ("Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio",
         "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre")
_MESI_BREVI = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
_GIORNI = ("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica")
_GIORNI_BREVI = ("Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom")
# Il calendario si sposta al massimo di due anni da oggi, avanti e indietro.
_MESI_MAX = 24
# Voci mostrate dentro la cella del mese; tutte nel pannello del giorno.
_VOCI_PER_CELLA = 3
# Scadute mostrate nel riquadro laterale; tutte nell'elenco filtrato.
_SCADUTE_LATO = 6


def _indice_mese(d: date) -> int:
    return d.year * 12 + d.month - 1


def _mese_richiesto(valore: str, oggi: date) -> date:
    try:
        anno, mese = (int(x) for x in valore.split("-", 1))
        primo = date(anno, mese, 1)
    except (ValueError, TypeError):
        return oggi.replace(day=1)
    if abs(_indice_mese(primo) - _indice_mese(oggi)) > _MESI_MAX:
        return oggi.replace(day=1)
    return primo


def _sposta_mese(primo: date, passi: int) -> date:
    n = _indice_mese(primo) + passi
    return date(n // 12, n % 12 + 1, 1)


def _urgenza(v) -> str:
    if v.giorni is None:
        return ""
    if v.giorni < 0:
        return "scaduta"
    if v.giorni <= 30:
        return "vicina"
    return ""


def _etichetta_giorni(v) -> str:
    g = v.giorni
    if g is None:
        return ""
    if g < -1:
        return f"scaduta da {-g} giorni"
    if g == -1:
        return "scaduta ieri"
    if g == 0:
        return "scade oggi"
    if g == 1:
        return "scade domani"
    return f"tra {g} giorni"


def _giorno_label(d: date) -> str:
    return f"{_GIORNI[d.weekday()]} {d.day} {_MESI[d.month - 1].lower()} {d.year}"


def _griglia_mese(primo: date, voci, oggi: date) -> list[list[dict]]:
    per_giorno: dict[date, list] = defaultdict(list)
    for v in voci:
        if v.data_scadenza:
            per_giorno[v.data_scadenza].append(v)
    settimane = []
    for settimana in calendar.Calendar(firstweekday=0).monthdatescalendar(primo.year, primo.month):
        riga = []
        for d in settimana:
            elenco = per_giorno.get(d, [])
            urg = {v.urgenza for v in elenco}
            riga.append({
                "data": d,
                "iso": d.isoformat(),
                "label": _giorno_label(d),
                "nel_mese": d.month == primo.month,
                "oggi": d == oggi,
                "passato": d < oggi,
                "festivo": d.weekday() >= 5,
                "voci": elenco,
                "in_cella": elenco[:_VOCI_PER_CELLA],
                "altre": max(0, len(elenco) - _VOCI_PER_CELLA),
                "n": len(elenco),
                "urgenza": "scaduta" if "scaduta" in urg else ("vicina" if "vicina" in urg else ""),
            })
        settimane.append(riga)
    return settimane


def _per_giorno(voci) -> list[dict]:
    giorni: dict[date, list] = defaultdict(list)
    for v in voci:
        giorni[v.data_scadenza].append(v)
    return [{"data": d, "num": d.day, "dow": _GIORNI_BREVI[d.weekday()],
             "mese": _MESI_BREVI[d.month - 1], "voci": giorni[d]} for d in sorted(giorni)]


def _agenda(voci, oggi: date) -> list[dict]:
    """Gruppi per settimana (lunedì-domenica), le scadute in testa."""
    gruppi: list[dict] = []
    scadute = [v for v in voci if v.scaduta and v.data_scadenza]
    if scadute:
        gruppi.append({"titolo": "Scadute", "n": len(scadute), "classe": "scaduta",
                       "giorni": _per_giorno(scadute)})
    lunedi = oggi - timedelta(days=oggi.weekday())
    settimane: dict[date, list] = defaultdict(list)
    for v in voci:
        if v.scaduta or not v.data_scadenza:
            continue
        settimane[v.data_scadenza - timedelta(days=v.data_scadenza.weekday())].append(v)
    for inizio in sorted(settimane):
        fine = inizio + timedelta(days=6)
        if inizio == lunedi:
            titolo = "Questa settimana"
        elif inizio == lunedi + timedelta(days=7):
            titolo = "La prossima settimana"
        else:
            titolo = (f"Dal {inizio.day} {_MESI_BREVI[inizio.month - 1]} "
                      f"al {fine.day} {_MESI_BREVI[fine.month - 1]}")
        gruppi.append({"titolo": titolo, "n": len(settimane[inizio]),
                       "classe": "corrente" if inizio == lunedi else "",
                       "giorni": _per_giorno(settimane[inizio])})
    return gruppi


# Fonti in cui conta prima la persona (di chi è la visita, la qualifica, il DPI…);
# nelle altre conta prima la cosa che scade (il certificato, l'azione, l'attività).
_PRIMA_LA_PERSONA = {"hr", "qualifiche", "dpi", "procedure"}


def _decora(voci) -> None:
    for v in voci:
        v.urgenza = _urgenza(v)
        v.quando = _etichetta_giorni(v)
        if v.source in _PRIMA_LA_PERSONA or not v.titolo:
            v.principale, v.secondario = v.soggetto, v.titolo
        else:
            v.principale, v.secondario = v.titolo, v.soggetto
        if v.secondario == v.principale:
            v.secondario = ""


@login_required
def scadenze_globali(request: HttpRequest) -> HttpResponse:
    filtro_sorgente = request.GET.get("sorgente", "").strip()   # uno dei PROVIDERS o ""
    filtro_stato = request.GET.get("stato", "").strip()          # scaduta/30/60/90/""
    filtro_reparto = request.GET.get("reparto", "").strip()
    export_csv = request.GET.get("format") == "csv"
    export_ics = request.GET.get("format") == "ics"
    vista = request.GET.get("vista", "").strip()
    if export_csv or export_ics:
        vista = "elenco"
    elif vista not in _VISTE:
        vista = "mese"

    oggi = timezone.localdate()
    primo = _mese_richiesto(request.GET.get("mese", ""), oggi)
    orizzonte = None
    if vista == "mese":
        ultimo = date(primo.year, primo.month, calendar.monthrange(primo.year, primo.month)[1])
        # La griglia mostra anche i primi giorni del mese dopo; mai meno della
        # finestra dei KPI, che devono restare uguali in tutte le viste.
        orizzonte = max(oggi + timedelta(days=ORIZZONTE_GIORNI), ultimo + timedelta(days=7))

    # Sorgenti da interrogare: solo quella selezionata, altrimenti tutte.
    if filtro_sorgente in PROVIDERS:
        sources = {filtro_sorgente}
    else:
        sources = None

    tutte = collect_all(request, sources=sources, oggi=oggi, orizzonte=orizzonte)

    # Filtro stato (in memoria: le voci sono già normalizzate su `giorni`).
    if filtro_stato in _STATI:
        pred = _STATI[filtro_stato]
        tutte = [v for v in tutte if pred(v.giorni)]

    # Filtro reparto (case-insensitive).
    if filtro_reparto:
        rf = filtro_reparto.casefold()
        tutte = [v for v in tutte if v.reparto and v.reparto.casefold() == rf]

    # KPI, elenco, agenda ed export restano sulla finestra dello scadenzario
    # (scadute + 90 giorni): solo la griglia del mese guarda più avanti.
    voci = [v for v in tutte if v.giorni is None or v.giorni <= ORIZZONTE_GIORNI]

    # Export CSV (prima della paginazione: esporta il set filtrato completo).
    if export_csv:
        return _export_csv(voci)
    if export_ics:
        from .scadenze_calendario import genera_ics

        resp = HttpResponse(genera_ics(voci, base_url=request.build_absolute_uri("/")),
                            content_type="text/calendar; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="scadenzario.ics"'
        return resp

    _decora(tutte)

    # KPI di sintesi.
    n_scadute = sum(1 for v in voci if v.scaduta)
    n_30gg = sum(1 for v in voci if not v.scaduta and v.giorni is not None and v.giorni <= 30)
    n_60gg = sum(1 for v in voci if not v.scaduta and v.giorni is not None and 30 < v.giorni <= 60)
    n_90gg = sum(1 for v in voci if not v.scaduta and v.giorni is not None and 60 < v.giorni <= 90)

    reparti = sorted({v.reparto for v in voci if v.reparto})

    # Legenda: le fonti presenti con il loro numero (stessa finestra dei KPI).
    conta: dict[str, int] = defaultdict(int)
    for v in voci:
        conta[v.source] += 1
    legenda = [(code, SOURCE_LABELS[code], conta[code]) for code in PROVIDERS if conta.get(code)]

    filtri = {k: val for k, val in (("sorgente", filtro_sorgente), ("stato", filtro_stato),
                                    ("reparto", filtro_reparto)) if val}
    qs_mese = urlencode({**filtri, "vista": "mese"})

    context: dict[str, Any] = {
        "page_title": "Scadenzario",
        "vista": vista,
        "totale": len(voci),
        "n_scadute": n_scadute,
        "n_30gg": n_30gg,
        "n_60gg": n_60gg,
        "n_90gg": n_90gg,
        "orizzonte_giorni": ORIZZONTE_GIORNI,
        "source_labels": SOURCE_LABELS,
        "reparti": reparti,
        "sorgenti": [(code, SOURCE_LABELS[code]) for code in PROVIDERS],
        "legenda": legenda,
        "filtro_sorgente": filtro_sorgente,
        "filtro_stato": filtro_stato,
        "filtro_reparto": filtro_reparto,
        "qs_filtri": urlencode(filtri),
        "qs_senza_sorgente": urlencode({k: val for k, val in filtri.items() if k != "sorgente"}),
        "qs_senza_stato": urlencode({k: val for k, val in filtri.items() if k != "stato"}),
        "puo_pannello": _puo_pannello(request),
        "puo_generiche": _puo_generiche(request),
        "oggi": oggi,
    }

    if vista == "mese":
        settimane = _griglia_mese(primo, tutte, oggi)
        scadute = sorted((v for v in tutte if v.scaduta and v.data_scadenza),
                         key=lambda v: v.data_scadenza)
        prec, succ = _sposta_mese(primo, -1), _sposta_mese(primo, 1)
        giorni_con_voci = [c for riga in settimane for c in riga if c["n"]]
        context.update({
            "qs_mese": qs_mese,
            "mese_label": f"{_MESI[primo.month - 1]} {primo.year}",
            "mese_prec": prec.strftime("%Y-%m"),
            "mese_succ": succ.strftime("%Y-%m"),
            "mese_corrente": primo == oggi.replace(day=1),
            "nav_prec": abs(_indice_mese(prec) - _indice_mese(oggi)) <= _MESI_MAX,
            "nav_succ": abs(_indice_mese(succ) - _indice_mese(oggi)) <= _MESI_MAX,
            "settimane": settimane,
            "intestazione": _GIORNI_BREVI,
            "giorni_con_voci": giorni_con_voci,
            "n_mese": sum(c["n"] for riga in settimane for c in riga if c["nel_mese"]),
            "scadute_lato": scadute[:_SCADUTE_LATO],
            "scadute_altre": max(0, len(scadute) - _SCADUTE_LATO),
            "prossimi_7": [v for v in tutte if v.giorni is not None and 0 <= v.giorni <= 7],
        })
    elif vista == "agenda":
        context["gruppi"] = _agenda(voci, oggi)
    else:
        context["page_obj"] = Paginator(voci, 50).get_page(request.GET.get("page"))
    return render(request, "dashboard/pages/scadenze_globali.html", context)


def _puo_pannello(request) -> bool:
    try:
        from scadenzario.visibilita import puo_gestire_pannello

        return puo_gestire_pannello(request)
    except Exception:
        return False


def _puo_generiche(request) -> bool:
    try:
        from scadenzario.permessi import puo_usare_modulo

        return puo_usare_modulo(request)
    except Exception:
        return False


def _export_csv(voci) -> HttpResponse:
    resp = HttpResponse(content_type=CSV_CONTENT_TYPE)
    resp["Content-Disposition"] = 'attachment; filename="scadenzario_globale.csv"'
    resp.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
    writer = safe_csv_writer(resp, delimiter=";")
    writer.writerow(["Sorgente", "Tipo", "Soggetto", "Reparto", "Descrizione", "Scadenza", "Stato"])
    for v in voci:
        if v.scaduta:
            stato = f"Scaduta da {abs(v.giorni)} giorni"
        elif v.giorni is not None:
            stato = f"Scade tra {v.giorni} giorni"
        else:
            stato = ""
        writer.writerow([
            SOURCE_LABELS.get(v.source, v.source),
            v.kind_label,
            v.soggetto,
            v.reparto,
            v.titolo,
            v.data_scadenza.strftime("%d-%m-%Y") if v.data_scadenza else "",
            stato,
        ])
    return resp
