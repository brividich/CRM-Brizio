"""Scadenzario generale (`/scadenze`).

Compone i provider per dominio (`dashboard.scadenze_providers`) in un'unica
pagina con cinque viste: calendario del mese, anno, agenda, elenco e andamento
(fotografie giornaliere, per chi gestisce il pannello). Filtri a scelta multipla
in memoria, ricerca, «solo le mie», viste salvate, schermo intero con
aggiornamento automatico. Ogni sorgente rispetta l'ACL del proprio modulo
(gating dentro il provider); le azioni in POST stanno in
`scadenzario/views_calendario.py`.
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
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from core.csv_export import BOM, CSV_CONTENT_TYPE, safe_csv_writer

from .scadenze_providers import (
    ORIZZONTE_GIORNI,
    PROVIDERS,
    SOURCE_LABELS,
    collect_all,
)

# Fasce dello stato: le stesse dei contatori, disgiunte, così filtro e numero
# coincidono sempre (una scadenza sta in una fascia sola).
_FASCE = ("scaduta", "30", "60", "90")
_FASCE_KPI = (
    ("scaduta", "Scadute", "k-red"),
    ("30", "Entro 30 giorni", "k-amber"),
    ("60", "31–60 giorni", "k-blue"),
    ("90", "61–90 giorni", "k-blue"),
)


def _fascia(giorni: int | None) -> str:
    if giorni is None:
        return ""
    if giorni < 0:
        return "scaduta"
    if giorni <= 30:
        return "30"
    if giorni <= 60:
        return "60"
    if giorni <= 90:
        return "90"
    return "oltre"


_VISTE = ("mese", "anno", "agenda", "elenco", "andamento")
_MESI = ("Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio",
         "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre")
_MESI_BREVI = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic")
_GIORNI = ("Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica")
_GIORNI_BREVI = ("Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom")
# Il calendario si sposta al massimo di due anni da oggi, avanti e indietro.
_MESI_MAX = 24
# Voci messe nella cella del mese (quante se ne vedono lo decide l'altezza della
# cella, in pagina); tutte comunque nel pannello del giorno.
_VOCI_PER_CELLA = 12
# Scadute mostrate nel riquadro laterale; tutte nell'elenco filtrato.
_SCADUTE_LATO = 6
# Aggiornamento automatico in schermo intero (minuti).
_AUTO_MINUTI = (5, 10, 15)
# Vista anno: gradini del colore per numero di scadenze nel giorno.
_LIVELLI = ((1, 1), (2, 3), (4, 6), (7, 10))


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


def _anno_richiesto(valore: str, oggi: date) -> int:
    try:
        anno = int(valore)
    except (TypeError, ValueError):
        return oggi.year
    return anno if abs(anno - oggi.year) <= _MESI_MAX // 12 else oggi.year


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


def _per_data(voci) -> dict[date, list]:
    per_giorno: dict[date, list] = defaultdict(list)
    for v in voci:
        if v.data_scadenza:
            per_giorno[v.data_scadenza].append(v)
    return per_giorno


def _griglia_mese(primo: date, voci, oggi: date, feste: dict) -> list[list[dict]]:
    per_giorno = _per_data(voci)
    settimane = []
    for settimana in calendar.Calendar(firstweekday=0).monthdatescalendar(primo.year, primo.month):
        riga = []
        for d in settimana:
            elenco = per_giorno.get(d, [])
            urg = {v.urgenza for v in elenco}
            festa = feste.get(d, "")
            riga.append({
                "data": d,
                "iso": d.isoformat(),
                "label": _giorno_label(d) + (f" · {festa}" if festa else ""),
                "nel_mese": d.month == primo.month,
                "oggi": d == oggi,
                "passato": d < oggi,
                "festivo": d.weekday() >= 5 or bool(festa),
                "festa": festa,
                "voci": elenco,
                "in_cella": elenco[:_VOCI_PER_CELLA],
                "altre": max(0, len(elenco) - _VOCI_PER_CELLA),
                "n": len(elenco),
                "urgenza": "scaduta" if "scaduta" in urg else ("vicina" if "vicina" in urg else ""),
            })
        settimane.append(riga)
    return settimane


def _livello(n: int) -> int:
    for i, (_minimo, massimo) in enumerate(_LIVELLI, start=1):
        if n <= massimo:
            return i
    return len(_LIVELLI) + 1


def _griglia_anno(anno: int, voci, oggi: date, feste: dict, link_giorno) -> list[dict]:
    per_giorno = _per_data(voci)
    mesi = []
    for mese in range(1, 13):
        settimane, totale = [], 0
        for settimana in calendar.Calendar(firstweekday=0).monthdatescalendar(anno, mese):
            riga = []
            for d in settimana:
                if d.month != mese:
                    riga.append(None)
                    continue
                elenco = per_giorno.get(d, [])
                totale += len(elenco)
                festa = feste.get(d, "")
                titolo = f"{d.day} {_MESI[mese - 1].lower()}" + (f" · {festa}" if festa else "")
                if elenco:
                    titolo += f": {len(elenco)} scadenz{'a' if len(elenco) == 1 else 'e'}"
                riga.append({
                    "num": d.day, "n": len(elenco), "livello": _livello(len(elenco)) if elenco else 0,
                    "scadute": any(v.scaduta for v in elenco), "oggi": d == oggi,
                    "festivo": d.weekday() >= 5 or bool(festa), "festa": festa, "titolo": titolo,
                    "href": link_giorno(d) if elenco else "",
                })
            settimane.append(riga)
        mesi.append({"nome": _MESI[mese - 1], "settimane": settimane, "n": totale,
                     "corrente": anno == oggi.year and mese == oggi.month,
                     "href": link_giorno(date(anno, mese, 1), giorno=False)})
    return mesi


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


def _decora(voci, *, feste: dict | None = None) -> None:
    from scadenzario.calendario import non_lavorativo

    for v in voci:
        v.urgenza = _urgenza(v)
        v.quando = _etichetta_giorni(v)
        if v.source in _PRIMA_LA_PERSONA or not v.titolo:
            v.principale, v.secondario = v.soggetto, v.titolo
        else:
            v.principale, v.secondario = v.titolo, v.soggetto
        if v.secondario == v.principale:
            v.secondario = ""
        v.non_lavorativo = non_lavorativo(v.data_scadenza, feste) if feste is not None else ""


def _azioni(request, voci) -> None:
    """Chiave della scadenza, presa in carico e rinnovo diretto (scadenze generiche)."""
    from scadenzario.calendario import chiave_scadenza, nome_utente, prese_in_carico

    for v in voci:
        v.chiave = chiave_scadenza(v)
    prese = prese_in_carico(v.chiave for v in voci)
    gestibili: dict[int, bool] = {}
    for v in voci:
        v.presa = prese.get(v.chiave)
        v.presa_nome = nome_utente(v.presa.utente) if v.presa else ""
        v.presa_mia = bool(v.presa and v.presa.utente_id == request.user.id)
        v.rinnovo_url = ""
        cat = (v.extra or {}).get("categoria_id") if v.source == "generiche" else None
        sid = (v.extra or {}).get("scadenza_id")
        if cat and sid:
            if cat not in gestibili:
                try:
                    from scadenzario.permessi import puo_gestire_categoria

                    gestibili[cat] = puo_gestire_categoria(request, cat)
                except Exception:
                    gestibili[cat] = False
            if gestibili[cat]:
                v.rinnovo_url = reverse("scadenzario:scadenza_rinnovo", args=[sid])


def _viste_salvate(request) -> list:
    try:
        from scadenzario.models import VistaSalvata

        return list(VistaSalvata.objects.filter(utente=request.user))
    except Exception:
        return []


@login_required
def scadenze_globali(request: HttpRequest) -> HttpResponse:
    viste_salvate = _viste_salvate(request)
    # Senza parametri si apre la vista predefinita della persona, se ne ha una.
    if not request.GET:
        predefinita = next((vs for vs in viste_salvate if vs.predefinita and vs.parametri), None)
        if predefinita:
            return redirect(f"{reverse('scadenze_globali')}?{predefinita.parametri}")

    # Filtri a scelta multipla (?sorgente=a&sorgente=b…); vuoto = tutti.
    sel_sorgenti = [s for s in request.GET.getlist("sorgente") if s in PROVIDERS]
    sel_stati = [s for s in request.GET.getlist("stato") if s in _FASCE]
    sel_reparti = [r.strip() for r in request.GET.getlist("reparto") if r.strip()]
    cerca = request.GET.get("q", "").strip()[:80]
    solo_mie = request.GET.get("mie") == "1"
    intero = request.GET.get("intero") == "1"
    try:
        auto = int(request.GET.get("auto") or 0)
    except ValueError:
        auto = 0
    auto = auto if intero and auto in _AUTO_MINUTI else 0
    export_csv = request.GET.get("format") == "csv"
    export_ics = request.GET.get("format") == "ics"
    puo_pannello = _puo_pannello(request)
    vista = request.GET.get("vista", "").strip()
    if export_csv or export_ics:
        vista = "elenco"
    elif vista not in _VISTE or (vista == "andamento" and not puo_pannello):
        vista = "mese"

    oggi = timezone.localdate()
    finestra_kpi = oggi + timedelta(days=ORIZZONTE_GIORNI)
    primo = _mese_richiesto(request.GET.get("mese", ""), oggi)
    anno = _anno_richiesto(request.GET.get("anno", ""), oggi)
    orizzonte = None
    if vista == "mese":
        ultimo = date(primo.year, primo.month, calendar.monthrange(primo.year, primo.month)[1])
        # La griglia mostra anche i primi giorni del mese dopo; mai meno della
        # finestra dei KPI, che devono restare uguali in tutte le viste.
        orizzonte = max(finestra_kpi, ultimo + timedelta(days=7))
    elif vista == "anno":
        orizzonte = max(finestra_kpi, date(anno, 12, 31))

    # Si raccolgono sempre tutte le fonti: i filtri lavorano in memoria, così
    # contatori ed etichette mostrano anche quanto c'è fuori dalla scelta.
    tutte = collect_all(request, oggi=oggi, orizzonte=orizzonte)
    for v in tutte:
        v.fascia = _fascia(v.giorni)

    if not (export_csv or export_ics):
        _azioni(request, tutte)
    if solo_mie or not (export_csv or export_ics):
        from scadenzario.calendario import chiavi_persona_di, e_mia

        chiavi_persona = chiavi_persona_di(request)
        for v in tutte:
            if not hasattr(v, "presa"):
                v.presa = None
            v.mia = e_mia(v, user_id=request.user.id, chiavi_persona=chiavi_persona)

    def per_sorgente(v):
        return not sel_sorgenti or v.source in sel_sorgenti

    def per_stato(v):
        return not sel_stati or v.fascia in sel_stati

    rep_cf = {r.casefold() for r in sel_reparti}

    def per_reparto(v):
        return not rep_cf or (v.reparto or "").casefold() in rep_cf

    cerca_cf = cerca.casefold()

    def per_testo(v):
        if not cerca_cf:
            return True
        testo = " ".join((v.soggetto or "", v.titolo or "", v.kind_label or "", v.elemento_label or "",
                          v.reparto or "", v.source_label))
        return cerca_cf in testo.casefold()

    def per_mie(v):
        return not solo_mie or getattr(v, "mia", False)

    filtri_tutti = (per_sorgente, per_stato, per_reparto, per_testo, per_mie)

    def tranne(escluso):
        return [v for v in tutte if all(f(v) for f in filtri_tutti if f is not escluso)]

    filtrate = [v for v in tutte if all(f(v) for f in filtri_tutti)]

    # KPI, elenco, agenda ed export restano sulla finestra dello scadenzario
    # (scadute + 90 giorni): solo mese e anno guardano più avanti.
    def finestra(elenco):
        return [v for v in elenco if v.giorni is None or v.giorni <= ORIZZONTE_GIORNI]

    voci = finestra(filtrate)

    if export_csv:
        return _export_csv(voci)
    if export_ics:
        from .scadenze_calendario import genera_ics

        resp = HttpResponse(genera_ics(voci, base_url=request.build_absolute_uri("/")),
                            content_type="text/calendar; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="scadenzario.ics"'
        return resp

    from scadenzario.calendario import festivi, pulisci_parametri

    anni = {oggi.year, primo.year, anno} | {v.data_scadenza.year for v in filtrate if v.data_scadenza}
    feste = festivi(anni | {primo.year + 1, primo.year - 1})
    _decora(filtrate, feste=feste)

    # Contatori «a faccette»: ognuno conta con tutti i filtri tranne il proprio,
    # così scegliere una fascia non azzera le altre.
    per_fascia: dict[str, int] = defaultdict(int)
    for v in finestra(tranne(per_stato)):
        per_fascia[v.fascia] += 1
    conta_fonti: dict[str, int] = defaultdict(int)
    for v in finestra(tranne(per_sorgente)):
        conta_fonti[v.source] += 1
    n_mie = sum(1 for v in finestra(tranne(per_mie)) if getattr(v, "mia", False))
    reparti = sorted({v.reparto for v in finestra(tranne(per_reparto)) if v.reparto} | set(sel_reparti),
                     key=str.casefold)

    filtri = {"sorgente": sel_sorgenti, "stato": sel_stati, "reparto": sel_reparti,
              "q": [cerca] if cerca else [], "mie": ["1"] if solo_mie else [],
              "intero": ["1"] if intero else [], "auto": [str(auto)] if auto else []}
    if vista == "mese" and primo != oggi.replace(day=1):
        filtri["mese"] = [primo.strftime("%Y-%m")]
    if vista == "anno" and anno != oggi.year:
        filtri["anno"] = [str(anno)]

    def link(**cambi) -> str:
        """Querystring con i filtri correnti; `chiave=(valore,)` aggiunge o toglie
        quel valore, `chiave=[...]` sostituisce la lista."""
        nuovi = {k: list(v) for k, v in filtri.items()}
        nuovi["vista"] = [vista]
        for k, val in cambi.items():
            if isinstance(val, tuple):
                cur = nuovi.setdefault(k, [])
                for x in val:
                    if x in cur:
                        cur.remove(x)
                    else:
                        cur.append(x)
            else:
                nuovi[k] = list(val)
        return "?" + urlencode({k: v for k, v in nuovi.items() if v}, doseq=True)

    def link_giorno(d: date, giorno: bool = True) -> str:
        extra = {"giorno": [d.isoformat()]} if giorno else {"giorno": []}
        return link(vista=["mese"], mese=[d.strftime("%Y-%m")], anno=[], **extra)

    kpi = [
        {"codice": code, "etichetta": etichetta, "classe": classe, "n": per_fascia.get(code, 0),
         "on": code in sel_stati, "href": link(stato=(code,))}
        for code, etichetta, classe in _FASCE_KPI
    ]
    legenda = [
        {"codice": code, "etichetta": SOURCE_LABELS[code], "n": conta_fonti.get(code, 0),
         "on": code in sel_sorgenti, "href": link(sorgente=(code,))}
        for code in PROVIDERS if conta_fonti.get(code) or code in sel_sorgenti
    ]
    ci_sono_filtri = bool(sel_sorgenti or sel_stati or sel_reparti or cerca or solo_mie)
    parametri_correnti = pulisci_parametri(urlencode(
        {k: v for k, v in {**filtri, "vista": [vista]}.items() if v}, doseq=True))
    for vs in viste_salvate:
        vs.href = f"?{vs.parametri}" if vs.parametri else "?vista=mese"
        vs.attiva = vs.parametri == parametri_correnti

    context: dict[str, Any] = {
        "page_title": "Scadenzario",
        "vista": vista,
        "intero": intero,
        "auto": auto,
        "auto_scelte": [(m, link(auto=[str(m)]), m == auto) for m in _AUTO_MINUTI],
        "link_auto_off": link(auto=[]),
        "aggiornato_alle": timezone.localtime(),
        "kpi": kpi,
        "totale": len(voci),
        "totale_href": link(stato=[]),
        "orizzonte_giorni": ORIZZONTE_GIORNI,
        "reparti": reparti,
        "sorgenti": [(code, SOURCE_LABELS[code], code in sel_sorgenti) for code in PROVIDERS],
        "legenda": legenda,
        "sel_sorgenti": sel_sorgenti,
        "sel_stati": sel_stati,
        "sel_reparti": sel_reparti,
        "cerca": cerca,
        "solo_mie": solo_mie,
        "n_mie": n_mie,
        "link_mie": link(mie=[] if solo_mie else ["1"]),
        "ci_sono_filtri": ci_sono_filtri,
        "link_pulisci": link(sorgente=[], stato=[], reparto=[], q=[], mie=[]),
        "link_viste": {v: link(vista=[v], mese=[], anno=[]) for v in _VISTE},
        "link_intero": link(intero=[] if intero else ["1"], auto=[]),
        "link_csv": link(format=["csv"], intero=[], auto=[], mese=[], anno=[]),
        "link_ics": link(format=["ics"], intero=[], auto=[], mese=[], anno=[]),
        "link_scadute": link(vista=["elenco"], stato=["scaduta"], mese=[], anno=[]),
        "viste_salvate": viste_salvate,
        "parametri_correnti": parametri_correnti,
        "torna": request.get_full_path(),
        "puo_pannello": puo_pannello,
        "puo_generiche": _puo_generiche(request),
        "oggi": oggi,
        "oggi_iso": oggi.isoformat(),
    }

    if vista == "mese":
        settimane = _griglia_mese(primo, filtrate, oggi, feste)
        scadute = sorted((v for v in filtrate if v.scaduta and v.data_scadenza), key=lambda v: v.data_scadenza)
        prec, succ = _sposta_mese(primo, -1), _sposta_mese(primo, 1)
        try:
            giorno_sel = date.fromisoformat(request.GET.get("giorno", "")).isoformat()
        except ValueError:
            giorno_sel = ""
        context.update({
            "mese_label": f"{_MESI[primo.month - 1]} {primo.year}",
            "link_prec": link(mese=[prec.strftime("%Y-%m")]),
            "link_succ": link(mese=[succ.strftime("%Y-%m")]),
            "link_oggi": link(mese=[]),
            "mese_corrente": primo == oggi.replace(day=1),
            "nav_prec": abs(_indice_mese(prec) - _indice_mese(oggi)) <= _MESI_MAX,
            "nav_succ": abs(_indice_mese(succ) - _indice_mese(oggi)) <= _MESI_MAX,
            "settimane": settimane,
            "n_settimane": len(settimane),
            "intestazione": _GIORNI_BREVI,
            "giorni_con_voci": [c for riga in settimane for c in riga if c["n"]],
            "n_mese": sum(c["n"] for riga in settimane for c in riga if c["nel_mese"]),
            "n_scadute_lato": len(scadute),
            "scadute_lato": scadute[:_SCADUTE_LATO],
            "scadute_altre": max(0, len(scadute) - _SCADUTE_LATO),
            "prossimi_7": [v for v in filtrate if v.giorni is not None and 0 <= v.giorni <= 7],
            "giorno_sel": giorno_sel,
            "feste_mese": sorted((d, n) for d, n in feste.items() if d.year == primo.year and d.month == primo.month),
        })
    elif vista == "anno":
        context.update({
            "anno": anno,
            "mesi_anno": _griglia_anno(anno, filtrate, oggi, feste, link_giorno),
            "n_anno": sum(1 for v in filtrate if v.data_scadenza and v.data_scadenza.year == anno),
            "n_scadute_prima": sum(1 for v in filtrate if v.data_scadenza and v.data_scadenza.year < anno),
            "link_anno_prec": link(anno=[str(anno - 1)]),
            "link_anno_succ": link(anno=[str(anno + 1)]),
            "link_anno_oggi": link(anno=[]),
            "nav_anno_prec": abs(anno - 1 - oggi.year) <= _MESI_MAX // 12,
            "nav_anno_succ": abs(anno + 1 - oggi.year) <= _MESI_MAX // 12,
            "intestazione": _GIORNI_BREVI,
            "livelli": [(i, f"{a}" if a == b else f"{a}–{b}") for i, (a, b) in enumerate(_LIVELLI, start=1)]
                       + [(len(_LIVELLI) + 1, f"{_LIVELLI[-1][1] + 1}+")],
        })
    elif vista == "agenda":
        context["gruppi"] = _agenda(voci, oggi)
    elif vista == "andamento":
        from .scadenze_andamento import andamento

        context["andamento"] = andamento(oggi)
    else:
        context["page_obj"] = Paginator(voci, 50).get_page(request.GET.get("page"))
        context["link_pagina"] = link()
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
