"""Viste del modulo Gestione Carichi Macchina.

Vista PRIMARIA: la matrice "Excel" (macchine x giorni), resa server-side e con
celle editabili inline via HTMX. L'API JSON (FBV + JsonResponse, NON django-ninja)
alimenta la vista Gantt (Passo 4).

ACL: per ora @login_required; il binding ACL v2 + voce di menu arriva al Passo 6.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import ceil

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

# Ordine delle sezioni come nel foglio Excel.
_CAT_ORDER = ["4_axis", "torni_fresa", "5_axis", "alesatrici", "torni"]
_GIORNI_DEFAULT = 21
_GIORNI_MIN = 7
_GIORNI_MAX = 56


def _as_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _lunedi(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _giorni_lavorativi(start: date, n: int) -> list[date]:
    """n giorni lavorativi (lun-ven) a partire da start (weekend esclusi, come nel foglio)."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _inizio_finestra_prec(start: date, n: int) -> date:
    """Inizio della finestra precedente: n giorni lavorativi prima di start."""
    ws: list[date] = []
    d = start - timedelta(days=1)
    while len(ws) < n:
        if d.weekday() < 5:
            ws.append(d)
        d -= timedelta(days=1)
    return ws[-1]


def _finestra(request):
    """Finestra in GIORNI LAVORATIVI (no sabato/domenica): (start, giorni_n, [giorni])."""
    oggi = timezone.localdate()
    start = _parse_date(request.GET.get("start")) or _lunedi(oggi)
    giorni_n = _as_int(request.GET.get("giorni"), _GIORNI_DEFAULT) or _GIORNI_DEFAULT
    giorni_n = max(_GIORNI_MIN, min(giorni_n, _GIORNI_MAX))
    giorni = _giorni_lavorativi(start, giorni_n)
    return giorni[0], giorni_n, giorni


def _classe_cella(job, oggi: date) -> str:
    """Classe colore della cella secondo stato/urgenza."""
    from .models import Pianificazione

    if job.stato == Pianificazione.STATO_COMPLETATA:
        return "done"
    commessa = job.commessa
    urgente = bool(
        commessa
        and (
            commessa.priorita >= commessa.PRIORITA_URGENTE
            or (commessa.data_consegna and commessa.data_consegna < oggi)
        )
    )
    if urgente:
        return "urg"
    if job.stato == Pianificazione.STATO_IN_CORSO:
        return "wip"
    return "plan"


def _job_label(job) -> str:
    if job.testo_originale:
        return job.testo_originale
    parti = []
    if job.qta:
        parti.append(str(job.qta))
    if job.famiglia_id:
        parti.append(job.famiglia.nome)
    if job.ore:
        parti.append(f"({job.ore}h)")
    if job.fase:
        parti.append(job.fase)
    return " ".join(parti) or "—"


def _colore_commessa(chiave: str) -> str:
    """Colore HSL stabile e deterministico per raggruppare visivamente una commessa/pezzo.

    Niente hash() (varia tra processi): rolling hash manuale -> stesso colore ad ogni render.
    """
    chiave = (chiave or "").strip().lower()
    if not chiave:
        return "hsl(212, 14%, 62%)"  # grigio-blu neutro
    h = 0
    for ch in chiave:
        h = (h * 31 + ord(ch)) % 360
    return f"hsl({h}, 58%, 44%)"


def _chiave_commessa(job) -> str:
    """Identita' di commessa/pezzo per il colore: cliente+famiglia se noti, altrimenti famiglia/testo."""
    if job.commessa_id and getattr(job.commessa, "cliente", ""):
        return job.commessa.cliente + "/" + (job.famiglia.nome if job.famiglia_id else "")
    if job.famiglia_id:
        return job.famiglia.nome
    return job.testo_originale or ""


def _job_ctx(job, oggi: date) -> dict:
    classe = _classe_cella(job, oggi)
    return {
        "id": job.id,
        "label": _job_label(job),
        "classe": classe,
        "colore": _colore_commessa(_chiave_commessa(job)),
        "urgente": classe == "urg",
    }


@login_required
def vista_excel(request):
    from .models import FamigliaPezzo, Macchina, Pianificazione

    oggi = timezone.localdate()
    start = _parse_date(request.GET.get("start")) or _lunedi(oggi)
    giorni_n = _as_int(request.GET.get("giorni"), _GIORNI_DEFAULT) or _GIORNI_DEFAULT
    giorni_n = max(_GIORNI_MIN, min(giorni_n, _GIORNI_MAX))
    giorni = _giorni_lavorativi(start, giorni_n)  # solo lun-ven, come nel foglio
    start = giorni[0]
    fine = giorni[-1]

    macchine = list(
        Macchina.objects.filter(attivo=True)
        .select_related("asset")
        .order_by("categoria", "ordine_sezione", "id")
    )

    pians = (
        Pianificazione.objects.filter(
            data__range=(start, fine), macchina__in=macchine or [0]
        )
        .select_related("commessa", "famiglia")
    )
    lookup: dict[tuple, list] = defaultdict(list)
    for p in pians:
        lookup[(p.macchina_id, p.turno, p.data)].append(p)

    by_cat: dict[str, list] = defaultdict(list)
    for m in macchine:
        by_cat[m.categoria].append(m)

    cat_label = dict(Macchina.CATEGORIA_CHOICES)
    # Flag di visualizzazione turni: OFF (default) = una riga per macchina (look familiare,
    # tutti i turni uniti); ON = righe separate 1° turno / 2° turno / notturno (solo quelli
    # che la macchina ha). Spostare un lavoro su una riga turno non tocca gli altri turni.
    mostra_turni = request.GET.get("turni") == "1"
    sezioni = []
    for cat in _CAT_ORDER:
        ms = by_cat.get(cat)
        if not ms:
            continue
        righe = []
        for m in ms:
            ferma = m.stato_pianificazione != Macchina.STATO_ATTIVA

            def _celle(turni_inclusi):
                out = []
                for g in giorni:
                    jobs = []
                    for t in turni_inclusi:
                        jobs += lookup.get((m.id, t, g), [])
                    out.append({
                        "data": g, "data_iso": g.isoformat(),
                        "jobs": [_job_ctx(j, oggi) for j in jobs], "oggi": g == oggi,
                    })
                return out

            if mostra_turni:
                seq = [(Pianificazione.TURNO_GIORNO, "1° turno", False)]
                if m.ha_secondo_turno:
                    seq.append((Pianificazione.TURNO_T2, "2° turno", True))
                if m.ha_turno_notte:
                    seq.append((Pianificazione.TURNO_NOTTE, "notturno", True))
                for turno, label, sub in seq:
                    righe.append({
                        "macchina": m, "turno": turno, "turno_label": label, "sub": sub,
                        "celle": _celle([turno]), "ferma": ferma,
                    })
            else:
                # Default: 1°+2° turno UNITI in una riga (look familiare); il notturno
                # resta su riga separata solo se la macchina lo ha (com'era nel foglio).
                righe.append({
                    "macchina": m, "turno": Pianificazione.TURNO_GIORNO, "turno_label": "",
                    "sub": False, "ferma": ferma,
                    "celle": _celle([Pianificazione.TURNO_GIORNO, Pianificazione.TURNO_T2]),
                })
                if m.ha_turno_notte:
                    righe.append({
                        "macchina": m, "turno": Pianificazione.TURNO_NOTTE, "turno_label": "notturno",
                        "sub": True, "ferma": ferma,
                        "celle": _celle([Pianificazione.TURNO_NOTTE]),
                    })
        sezioni.append({"categoria": cat, "label": cat_label.get(cat, cat), "righe": righe})

    # autocomplete famiglia via <datalist>: nomi canonici + alias
    famiglie = list(FamigliaPezzo.objects.values_list("nome", flat=True))

    ctx = {
        "giorni": giorni,
        "sezioni": sezioni,
        "oggi": oggi,
        "start": start,
        "giorni_n": giorni_n,
        "prev_start": _inizio_finestra_prec(start, giorni_n).isoformat(),
        "next_start": (fine + timedelta(days=1)).isoformat(),
        "famiglie": famiglie,
        "mostra_turni": mostra_turni,
        "stato_choices": Pianificazione.STATO_CHOICES,
        "fase_choices": Pianificazione.FASE_CHOICES,
    }
    return render(request, "gestione_carichi_macchina/excel.html", ctx)


def _match_famiglia(testo: str):
    from .models import FamigliaAlias, FamigliaPezzo

    toks = set(re.findall(r"[a-zàèéìòù]+", testo.lower()))
    if not toks:
        return None
    fam = FamigliaPezzo.objects.filter(nome__in=toks).first()
    if fam:
        return fam
    alias = FamigliaAlias.objects.filter(alias__in=toks).select_related("famiglia").first()
    return alias.famiglia if alias else None


def _render_cella(request, macchina, turno, data):
    from .models import Pianificazione

    oggi = timezone.localdate()
    jobs = list(
        Pianificazione.objects.filter(macchina=macchina, turno=turno, data=data)
        .select_related("commessa", "famiglia")
        .order_by("id")
    )
    ctx = {
        "macchina": macchina, "turno": turno, "data": data, "data_iso": data.isoformat(),
        "jobs": [_job_ctx(j, oggi) for j in jobs],
    }
    return render(request, "gestione_carichi_macchina/partials/_cella.html", ctx)


@login_required
@require_http_methods(["GET", "POST"])
def cella_edit(request):
    """GET: form inline (o display con ?display=1). POST: salva/elimina, ritorna display."""
    from .models import FamigliaPezzo, Macchina, Pianificazione
    from .parsing import parse_cell

    mid = request.GET.get("macchina") or request.POST.get("macchina")
    macchina = get_object_or_404(Macchina, pk=mid)
    turno = request.GET.get("turno") or request.POST.get("turno") or Pianificazione.TURNO_GIORNO
    data = _parse_date(request.GET.get("data") or request.POST.get("data"))
    if data is None:
        data = timezone.localdate()

    if request.method == "GET":
        if request.GET.get("display"):
            return _render_cella(request, macchina, turno, data)
        job = (
            Pianificazione.objects.filter(macchina=macchina, turno=turno, data=data)
            .order_by("id").first()
        )
        ctx = {
            "macchina": macchina, "turno": turno, "data": data, "data_iso": data.isoformat(),
            "job": job,
            "famiglie": list(FamigliaPezzo.objects.values_list("nome", flat=True)),
            "stato_choices": Pianificazione.STATO_CHOICES,
            "fase_choices": Pianificazione.FASE_CHOICES,
        }
        return render(request, "gestione_carichi_macchina/partials/_cella_form.html", ctx)

    # POST
    job_id = _as_int(request.POST.get("pianificazione_id"))
    if request.POST.get("elimina") and job_id:
        Pianificazione.objects.filter(pk=job_id, macchina=macchina).delete()
        return _render_cella(request, macchina, turno, data)

    testo = (request.POST.get("testo") or "").strip()
    if not testo:
        # niente testo: se esiste e si svuota, elimina; altrimenti no-op
        if job_id:
            Pianificazione.objects.filter(pk=job_id, macchina=macchina).delete()
        return _render_cella(request, macchina, turno, data)

    p = parse_cell(testo)
    qta = _as_int(request.POST.get("qta")) if request.POST.get("qta") else p.qta
    ore = _as_dec(request.POST.get("ore")) if request.POST.get("ore") else (Decimal(p.ore) if p.ore else None)
    fase = request.POST.get("fase") or p.fase or Pianificazione.FASE_NA
    stato = request.POST.get("stato") or Pianificazione.STATO_PIANIFICATA
    famiglia = _match_famiglia(testo)

    valori = {
        "testo_originale": testo, "qta": qta, "ore": ore, "fase": fase,
        "stato": stato, "famiglia": famiglia,
        "fonte": Pianificazione.FONTE_MANUALE,  # gli edit manuali non vengono sovrascritti dall'import
    }
    if job_id:
        Pianificazione.objects.filter(pk=job_id, macchina=macchina).update(**valori)
    else:
        Pianificazione.objects.create(macchina=macchina, turno=turno, data=data, **valori)
    return _render_cella(request, macchina, turno, data)


@login_required
def api_pianificazioni(request):
    """JSON per la vista Gantt (Passo 4). FBV + JsonResponse, niente django-ninja."""
    from .models import Macchina, Pianificazione

    start = _parse_date(request.GET.get("start")) or _lunedi(timezone.localdate())
    giorni_n = _as_int(request.GET.get("giorni"), _GIORNI_DEFAULT) or _GIORNI_DEFAULT
    giorni_n = max(_GIORNI_MIN, min(giorni_n, _GIORNI_MAX))
    fine = start + timedelta(days=giorni_n - 1)

    pians = (
        Pianificazione.objects.filter(data__range=(start, fine))
        .select_related("macchina__asset", "famiglia", "commessa")
        .order_by("data")
    )
    items = [
        {
            "id": p.id,
            "macchina_id": p.macchina_id,
            "macchina": p.macchina.asset.asset_tag if p.macchina.asset_id else "",
            "data": p.data.isoformat(),
            "turno": p.turno,
            "famiglia": p.famiglia.nome if p.famiglia_id else None,
            "qta": p.qta,
            "ore": float(p.ore) if p.ore is not None else None,
            "stato": p.stato,
            "fase": p.fase,
            "testo": p.testo_originale,
        }
        for p in pians
    ]
    macchine = [
        {"id": m.id, "codice": m.codice, "categoria": m.categoria}
        for m in Macchina.objects.filter(attivo=True).select_related("asset")
    ]
    return JsonResponse({"ok": True, "start": start.isoformat(), "giorni": giorni_n,
                         "macchine": macchine, "items": items})


def _assign_lanes(bars: list[dict]) -> int:
    """Assegna a ogni barra una 'corsia' verticale per non sovrapporre intervalli.

    Greedy interval partitioning su (start_idx, start_idx+span). Imposta b['lane'].
    Ritorna il numero di corsie usate (min 1).
    """
    lanes_end: list[int] = []
    for b in sorted(bars, key=lambda x: x["start_idx"]):
        fine_idx = b["start_idx"] + b["span"]
        for li, end in enumerate(lanes_end):
            if b["start_idx"] >= end:
                b["lane"] = li
                lanes_end[li] = fine_idx
                break
        else:
            b["lane"] = len(lanes_end)
            lanes_end.append(fine_idx)
    return len(lanes_end) or 1


def _segna_conflitti(bars: list[dict]) -> bool:
    """Marca le barre che si sovrappongono nel tempo sullo STESSO turno (conflitto di
    capacita': in finite-capacity due lavori non possono occupare la stessa macchina/turno).
    Ritorna True se la riga ha almeno un conflitto."""
    has = False
    per_turno: dict[str, list] = defaultdict(list)
    for b in bars:
        per_turno[b["turno"]].append(b)
    for grp in per_turno.values():
        grp.sort(key=lambda x: x["start_idx"])
        max_end = -1
        prev = None
        for b in grp:
            if b["start_idx"] < max_end:
                b["conflitto"] = True
                if prev is not None:
                    prev["conflitto"] = True
                has = True
            if b["start_idx"] + b["span"] > max_end:
                max_end = b["start_idx"] + b["span"]
                prev = b
    return has


@login_required
def vista_gantt(request):
    """Gantt (stessa sorgente dati della vista Excel): barre per pianificazione,
    raggruppate per macchina/sezione, con saturazione, filtri, zoom, corsie e
    drag-to-reschedule."""
    from .models import Commessa, FamigliaPezzo, Macchina, Pianificazione
    from .previsioni import costruisci_indici, prevedi_ore, rischio_ritardo
    from .tasks import saturazione_finestra

    start, giorni_n, giorni = _finestra(request)
    oggi = timezone.localdate()
    fine = giorni[-1]
    idx_map = {g: i for i, g in enumerate(giorni)}  # data -> colonna (in giorni lavorativi)
    cell_w = max(24, min(_as_int(request.GET.get("cw"), 38) or 38, 72))
    lane_h = 30

    f_cat = request.GET.get("cat") or ""
    f_cliente = (request.GET.get("cliente") or "").strip()
    f_fam = _as_int(request.GET.get("fam"))
    mostra_turni = request.GET.get("turni") == "1"

    macchine_qs = Macchina.objects.filter(attivo=True).select_related("asset")
    if f_cat:
        macchine_qs = macchine_qs.filter(categoria=f_cat)
    macchine = list(macchine_qs.order_by("categoria", "ordine_sezione", "id"))

    pians_qs = (
        Pianificazione.objects.filter(data__range=(start, fine), macchina__in=macchine or [0])
        .select_related("commessa", "famiglia")
    )
    if f_fam:
        pians_qs = pians_qs.filter(famiglia_id=f_fam)
    if f_cliente:
        pians_qs = pians_qs.filter(commessa__cliente__icontains=f_cliente)

    by_mac: dict[int, list] = defaultdict(list)
    for p in pians_qs:
        by_mac[p.macchina_id].append(p)

    sat = saturazione_finestra(start, giorni_n)
    filtro_lavori = bool(f_fam or f_cliente)  # nasconde le righe senza barre
    ciclo_tempi, affinita_ore, famiglia_ore = costruisci_indici()  # AI predittiva: durata

    by_cat: dict[str, list] = defaultdict(list)
    for m in macchine:
        by_cat[m.categoria].append(m)
    cat_label = dict(Macchina.CATEGORIA_CHOICES)

    leg_count: Counter = Counter()       # legenda commesse: colore -> #barre
    leg_label: dict[str, str] = {}       # colore -> etichetta leggibile

    sezioni = []
    for cat in _CAT_ORDER:
        ms = by_cat.get(cat)
        if not ms:
            continue
        righe = []
        for m in ms:
            ogg = float(m.ore_giorno_disponibili) or 8.0
            bars = []
            for p in by_mac.get(m.id, []):
                start_idx = idx_map.get(p.data)
                if start_idx is None:
                    continue
                ore = float(p.ore) if p.ore else None
                stima = False
                if ore is None:  # AI predittiva: stima la durata quando le ore non sono scritte
                    pred, _f, _c = prevedi_ore(
                        qta=p.qta, macchina_id=p.macchina_id, famiglia_id=p.famiglia_id,
                        ciclo_tempi=ciclo_tempi, affinita_ore=affinita_ore, famiglia_ore=famiglia_ore,
                    )
                    if pred:
                        ore, stima = pred, True
                span = min(max(1, ceil(ore / ogg)) if ore else 1, giorni_n - start_idx)
                classe = _classe_cella(p, oggi)
                colore = _colore_commessa(_chiave_commessa(p))
                cliente = p.commessa.cliente if p.commessa_id else ""
                famiglia = p.famiglia.nome if p.famiglia_id else ""
                # rischio ritardo: fine prevista (durata) oltre la consegna della commessa
                ritardo = False
                if p.commessa_id and p.commessa.data_consegna and ore:
                    ritardo = rischio_ritardo(
                        data_inizio=p.data, ore_previste=ore, ore_giorno=ogg,
                        data_consegna=p.commessa.data_consegna,
                    ).get("in_ritardo", False)
                bars.append({
                    "id": p.id, "start_idx": start_idx, "span": span,
                    "label": _job_label(p), "classe": classe, "colore": colore,
                    "urgente": classe == "urg", "conflitto": False, "ritardo": ritardo,
                    "turno": p.turno, "ore": p.ore, "qta": p.qta,
                    "stima": stima, "ore_stima": round(ore, 1) if stima else None,
                    "famiglia": famiglia, "cliente": cliente,
                })
                leg_count[colore] += 1
                if colore not in leg_label:
                    leg_label[colore] = (cliente or famiglia or _job_label(p))[:22]
            def _riga(turni_inclusi, label, sub):
                sub_bars = [b for b in bars if b["turno"] in turni_inclusi]
                if filtro_lavori and not sub_bars:
                    return None
                nlanes = _assign_lanes(sub_bars)
                conf = _segna_conflitti(sub_bars)
                for b in sub_bars:
                    b["top"] = b["lane"] * lane_h + 6
                turno_riga = turni_inclusi[0] if len(turni_inclusi) == 1 else Pianificazione.TURNO_GIORNO
                return {
                    "macchina": m, "turno": turno_riga, "turno_label": label, "sub": sub,
                    "bars": sub_bars,
                    "sat": sat["per_macchina"].get(m.id) if not sub else None,
                    "row_h": nlanes * lane_h + 12, "conflitto": conf,
                }

            if mostra_turni:
                rows = [_riga([Pianificazione.TURNO_GIORNO], "1° turno", False)]
                if m.ha_secondo_turno:
                    rows.append(_riga([Pianificazione.TURNO_T2], "2° turno", True))
                if m.ha_turno_notte:
                    rows.append(_riga([Pianificazione.TURNO_NOTTE], "notturno", True))
            else:
                # Default: 1°+2° turno UNITI; notturno su riga separata se presente.
                rows = [_riga([Pianificazione.TURNO_GIORNO, Pianificazione.TURNO_T2], "", False)]
                if m.ha_turno_notte:
                    rows.append(_riga([Pianificazione.TURNO_NOTTE], "notturno", True))
            righe.extend(r for r in rows if r is not None)
        if righe:
            sezioni.append({
                "categoria": cat, "label": cat_label.get(cat, cat),
                "righe": righe, "sat": sat["per_reparto"].get(cat),
            })

    # bande settimana (per orientamento sulla timeline)
    settimane = []
    if giorni:
        cur = giorni[0].isocalendar()[1]
        cnt = 0
        for g in giorni:
            wk = g.isocalendar()[1]
            if wk != cur:
                settimane.append({"label": f"Sett. {cur:02d}", "giorni": cnt})
                cur, cnt = wk, 0
            cnt += 1
        settimane.append({"label": f"Sett. {cur:02d}", "giorni": cnt})

    clienti = sorted(c for c in Commessa.objects.values_list("cliente", flat=True).distinct() if c)
    commesse_legenda = [
        {"colore": c, "label": leg_label.get(c, "")} for c, _n in leg_count.most_common(14)
    ]
    ctx = {
        "giorni": giorni, "sezioni": sezioni, "oggi": oggi, "start": start, "giorni_n": giorni_n,
        "cell_w": cell_w, "lane_h": lane_h, "settimane": settimane,
        "prev_start": _inizio_finestra_prec(start, giorni_n).isoformat(),
        "next_start": (fine + timedelta(days=1)).isoformat(),
        "sat_totale": sat["totale"],
        "oggi_idx": idx_map.get(oggi),
        "categorie": Macchina.CATEGORIA_CHOICES,
        "finestra_opzioni": [7, 14, 21, 28, 42, 56],
        "clienti": clienti,
        "famiglie": list(FamigliaPezzo.objects.values("id", "nome").order_by("nome")),
        "f_cat": f_cat, "f_cliente": f_cliente, "f_fam": f_fam, "mostra_turni": mostra_turni,
        "colore_mode": "stato" if request.GET.get("colore") == "stato" else "commessa",
        "commesse_legenda": commesse_legenda,
        "ha_undo": bool(request.session.get("gcm_undo")),
    }
    return render(request, "gestione_carichi_macchina/gantt.html", ctx)


def _stesso_pool(p, target) -> bool:
    """True se macchina sorgente e destinazione condividono un pool_equivalenza per la famiglia del lavoro."""
    from .models import MacchinaFamigliaAffinita

    if not p.famiglia_id:
        return False
    pools = set(
        MacchinaFamigliaAffinita.objects.filter(
            macchina_id=p.macchina_id, famiglia_id=p.famiglia_id
        ).exclude(pool_equivalenza="").values_list("pool_equivalenza", flat=True)
    )
    if not pools:
        return False
    return MacchinaFamigliaAffinita.objects.filter(
        macchina_id=target.id, famiglia_id=p.famiglia_id, pool_equivalenza__in=pools
    ).exists()


@login_required
@require_POST
def reschedule(request):
    """Sposta una pianificazione nel tempo e/o su un'altra macchina (drag-to-reschedule).

    - `giorni_delta`: spostamento in giorni.
    - `cascata=1`: sposta dello stesso delta anche i lavori successivi sulla STESSA macchina
      (solo per spostamenti temporali, non con cambio macchina).
    - `macchina_dest`: nuova macchina; se incompatibile (categoria diversa e fuori pool)
      e senza `forza=1`, ritorna reason=incompatibile per far decidere all'operatore.
    Snapshot dello stato precedente in sessione per l'undo.
    """
    from django.db import transaction

    from .models import Macchina, Pianificazione

    pid = _as_int(request.POST.get("pianificazione_id"))
    delta = _as_int(request.POST.get("giorni_delta"), 0) or 0
    cascata = request.POST.get("cascata") in ("1", "true", "on")
    mac_dest = _as_int(request.POST.get("macchina_dest"))
    forza = request.POST.get("forza") in ("1", "true", "on")
    if not pid:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    p = get_object_or_404(Pianificazione.objects.select_related("macchina"), pk=pid)
    sposta_macchina = bool(mac_dest and mac_dest != p.macchina_id)
    if delta == 0 and not sposta_macchina:
        return JsonResponse({"ok": False, "error": "Parametri non validi."}, status=400)

    target = None
    if sposta_macchina:
        target = get_object_or_404(Macchina.objects.select_related("asset"), pk=mac_dest)
        eleggibile = (target.categoria == p.macchina.categoria) or _stesso_pool(p, target)
        if not eleggibile and not forza:
            return JsonResponse({
                "ok": False, "reason": "incompatibile",
                "error": f"{target.codice} è di categoria diversa ({target.get_categoria_display()}). Spostare comunque?",
            }, status=200)

    with transaction.atomic():
        if cascata and not sposta_macchina:
            # Cascata SOLO sullo stesso turno: spostare un lavoro del 1° turno non deve
            # toccare 2° turno / notturno (sono linee indipendenti).
            successivi = list(
                Pianificazione.objects.select_for_update().filter(
                    macchina_id=p.macchina_id, turno=p.turno, data__gte=p.data
                ).exclude(pk=p.pk)
            )
            affected = [p] + successivi
        else:
            affected = [p]
        snap = [
            {"id": j.id, "macchina_id": j.macchina_id, "data": j.data.isoformat()}
            for j in affected
        ]
        for job in affected:
            job.data = job.data + timedelta(days=delta)
            if sposta_macchina and job.pk == p.pk:
                job.macchina = target
            job.fonte = Pianificazione.FONTE_MANUALE
            job.save(update_fields=["data", "macchina", "fonte", "updated_at"])

    request.session["gcm_undo"] = {"snap": snap}
    request.session.modified = True
    return JsonResponse({
        "ok": True, "id": p.id, "spostati": len(affected),
        "cascata": cascata and not sposta_macchina, "macchina": sposta_macchina,
    })


@login_required
@require_POST
def reschedule_undo(request):
    """Annulla l'ultimo spostamento: ripristina macchina e data dallo snapshot in sessione."""
    from django.db import transaction

    from .models import Pianificazione

    undo = request.session.get("gcm_undo")
    snap = undo.get("snap") if undo else None
    if not snap:
        return JsonResponse({"ok": False, "error": "Niente da annullare."}, status=400)
    with transaction.atomic():
        for s in snap:
            Pianificazione.objects.filter(pk=s["id"]).update(
                macchina_id=s["macchina_id"], data=_parse_date(s["data"])
            )
    del request.session["gcm_undo"]
    request.session.modified = True
    return JsonResponse({"ok": True, "annullati": len(snap)})


def _famiglia_da_param(par: str):
    from .models import FamigliaPezzo

    par = (par or "").strip()
    if par.isdigit():
        return FamigliaPezzo.objects.filter(pk=int(par)).first()
    if par:
        return FamigliaPezzo.objects.filter(nome__iexact=par).first()
    return None


def _suggerimenti_macchina(fam, fase: str = "") -> list[dict]:
    from .models import Macchina
    from .previsioni import (
        costruisci_indice_carico,
        costruisci_indice_macchine,
        costruisci_indice_macchine_fase,
        costruisci_indice_recency,
        costruisci_indice_stato,
        prevedi_macchina,
    )

    # Suggerimento PESATO: affinita' storica (per FASE quando indicata) + recency + carico
    # attuale, escludendo le macchine in guasto/manutenzione. Mantiene prob/occorrenze.
    ranked = prevedi_macchina(
        fam.id,
        costruisci_indice_macchine(),
        fase=fase or None,
        freq_per_famiglia_fase=costruisci_indice_macchine_fase() if fase else None,
        recency_per_coppia=costruisci_indice_recency(),
        carico_per_macchina=costruisci_indice_carico(),
        stato_per_macchina=costruisci_indice_stato(),
    )[:5]
    macs = {
        m.id: m for m in
        Macchina.objects.filter(id__in=[r["macchina_id"] for r in ranked]).select_related("asset")
    }
    return [
        {"macchina_id": r["macchina_id"],
         "codice": macs[r["macchina_id"]].codice if r["macchina_id"] in macs else "",
         "occorrenze": r["occorrenze"], "prob": r["prob"],
         "score": r.get("score"), "saturazione": r.get("saturazione"),
         "componenti": r.get("componenti")}
        for r in ranked
    ]


def _righe_suggerimento_display(sugg: list[dict], macchina_corrente: int) -> list[dict]:
    """Trasforma i suggerimenti in righe pronte per il template (percentuali + classe carico)."""
    righe = []
    for s in sugg:
        score = s.get("score")
        sat = s.get("saturazione")
        comp = s.get("componenti") or {}
        if sat is None:
            sat_classe = ""
        elif sat >= 0.9:
            sat_classe = "satura"
        elif sat >= 0.6:
            sat_classe = "media"
        else:
            sat_classe = "libera"
        base = score if score is not None else s.get("prob", 0)
        righe.append({
            "macchina_id": s["macchina_id"],
            "codice": s.get("codice") or s["macchina_id"],
            "score_pct": round(float(base) * 100),
            "occorrenze": s.get("occorrenze"),
            "sat_pct": round(float(sat) * 100) if sat is not None else None,
            "sat_classe": sat_classe,
            "freq_pct": round(float(comp.get("freq", 0)) * 100),
            "rec_pct": round(float(comp.get("recency", 0)) * 100),
            "lib_pct": round(float(comp.get("carico_libero", 0)) * 100),
            "is_corrente": s["macchina_id"] == macchina_corrente,
        })
    return righe


@login_required
def cella_suggerimento(request):
    """Box HTMX (read-only): macchine consigliate per la famiglia digitata nella cella.

    Mostra score (barra) e carico (colore), evidenziando la macchina della cella.
    Ritorna frammento vuoto se la famiglia non e' riconosciuta dal testo.
    """
    testo = (request.GET.get("testo") or "").strip()
    try:
        macchina_corrente = int(request.GET.get("macchina") or 0)
    except (TypeError, ValueError):
        macchina_corrente = 0
    fam = _match_famiglia(testo) if testo else None
    if not fam:
        return HttpResponse("")
    fase = (request.GET.get("fase") or "").strip()
    righe = _righe_suggerimento_display(_suggerimenti_macchina(fam, fase=fase), macchina_corrente)
    ctx = {
        "famiglia": fam.nome,
        "fase": fase,
        "righe": righe,
        "ha_corrente": bool(macchina_corrente),
        "corrente_in_lista": any(r["is_corrente"] for r in righe),
    }
    return render(request, "gestione_carichi_macchina/partials/_suggerimento_macchina.html", ctx)


@login_required
def api_suggerimento_macchina(request):
    """Predice (storico) le macchine piu' probabili per una famiglia. FBV + JsonResponse."""
    fam = _famiglia_da_param(request.GET.get("famiglia"))
    if not fam:
        return JsonResponse({"ok": False, "error": "Famiglia non trovata."}, status=404)
    return JsonResponse({"ok": True, "famiglia": fam.nome, "suggerimenti": _suggerimenti_macchina(fam)})


@login_required
def api_spiega_macchina(request):
    """Suggerimento macchina + SPIEGAZIONE in linguaggio naturale (Fase 5, LLM via gateway).

    L'LLM spiega i numeri già calcolati; se non disponibile, `spiegazione` è null (fail-safe)
    e restano i suggerimenti deterministici.
    """
    from .spiegazioni import contesto_suggerimento_macchina, spiega

    fam = _famiglia_da_param(request.GET.get("famiglia"))
    if not fam:
        return JsonResponse({"ok": False, "error": "Famiglia non trovata."}, status=404)
    sugg = _suggerimenti_macchina(fam)
    spiegazione = None
    if sugg:
        prompt, contesto = contesto_suggerimento_macchina(fam.nome, sugg)
        spiegazione = spiega(prompt, contesto, timeout=30)
    return JsonResponse({
        "ok": True, "famiglia": fam.nome, "suggerimenti": sugg, "spiegazione": spiegazione,
    })
