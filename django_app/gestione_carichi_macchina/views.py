"""Viste del modulo Gestione Carichi Macchina.

Vista PRIMARIA: la matrice "Excel" (macchine x giorni), resa server-side e con
celle editabili inline via HTMX. L'API JSON (FBV + JsonResponse, NON django-ninja)
alimenta la vista Gantt (Passo 4).

ACL: per ora @login_required; il binding ACL v2 + voce di menu arriva al Passo 6.
"""
from __future__ import annotations

import hashlib
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


def _puo_modificare(request) -> bool:
    """True se l'utente ha il permesso canonico di MODIFICA del piano.

    L'enforcement principale è il binding route->permesso (middleware ACL v2, strict in
    prod); questo serve a riflettere il permesso nella UI (nascondere i comandi di scrittura
    a chi ha solo la vista). Fail-safe: in assenza del sottosistema ACL ricade su
    is_authenticated (come prima), così dev/test restano usabili.
    """
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        # Risolve l'identità legacy (ruolo) come fa il middleware ACL: senza di essa
        # evaluate_permission_code_access non può leggere i grant di ruolo e negherebbe
        # la modifica a tutti i non-superuser (caporeparto/amministrazione compresi).
        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return bool(evaluate_permission_code_access(
            permission_code="gestione_carichi_macchina.piano.edit",
            legacy_user=legacy_user,
            django_user=request.user,
        ).get("allowed"))
    except Exception:
        return bool(getattr(request, "user", None) and request.user.is_authenticated)


def _log_azione(request, azione, *, macchina=None, pianificazione_id=None, descrizione=""):
    """Registra un'azione sul piano (audit trail). Fail-safe: non deve mai rompere l'operazione."""
    from .models import RegistroAzione

    try:
        u = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        RegistroAzione.objects.create(
            utente=u, utente_nome=(u.get_username() if u else ""),
            azione=azione, macchina=macchina,
            macchina_cod=(getattr(macchina, "codice", "") if macchina else ""),
            pianificazione_id=pianificazione_id, descrizione=(descrizione or "")[:255],
        )
    except Exception:
        pass


def _giorni_lavorativi(start: date, n: int) -> list[date]:
    """n giorni lavorativi (lun-ven) a partire da start (weekend esclusi, come nel foglio)."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _span_lavorativi(ore, ore_giorno) -> int:
    """Durata in giorni LAVORATIVI di un lavoro: ceil(ore / ore_giorno), minimo 1."""
    if not ore or not ore_giorno or ore_giorno <= 0:
        return 1
    return max(1, ceil(float(ore) / float(ore_giorno)))


def _fine_lavorativa_excl(inizio: date, span_lav: int) -> date:
    """Data di fine ESCLUSIVA contando `span_lav` giorni lavorativi da `inizio`."""
    giorni = _giorni_lavorativi(inizio, max(1, span_lav))
    return giorni[-1] + timedelta(days=1)


def _sovrapposizioni(macchina, turno, data, ore, escludi_id=None):
    """Altri lavori sulla stessa macchina che CONFLIGGONO col lavoro dato.

    Conflitto = le **fasce orarie** dei due turni si intersecano (1°/2° non si toccano,
    ma 1°+Entrambi, *+H24, Notte+H24 sì) **e** gli intervalli in giorni lavorativi si
    sovrappongono. Usato per la conferma all'inserimento/spostamento; esclude i completati.
    """
    from .models import Pianificazione

    fasce = Pianificazione.fasce_di(turno)
    span = _span_lavorativi(ore, macchina.ore_giorno_per_turno(turno))
    fine = _fine_lavorativa_excl(data, span)
    qs = (
        Pianificazione.objects.filter(macchina=macchina, data__lt=fine)
        .exclude(stato=Pianificazione.STATO_COMPLETATA)
        .select_related("famiglia")
    )
    if escludi_id:
        qs = qs.exclude(pk=escludi_id)
    out = []
    for o in qs:
        if not (fasce & Pianificazione.fasce_di(o.turno)):
            continue  # fasce disgiunte (es. 1° vs 2°): nessun conflitto
        o_fine = _fine_lavorativa_excl(
            o.data, _span_lavorativi(float(o.ore) if o.ore else None,
                                     macchina.ore_giorno_per_turno(o.turno))
        )
        if o.data < fine and data < o_fine:  # intersezione temporale
            out.append(o)
    return out


def _primo_slot_libero(macchina, data, ore, turno):
    """Primo slot senza conflitto sulla macchina: prima gli altri turni consentiti nello
    STESSO giorno, poi lo stesso turno nei giorni lavorativi successivi (orizzonte 20gg).

    Ritorna {turno, data, tipo, label} o None se non trova nulla nell'orizzonte.
    """
    from .models import Pianificazione

    turni_lbl = dict(Pianificazione.TURNO_CHOICES)
    # 1) stesso giorno, un altro turno che la macchina può fare e con fasce libere
    for t in macchina.turni_consentiti():
        if t == turno:
            continue
        if not _sovrapposizioni(macchina, t, data, ore):
            return {"turno": t, "data": data.isoformat(), "tipo": "turno",
                    "label": f"{turni_lbl.get(t, t)}, stesso giorno"}
    # 2) stesso turno, primo giorno lavorativo successivo libero
    for g in _giorni_lavorativi(data + timedelta(days=1), 20):
        if not _sovrapposizioni(macchina, turno, g, ore):
            return {"turno": turno, "data": g.isoformat(), "tipo": "giorno",
                    "label": f"{turni_lbl.get(turno, turno)} dal {g.strftime('%d/%m')}"}
    return None


def _piano_slittamento(macchina_eff, p, nuova_data, coda=False):
    """Calcola (senza toccare il DB) i movimenti necessari per spostare `p` a
    `nuova_data` sulla macchina `macchina_eff`.

    Con coda=False slitta SOLO i conflitti che il drag **crea**, del minimo
    necessario (in giorni lavorativi). In particolare:

    * un lavoro che era GIÀ sovrapposto a `p` prima dello spostamento non viene
      toccato: il drag non ha creato quel conflitto, non tocca a lui risolverlo
      (nel foglio reale i lavori lunghi si sovrappongono già fra loro);
    * NESSUNA catena: se uno slittato finisce sopra un terzo lavoro, il terzo
      resta dov'è e il Gantt lo segnala come conflitto (⚠). Il modello tollera i
      conflitti — segnalarli è compito della vista, non della pianificazione.

    Ritorna lista ordinata di dict {id, etichetta, macchina, da, a, irrisolto};
    la prima riga è sempre `p`.
    """
    def _etichetta(job):
        return (getattr(job, "testo_originale", "") or
                (job.famiglia.nome if getattr(job, "famiglia_id", None) else "") or
                "lavoro")

    def _fine(inizio, job):
        ore = float(job.ore) if job.ore else None
        span = _span_lavorativi(ore, macchina_eff.ore_giorno_per_turno(job.turno))
        return _fine_lavorativa_excl(inizio, span)

    def _primo_lav(da_data):
        return _giorni_lavorativi(da_data, 1)[0]

    piano = [{"id": p.id, "etichetta": _etichetta(p), "macchina": macchina_eff.codice,
              "da": p.data, "a": nuova_data, "irrisolto": False}]

    if coda:
        from .models import Pianificazione
        delta_lav = _delta_giorni_lavorativi(p.data, nuova_data)
        # Stessa regola di fascia-oraria di _confligge/_sovrapposizioni: la coda deve
        # includere anche i turni DIVERSI ma la cui fascia si interseca con quella di p
        # (es. 'entrambi' tocca sia 'giorno' che 't2'), non solo il match esatto.
        fasce_p = Pianificazione.fasce_di(p.turno)
        turni_compatibili = [
            t for t, _ in Pianificazione.TURNO_CHOICES if Pianificazione.fasce_di(t) & fasce_p
        ]
        successivi = (Pianificazione.objects
                      .filter(macchina=macchina_eff, turno__in=turni_compatibili, data__gte=p.data)
                      .exclude(pk=p.pk)
                      .exclude(stato=Pianificazione.STATO_COMPLETATA)
                      .order_by("data", "id"))
        for o in successivi:
            piano.append({"id": o.id, "etichetta": _etichetta(o),
                          "macchina": macchina_eff.codice,
                          "da": o.data, "a": _sposta_giorni_lavorativi(o.data, delta_lav),
                          "irrisolto": False})
        return piano

    from .models import Pianificazione

    attivi = list(
        Pianificazione.objects.filter(macchina=macchina_eff)
        .exclude(stato=Pianificazione.STATO_COMPLETATA)
        .exclude(pk=p.pk)
        .select_related("famiglia")
    )

    def _confligge(p_data, o):
        # Stesse regole di _sovrapposizioni: fasce orarie intersecanti + sovrapposizione
        # degli intervalli in giorni lavorativi, ma su una data-inizio ipotetica di `p`.
        if not (Pianificazione.fasce_di(p.turno) & Pianificazione.fasce_di(o.turno)):
            return False
        return p_data < _fine(o.data, o) and o.data < _fine(p_data, p)

    # Conflitti che esistevano GIÀ nella posizione di partenza: non li ha creati il drag,
    # quindi restano dove sono. (Se il lavoro cambia macchina non ce n'è nessuno.)
    gia_in_conflitto = (
        {o.id for o in attivi if _confligge(p.data, o)}
        if p.macchina_id == macchina_eff.id else set()
    )
    nuovi = sorted(
        (o for o in attivi if o.id not in gia_in_conflitto and _confligge(nuova_data, o)),
        key=lambda o: (o.data, o.id),
    )

    # Ogni conflitto nuovo va dopo la fine di `p`, impilato in sequenza sugli altri
    # slittati (così non si sovrappongono fra loro). Nessuna propagazione oltre.
    cursor = _primo_lav(_fine(nuova_data, p))
    for o in nuovi:
        piano.append({"id": o.id, "etichetta": _etichetta(o), "macchina": macchina_eff.codice,
                      "da": o.data, "a": cursor, "irrisolto": False})
        cursor = _primo_lav(_fine(cursor, o))
    return piano


def _inizio_finestra_prec(start: date, n: int) -> date:
    """Inizio della finestra precedente: n giorni lavorativi prima di start."""
    ws: list[date] = []
    d = start - timedelta(days=1)
    while len(ws) < n:
        if d.weekday() < 5:
            ws.append(d)
        d -= timedelta(days=1)
    return ws[-1]


def _giorni_lavorativi_indietro(d: date, n: int) -> date:
    """Data n giorni lavorativi PRIMA di d (d escluso). n<=0 → d."""
    if n <= 0:
        return d
    out: list[date] = []
    cur = d - timedelta(days=1)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur)
        cur -= timedelta(days=1)
    return out[-1]


def _giorni_lavorativi_avanti(d: date, n: int) -> date:
    """Data n giorni lavorativi DOPO d (d escluso). n<=0 → d. Simmetrica a
    `_giorni_lavorativi_indietro`."""
    if n <= 0:
        return d
    out: list[date] = []
    cur = d + timedelta(days=1)
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out[-1]


def _delta_giorni_lavorativi(a: date, b: date) -> int:
    """Numero di giorni LAVORATIVI da percorrere per andare da `a` a `b` (segno secondo
    la direzione; 0 se coincidono). Presuppone a e b giorni lavorativi: i weekend
    attraversati non contano come passi."""
    if b == a:
        return 0
    passo = 1 if b > a else -1
    d, n = a, 0
    while d != b:
        d += timedelta(days=passo)
        if d.weekday() < 5:
            n += passo
    return n


def _sposta_giorni_lavorativi(d: date, n: int) -> date:
    """Sposta `d` di `n` giorni LAVORATIVI (n può essere negativo), saltando i weekend."""
    if n > 0:
        return _giorni_lavorativi_avanti(d, n)
    if n < 0:
        return _giorni_lavorativi_indietro(d, -n)
    return d


def _finestra(request):
    """Finestra in GIORNI LAVORATIVI (no sabato/domenica): (start, giorni_n, [giorni]).

    Senza ?start esplicito la finestra parte qualche giorno lavorativo PRIMA di oggi
    (buffer "all'indietro" ∝ ampiezza finestra), così il Gantt mostra di default anche il
    recente passato e si può guardare/scrollare indietro senza cambiare periodo. Con uno
    ?start esplicito (navigazione ‹/›) la finestra è esatta.
    """
    oggi = timezone.localdate()
    giorni_n = _as_int(request.GET.get("giorni"), _GIORNI_DEFAULT) or _GIORNI_DEFAULT
    giorni_n = max(_GIORNI_MIN, min(giorni_n, _GIORNI_MAX))
    start = _parse_date(request.GET.get("start"))
    if start is None:
        backward = max(2, min(5, giorni_n // 4))  # ~1/4 della finestra nel passato
        start = _giorni_lavorativi_indietro(oggi, backward)
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
                # «entrambi»/«H24» (multi-fascia) si vedono nella riga 1° turno.
                seq = [([Pianificazione.TURNO_GIORNO, Pianificazione.TURNO_ENTRAMBI,
                         Pianificazione.TURNO_H24], Pianificazione.TURNO_GIORNO, "1° turno", False)]
                if m.ha_secondo_turno:
                    seq.append(([Pianificazione.TURNO_T2], Pianificazione.TURNO_T2, "2° turno", True))
                if m.ha_turno_notte:
                    seq.append(([Pianificazione.TURNO_NOTTE], Pianificazione.TURNO_NOTTE, "notturno", True))
                for turni_inc, turno, label, sub in seq:
                    righe.append({
                        "macchina": m, "turno": turno, "turno_label": label, "sub": sub,
                        "celle": _celle(turni_inc), "ferma": ferma,
                    })
            else:
                # Default: turni diurni (1°/2°/entrambi/H24) UNITI in una riga (look
                # familiare); il notturno resta su riga separata solo se la macchina lo ha.
                righe.append({
                    "macchina": m, "turno": Pianificazione.TURNO_GIORNO, "turno_label": "",
                    "sub": False, "ferma": ferma,
                    "celle": _celle(list(Pianificazione.TURNI_DIURNI)),
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
        # Turni consentiti per macchina (picker del modale "+ Aggiungi" coerente con la
        # capability) + label dei turni.
        "turno_choices": Pianificazione.TURNO_CHOICES,
        "macchine_turni": {m.id: m.turni_consentiti() for m in macchine},
        "can_edit": _puo_modificare(request),
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
        n, _ = Pianificazione.objects.filter(pk=job_id, macchina=macchina).delete()
        if n:
            _log_azione(request, "elimina", macchina=macchina, pianificazione_id=job_id,
                        descrizione=f"Eliminato lavoro #{job_id}")
        return _render_cella(request, macchina, turno, data)

    testo = (request.POST.get("testo") or "").strip()
    if not testo:
        # niente testo: se esiste e si svuota, elimina; altrimenti no-op
        if job_id:
            n, _ = Pianificazione.objects.filter(pk=job_id, macchina=macchina).delete()
            if n:
                _log_azione(request, "elimina", macchina=macchina, pianificazione_id=job_id,
                            descrizione=f"Svuotato lavoro #{job_id}")
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
        _log_azione(request, "modifica", macchina=macchina, pianificazione_id=job_id,
                    descrizione=f"{turno} {data.isoformat()} · {testo}")
    else:
        # Blocco "doppio inserimento": un doppio submit / doppio click non deve creare
        # due lavori identici. Se esiste gia' un lavoro con stessa macchina/turno/giorno e
        # stesso testo, non duplicare (idempotente); l'eventuale aggiornamento passa dal
        # ramo job_id sopra.
        esiste = Pianificazione.objects.filter(
            macchina=macchina, turno=turno, data=data, testo_originale=testo
        ).exists()
        if not esiste:
            nuovo = Pianificazione.objects.create(macchina=macchina, turno=turno, data=data, **valori)
            _log_azione(request, "crea", macchina=macchina, pianificazione_id=nuovo.id,
                        descrizione=f"{turno} {data.isoformat()} · {testo}")
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


@login_required
def api_pianificazione_dettaglio(request, pk):
    """Dettaglio di una pianificazione per il pannello laterale del Gantt (click su barra)."""
    from .models import Pianificazione

    p = get_object_or_404(
        Pianificazione.objects.select_related("macchina__asset", "famiglia", "commessa"), pk=pk
    )
    return JsonResponse({"ok": True, "p": {
        "id": p.id,
        "macchina_id": p.macchina_id,
        "macchina": p.macchina.codice,
        "data": p.data.isoformat(),
        "turno": p.turno,
        "turno_label": p.get_turno_display(),
        "testo": p.testo_originale or "",
        "famiglia": p.famiglia.nome if p.famiglia_id else "",
        "qta": p.qta if p.qta is not None else "",
        "ore": float(p.ore) if p.ore is not None else "",
        "stato": p.stato,
        "fase": p.fase,
        "cliente": p.commessa.cliente if p.commessa_id else "",
        "commessa": p.commessa.numero if p.commessa_id else "",
        "consegna": p.commessa.data_consegna.isoformat() if (p.commessa_id and p.commessa.data_consegna) else "",
    }})


def _layout_bande(bars: list[dict], lane_h: int):
    """Dispone le barre in corsie per FASCIA oraria (1°=G, 2°=T, notte=N) e marca i conflitti.

    Le fasce sono impilate verticalmente (G in alto, poi T, poi N); una banda compare solo
    se almeno una barra la usa. I lavori multi-fascia (Entrambi/H24) diventano barre **alte**
    più corsie. Più lavori che si contendono la stessa fascia+giorno finiscono in "blocchi"
    impilati (e marcati conflitto). Ritorna (n_lane_totali, bande) dove `bande` elenca le
    etichette di fascia presenti col loro offset verticale (chip a sinistra della traccia).
    """
    from .models import Pianificazione

    fasce_bar = {
        id(b): [f for f in Pianificazione.FASCE_ORDINE if f in Pianificazione.fasce_di(b["turno"])]
        for b in bars
    }
    presenti = [f for f in Pianificazione.FASCE_ORDINE if any(f in fasce_bar[id(b)] for b in bars)]
    if not presenti:
        presenti = [Pianificazione.FASCIA_G]
    pos = {f: i for i, f in enumerate(presenti)}
    nb = len(presenti)

    blocchi: list[dict] = []  # ogni blocco: {fascia: indice-giorno di fine occupazione}
    for b in sorted(bars, key=lambda x: x["start_idx"]):
        ff = fasce_bar[id(b)] or [presenti[0]]
        top_i = min(pos[f] for f in ff)
        bot_i = max(pos[f] for f in ff)
        need = presenti[top_i:bot_i + 1]
        scelto = None
        for bi, blk in enumerate(blocchi):
            if all(b["start_idx"] >= blk.get(f, -1) for f in need):
                scelto = bi
                break
        if scelto is None:
            blocchi.append({})
            scelto = len(blocchi) - 1
        for f in need:
            blocchi[scelto][f] = b["start_idx"] + b["span"]
        b["lane"] = scelto * nb + top_i
        b["lanespan"] = bot_i - top_i + 1
        b["top"] = b["lane"] * lane_h + 6

    # Conflitti: fasce intersecanti + sovrapposizione temporale (N piccolo, O(n^2)).
    for i, a in enumerate(bars):
        fa = set(fasce_bar[id(a)])
        for c in bars[i + 1:]:
            if (fa & set(fasce_bar[id(c)])
                    and a["start_idx"] < c["start_idx"] + c["span"]
                    and c["start_idx"] < a["start_idx"] + a["span"]):
                a["conflitto"] = True
                c["conflitto"] = True

    etich = {Pianificazione.FASCIA_G: "1°", Pianificazione.FASCIA_T: "2°", Pianificazione.FASCIA_N: "Notte"}
    bande = [{"label": etich.get(f, f), "top": i} for i, f in enumerate(presenti)] if nb > 1 else []
    return max(1, len(blocchi) * nb), bande


@login_required
def vista_gantt(request):
    """Gantt (stessa sorgente dati della vista Excel): barre per pianificazione,
    raggruppate per macchina/sezione, con saturazione, filtri, zoom, corsie e
    drag-to-reschedule."""
    from .integrations import assenze_overlay_for_assets
    from .models import Commessa, FamigliaPezzo, Macchina, Pianificazione
    from .previsioni import costruisci_indici, prevedi_ore, rischio_ritardo
    from .tasks import saturazione_finestra

    start, giorni_n, giorni = _finestra(request)
    oggi = timezone.localdate()
    fine = giorni[-1]
    idx_map = {g: i for i, g in enumerate(giorni)}  # data -> colonna (in giorni lavorativi)
    oggi_col = idx_map.get(oggi)
    cell_w = max(24, min(_as_int(request.GET.get("cw"), 38) or 38, 72))
    lane_h = 30
    # Intestazione date arricchita (sigla giorno + numero), come nel design Gantt.
    _abbr = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"]
    giorni_hdr = [
        {"d": g, "abbr": _abbr[g.weekday()], "num": g.day,
         "monday": g.weekday() == 0, "we": g.weekday() >= 5, "oggi": g == oggi}
        for g in giorni
    ]

    f_cat = request.GET.get("cat") or ""
    f_cliente = (request.GET.get("cliente") or "").strip()
    f_fam = _as_int(request.GET.get("fam"))

    macchine_qs = Macchina.objects.filter(attivo=True).select_related("asset")
    if f_cat:
        macchine_qs = macchine_qs.filter(categoria=f_cat)
    macchine = list(macchine_qs.order_by("categoria", "ordine_sezione", "id"))

    # Overlay "abilitati assenti" (Skill Matrix × assenze): per asset → {giorno: info}.
    # Fail-safe e additivo: {} finché la baseline skill matrix non è popolata.
    assenze_overlay = assenze_overlay_for_assets([m.asset_id for m in macchine], giorni)

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
    leg_fam_count: Counter = Counter()   # legenda famiglie: colore -> #barre
    leg_fam_label: dict[str, str] = {}   # colore -> nome famiglia

    sezioni = []
    for cat in _CAT_ORDER:
        ms = by_cat.get(cat)
        if not ms:
            continue
        righe = []
        for m in ms:
            bars = []
            for p in by_mac.get(m.id, []):
                start_idx = idx_map.get(p.data)
                if start_idx is None:
                    continue
                # Ore/giorno secondo il TURNO del lavoro: «entrambi» e «H24» fanno entrare
                # piu' ore al giorno, quindi la barra dura meno giorni a parita' di ore.
                ogg = m.ore_giorno_per_turno(p.turno)
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
                colore_fam = _colore_commessa(famiglia := (p.famiglia.nome if p.famiglia_id else ""))
                cliente = p.commessa.cliente if p.commessa_id else ""
                # rischio ritardo: fine prevista (durata) oltre la consegna della commessa
                ritardo = False
                if p.commessa_id and p.commessa.data_consegna and ore:
                    ritardo = rischio_ritardo(
                        data_inizio=p.data, ore_previste=ore, ore_giorno=ogg,
                        data_consegna=p.commessa.data_consegna,
                    ).get("in_ritardo", False)
                # Avanzamento derivato (no campo esplicito nel modello): completata=100%;
                # in corso = quota temporale se "oggi" cade dentro la barra, altrimenti 0.
                if p.stato == Pianificazione.STATO_COMPLETATA:
                    prog = 100
                elif (p.stato == Pianificazione.STATO_IN_CORSO and oggi_col is not None
                      and start_idx <= oggi_col < start_idx + span):
                    prog = max(5, min(100, round((oggi_col - start_idx + 1) / span * 100)))
                else:
                    prog = 0
                bars.append({
                    "id": p.id, "start_idx": start_idx, "span": span,
                    "label": _job_label(p), "classe": classe,
                    "colore": colore, "colore_fam": colore_fam,
                    "urgente": classe == "urg", "conflitto": False, "ritardo": ritardo,
                    "turno": p.turno, "turno_label": p.get_turno_display(),
                    "ore": p.ore, "qta": p.qta, "prog": prog,
                    "stima": stima, "ore_stima": round(ore, 1) if stima else None,
                    "famiglia": famiglia, "cliente": cliente,
                })
                leg_count[colore] += 1
                if colore not in leg_label:
                    leg_label[colore] = (cliente or famiglia or _job_label(p))[:22]
                leg_fam_count[colore_fam] += 1
                if colore_fam not in leg_fam_label:
                    leg_fam_label[colore_fam] = famiglia or "—"
            try:
                from .integrations import kickoff_tasks_for_asset
                m_ko = kickoff_tasks_for_asset(m.asset_id, start, fine)
            except Exception:
                m_ko = []
            # Milestone derivate (rombi sulla timeline): attivita KICK-OFF (data inizio)
            # + date di consegna delle commesse pianificate sulla macchina nella finestra.
            milestones = []
            for k in m_ko:
                idx = idx_map.get(k.get("start"))
                if idx is not None:
                    milestones.append({"start_idx": idx, "label": k.get("title") or "KICK-OFF", "kind": "kickoff"})
            consegne_viste: dict = {}
            for p in by_mac.get(m.id, []):
                if p.commessa_id and p.commessa.data_consegna and p.commessa.data_consegna in idx_map:
                    consegne_viste.setdefault(
                        p.commessa.data_consegna, p.commessa.cliente or p.commessa.numero or "")
            for d_cons, lbl in consegne_viste.items():
                milestones.append({"start_idx": idx_map[d_cons],
                                   "label": ("Consegna " + lbl).strip(), "kind": "consegna"})

            # Marker "abilitati assenti" per giorno (Skill Matrix × assenze). Vuoto se
            # la baseline skill matrix non è popolata: overlay completamente additivo.
            assenze_markers = []
            for g, info in (assenze_overlay.get(m.asset_id) or {}).items():
                idx = idx_map.get(g)
                if idx is None:
                    continue
                nomi = info.get("nomi") or []
                parts = [f"{nome} ({tipo})" for nome, tipo in nomi[:6]]
                if len(nomi) > 6:
                    parts.append(f"+{len(nomi) - 6} altri")
                assenze_markers.append({
                    "start_idx": idx, "n": info["n"], "tot": info["tot"], "sev": info["sev"],
                    "riepilogo": "%d di %d abilitati assenti il %s · %s" % (
                        info["n"], info["tot"], g.strftime("%d/%m"), ", ".join(parts)),
                })
            assenze_markers.sort(key=lambda a: a["start_idx"])

            # UNA riga per macchina con CORSIE PER FASCIA oraria (1°/2°/notte): i lavori
            # multi-fascia (Entrambi/H24) sono barre alte e i conflitti cross-fascia (es.
            # 1° turno vs Entrambi, qualcosa vs H24) sono marcati e bordati di rosso.
            if filtro_lavori and not bars:
                continue
            nlanes, bande = _layout_bande(bars, lane_h)
            conf = any(b.get("conflitto") for b in bars)
            righe.append({
                "macchina": m, "turno": Pianificazione.TURNO_GIORNO,
                "bars": bars, "lanes": nlanes, "bande": bande,
                "sat": sat["per_macchina"].get(m.id),
                "row_h": nlanes * lane_h + 12, "conflitto": conf,
                "kickoff": m_ko, "milestones": milestones, "assenze": assenze_markers,
            })
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
    famiglie_legenda = [
        {"colore": c, "label": leg_fam_label.get(c, "")}
        for c, _n in leg_fam_count.most_common(16) if leg_fam_label.get(c, "") not in ("", "—")
    ]
    _cm = request.GET.get("colore")
    colore_mode = _cm if _cm in ("stato", "famiglia", "commessa") else "commessa"
    ctx = {
        "giorni": giorni, "giorni_hdr": giorni_hdr, "sezioni": sezioni, "oggi": oggi,
        "start": start, "giorni_n": giorni_n,
        "cell_w": cell_w, "lane_h": lane_h, "settimane": settimane,
        "prev_start": _inizio_finestra_prec(start, giorni_n).isoformat(),
        "next_start": (fine + timedelta(days=1)).isoformat(),
        "sat_totale": sat["totale"],
        "oggi_idx": oggi_col,
        "categorie": Macchina.CATEGORIA_CHOICES,
        "finestra_opzioni": [7, 14, 21, 28, 42, 56],
        "clienti": clienti,
        "famiglie": list(FamigliaPezzo.objects.values("id", "nome").order_by("nome")),
        "f_cat": f_cat, "f_cliente": f_cliente, "f_fam": f_fam,
        # can_edit = permesso canonico di modifica (gestione_carichi_macchina.piano.edit):
        # nasconde i comandi di scrittura a chi ha solo la vista. L'enforcement reale è il
        # binding route->permesso (middleware ACL v2).
        "can_edit": _puo_modificare(request),
        "stato_choices": Pianificazione.STATO_CHOICES, "fase_choices": Pianificazione.FASE_CHOICES,
        "turno_choices": Pianificazione.TURNO_CHOICES,
        # Macchine per il select del modale "+ Aggiungi lavoro": rispetta il filtro
        # categoria della vista (coerente con ciò che si vede; il test verifica che le
        # macchine fuori categoria non compaiano). Porta anche la capability turni della
        # macchina, così il picker del turno mostra solo le opzioni davvero possibili.
        "macchine_scelta": [
            {"id": mm.id, "codice": mm.codice, "turni": mm.turni_consentiti(),
             "ha_secondo_turno": mm.ha_secondo_turno, "ha_turno_notte": mm.ha_turno_notte,
             "ore_giorno": float(mm.ore_giorno_disponibili), "stato": mm.stato_pianificazione}
            for mm in macchine
        ],
        "colore_mode": colore_mode,
        "commesse_legenda": commesse_legenda,
        "famiglie_legenda": famiglie_legenda,
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


def _piano_token(macchina_eff, p) -> str:
    """Impronta dello stato che `_piano_slittamento` usa per calcolare il piano su
    `macchina_eff` (i lavori attivi della macchina + `p` stesso). Cambia se, tra la
    preview e la conferma, qualcuno inserisce/sposta/elimina un lavoro coinvolto
    (protezione TOCTOU: la conferma dell'operatore va invalidata se il piano che ha
    visto non è più quello reale)."""
    from .models import Pianificazione

    parti = [f"p:{p.id}:{p.updated_at.isoformat()}"]
    qs = (
        Pianificazione.objects.filter(macchina=macchina_eff)
        .exclude(stato=Pianificazione.STATO_COMPLETATA)
        .exclude(pk=p.pk)
        .only("id", "updated_at")
    )
    parti += sorted(f"{o.id}:{o.updated_at.isoformat()}" for o in qs)
    return hashlib.sha256("|".join(parti).encode()).hexdigest()[:16]


@login_required
@require_POST
def reschedule(request):
    """Sposta una pianificazione nel tempo e/o su un'altra macchina (drag-to-reschedule).

    - `giorni_delta`: spostamento in giorni.
    - `coda=1` (alias legacy `cascata=1`): sposta dello stesso delta anche i lavori
      successivi sulla STESSA macchina/turno (solo per spostamenti temporali, non con
      cambio macchina).
    - `macchina_dest`: nuova macchina; se incompatibile (categoria diversa e fuori pool),
      o se non supporta il turno del lavoro, e senza `forza=1`, ritorna rispettivamente
      reason=incompatibile / reason=turno_incompatibile per far decidere all'operatore.
      `forza` bypassa SOLO questi due controlli di eleggibilità macchina, MAI la preview
      di slittamento sotto: sono conferme indipendenti.
    - Se il piano calcolato (`_piano_slittamento`) comporta più di una riga (slittamento
      a catena di altri lavori) e l'operatore non ha ancora confermato (`conferma_slittamento`),
      ritorna un preview (`reason=slittamento`, con flag `irrisolto` per riga se il conflitto
      eccede l'orizzonte di ricerca) SENZA scrivere sul DB. Le righe irrisolte non vengono
      comunque mai scritte (nessun movimento reale).
    Snapshot dello stato precedente in sessione per l'undo.
    """
    from django.db import transaction

    from .models import Macchina, Pianificazione

    pid = _as_int(request.POST.get("pianificazione_id"))
    delta = _as_int(request.POST.get("giorni_delta"), 0) or 0
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
        if not target.puo_turno(p.turno) and not forza:
            turno_lbl = dict(Pianificazione.TURNO_CHOICES).get(p.turno, p.turno)
            return JsonResponse({
                "ok": False, "reason": "turno_incompatibile",
                "error": f"{target.codice} non può fare il turno «{turno_lbl}». Spostare comunque?",
            }, status=200)

    coda = (request.POST.get("coda") in ("1", "true", "on")
            or request.POST.get("cascata") in ("1", "true", "on"))  # alias legacy
    conferma = request.POST.get("conferma_slittamento") in ("1", "true", "on")
    versione_client = (request.POST.get("versione") or "").strip()
    macchina_eff = target or p.macchina
    nuova_data = p.data + timedelta(days=delta)

    # `coda` (sposta tutta la coda) vale solo per gli spostamenti temporali: con cambio
    # macchina slittiamo soltanto i conflitti reali sulla destinazione.
    piano = _piano_slittamento(macchina_eff, p, nuova_data, coda=coda and not sposta_macchina)
    token = _piano_token(macchina_eff, p)

    # TOCTOU: se il client sta confermando una preview vista in precedenza (ha una
    # `versione`) ma nel frattempo lo stato è cambiato, il piano che l'operatore ha
    # confermato non è più quello reale -> rifiuta, non applicare alla cieca.
    if versione_client and versione_client != token:
        return JsonResponse({
            "ok": False, "reason": "stato_cambiato",
            "error": "Il piano è cambiato nel frattempo: ricontrolla lo spostamento.",
        }, status=200)

    # C'è slittamento (piano oltre la sola p) e non ancora confermato -> preview.
    # `forza` bypassa SOLO l'incompatibilità di categoria macchina (sopra): uno
    # slittamento a catena richiede sempre la sua conferma esplicita e separata,
    # anche quando il cambio macchina è già stato forzato.
    if len(piano) > 1 and not conferma:
        return JsonResponse({
            "ok": False, "reason": "slittamento", "versione": token,
            "piano": [{
                "etichetta": r["etichetta"], "macchina": r["macchina"],
                "da": r["da"].strftime("%d/%m"), "a": r["a"].strftime("%d/%m"),
                "irrisolto": bool(r.get("irrisolto")),
            } for r in piano],
        }, status=200)

    # Le righe IRRISOLTE (conflitto residuo oltre l'orizzonte di ricerca) non vanno
    # scritte: non c'è alcun movimento reale da applicare (a == da), solo da segnalare
    # all'operatore — scriverle sposterebbe inutilmente fonte/updated_at di un lavoro
    # che di fatto non e' stato toccato.
    da_scrivere = [r for r in piano if not r.get("irrisolto")]
    n_irrisolti = len(piano) - len(da_scrivere)

    with transaction.atomic():
        ids = [r["id"] for r in da_scrivere]
        blocco = {j.id: j for j in Pianificazione.objects.select_for_update().filter(pk__in=ids)}
        snap = [{"id": j.id, "macchina_id": j.macchina_id, "data": j.data.isoformat()}
                for j in blocco.values()]
        for r in da_scrivere:
            job = blocco.get(r["id"])
            if not job:
                continue
            job.data = r["a"]
            if sposta_macchina and job.pk == p.pk:
                job.macchina = target
            job.fonte = Pianificazione.FONTE_MANUALE
            job.save(update_fields=["data", "macchina", "fonte", "updated_at"])
        # "guardia": updated_at COME RISULTA dopo la nostra scrittura. L'undo la
        # confronta con quella corrente al momento del click: se non coincidono più,
        # qualcun altro ha ritoccato il job nel frattempo e non va sovrascritto alla cieca.
        for s in snap:
            s["guardia"] = blocco[s["id"]].updated_at.isoformat()

    request.session["gcm_undo"] = {"snap": snap}
    request.session.modified = True
    macchina_log = target or p.macchina
    n_slittati = len(da_scrivere) - 1
    if sposta_macchina:
        descr = f"Spostato su {macchina_log.codice}" + (f", {delta:+d} giorni" if delta else "")
    else:
        descr = f"Spostato di {delta:+d} giorni"
    if n_slittati:
        descr += f" (+{n_slittati} slittati)"
    if n_irrisolti:
        descr += f" ({n_irrisolti} conflitti irrisolti oltre l'orizzonte)"
    _log_azione(request, "sposta", macchina=macchina_log, pianificazione_id=p.id, descrizione=descr)
    return JsonResponse({
        "ok": True, "id": p.id, "spostati": len(da_scrivere),
        "irrisolti": n_irrisolti,
        "coda": coda and not sposta_macchina, "macchina": sposta_macchina,
    })


@login_required
@require_POST
def reschedule_undo(request):
    """Annulla l'ultimo spostamento: ripristina macchina e data dallo snapshot in sessione.

    Non sovrascrive alla cieca: un job va ripristinato solo se il suo `updated_at`
    coincide ancora con la "guardia" salvata subito dopo la nostra scrittura. Se qualcun
    altro (altra tab/utente) lo ha ritoccato nel frattempo, viene saltato (riportato in
    `saltati`) invece di perdere quella modifica successiva.
    """
    from django.db import transaction

    from .models import Pianificazione

    undo = request.session.get("gcm_undo")
    snap = undo.get("snap") if undo else None
    if not snap:
        return JsonResponse({"ok": False, "error": "Niente da annullare."}, status=400)

    correnti = {j.id: j for j in Pianificazione.objects.filter(pk__in=[s["id"] for s in snap])}
    da_ripristinare = [
        s for s in snap
        if s.get("guardia") and s["id"] in correnti
        and correnti[s["id"]].updated_at.isoformat() == s["guardia"]
    ]
    saltati = len(snap) - len(da_ripristinare)

    with transaction.atomic():
        for s in da_ripristinare:
            Pianificazione.objects.filter(pk=s["id"]).update(
                macchina_id=s["macchina_id"], data=_parse_date(s["data"])
            )
    del request.session["gcm_undo"]
    request.session.modified = True
    descr = f"Annullato spostamento di {len(da_ripristinare)} lavori"
    if saltati:
        descr += f" ({saltati} saltati: modificati nel frattempo)"
    _log_azione(request, "undo", descrizione=descr)
    return JsonResponse({"ok": True, "annullati": len(da_ripristinare), "saltati": saltati})


def _famiglia_da_param(par: str):
    from .models import FamigliaPezzo

    par = (par or "").strip()
    if par.isdigit():
        return FamigliaPezzo.objects.filter(pk=int(par)).first()
    if par:
        return FamigliaPezzo.objects.filter(nome__iexact=par).first()
    return None


def _suggerimenti_macchina(fam, fase: str = "", turno: str = "") -> list[dict]:
    from django.conf import settings

    from .models import Macchina
    from .previsioni import (
        costruisci_indice_carico,
        costruisci_indice_macchine,
        costruisci_indice_macchine_fase,
        costruisci_indice_macchine_fase_globale,
        costruisci_indice_recency,
        costruisci_indice_stato,
        costruisci_indici,
        finestra_carico_per_ore,
        prevedi_macchina,
    )

    # Suggerimento PESATO: affinita' storica (per FASE quando indicata) + recency + carico
    # attuale, escludendo le macchine in guasto/manutenzione. Mantiene prob/occorrenze.
    # Categoria di TUTTE le macchine (non solo quelle candidate: serve prima ancora di
    # sapere chi sopravvive allo scoring) per applicare eventuali pesi dedicati per reparto.
    categoria_per_macchina = dict(Macchina.objects.values_list("id", "categoria"))
    # Finestra di saturazione dimensionata sulla durata TIPICA dei lavori della famiglia
    # (non 14gg fissi): un lavoro breve va confrontato col carico immediato, uno lungo con
    # un orizzonte piu' ampio.
    _, _, famiglia_ore = costruisci_indici()
    giorni_finestra = finestra_carico_per_ore(famiglia_ore.get(fam.id))
    ranked = prevedi_macchina(
        fam.id,
        costruisci_indice_macchine(),
        fase=fase or None,
        freq_per_famiglia_fase=costruisci_indice_macchine_fase() if fase else None,
        # Cold-start: se la famiglia non ha ALCUNO storico proprio, ricade su quali
        # macchine fanno tipicamente quella fase in generale (invece di nessun suggerimento).
        freq_fase_globale=costruisci_indice_macchine_fase_globale() if fase else None,
        recency_per_coppia=costruisci_indice_recency(),
        carico_per_macchina=costruisci_indice_carico(giorni=giorni_finestra),
        stato_per_macchina=costruisci_indice_stato(),
        categoria_per_macchina=categoria_per_macchina,
        pesi_per_categoria=getattr(settings, "GCM_PESI_PER_CATEGORIA", None),
    )
    macs = {
        m.id: m for m in
        Macchina.objects.filter(id__in=[r["macchina_id"] for r in ranked]).select_related("asset")
    }
    # Coerenza col TURNO richiesto: una macchina che non puo' fare quel turno (es. lavoro
    # notturno su macchina senza turno notte) non va suggerita. Filtra prima del taglio
    # ai primi 5, cosi' la lista non si svuota scartando candidati in coda.
    if turno:
        ranked = [
            r for r in ranked
            if r["macchina_id"] in macs and macs[r["macchina_id"]].puo_turno(turno)
        ]
    ranked = ranked[:5]
    return [
        {"macchina_id": r["macchina_id"],
         "codice": macs[r["macchina_id"]].codice if r["macchina_id"] in macs else "",
         "occorrenze": r["occorrenze"], "prob": r["prob"],
         "score": r.get("score"), "saturazione": r.get("saturazione"),
         "componenti": r.get("componenti"),
         "fallback_globale": bool(r.get("fallback_globale"))}
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
            "fallback_globale": bool(s.get("fallback_globale")),
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
    turno = (request.GET.get("turno") or "").strip()
    righe = _righe_suggerimento_display(
        _suggerimenti_macchina(fam, fase=fase, turno=turno), macchina_corrente
    )
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


@login_required
def api_sovrapposizione(request):
    """Verifica (read-only) se un lavoro su (macchina, turno, data, ore) collide con altri.

    Usata dal modale "+ Aggiungi lavoro" per chiedere conferma PRIMA di salvare. FBV+JSON.
    """
    from .models import Macchina, Pianificazione

    macchina = get_object_or_404(Macchina, pk=request.GET.get("macchina") or 0)
    turno = request.GET.get("turno") or Pianificazione.TURNO_GIORNO
    data = _parse_date(request.GET.get("data")) or timezone.localdate()
    ore = _as_dec(request.GET.get("ore"))
    ore_f = float(ore) if ore else None
    escludi = _as_int(request.GET.get("escludi"))
    altri = _sovrapposizioni(macchina, turno, data, ore_f, escludi_id=escludi)
    # Suggerimento "primo slot libero" solo quando serve (c'è conflitto).
    suggerimento = _primo_slot_libero(macchina, data, ore_f, turno) if altri else None
    return JsonResponse({
        "ok": True, "overlap": bool(altri),
        "conflitti": [
            {"id": o.id,
             "testo": o.testo_originale or (o.famiglia.nome if o.famiglia_id else "lavoro"),
             "turno": o.turno, "data": o.data.isoformat()}
            for o in altri[:5]
        ],
        "suggerimento": suggerimento,
    })


@login_required
@require_POST
def pianificazione_duplica(request, pk):
    """Duplica un lavoro (stesso giorno/turno/macchina) come nuovo lavoro pianificato."""
    from .models import Pianificazione

    p = get_object_or_404(Pianificazione.objects.select_related("macchina__asset"), pk=pk)
    nuovo = Pianificazione.objects.create(
        macchina_id=p.macchina_id, data=p.data, turno=p.turno,
        commessa_id=p.commessa_id, operazione_id=p.operazione_id, famiglia_id=p.famiglia_id,
        qta=p.qta, ore=p.ore, stato=Pianificazione.STATO_PIANIFICATA, fase=p.fase,
        testo_originale=p.testo_originale, fonte=Pianificazione.FONTE_MANUALE,
    )
    _log_azione(request, "duplica", macchina=p.macchina, pianificazione_id=nuovo.id,
                descrizione=f"Duplicato da #{p.id}: {p.testo_originale or ''}".strip())
    return JsonResponse({"ok": True, "id": nuovo.id})


# Campi macchina modificabili dalla UI di pianificazione (NON si tocca l'asset).
_MACCHINA_CONFIG_CAMPI = ("ha_secondo_turno", "ha_turno_notte", "ore_giorno_disponibili", "stato_pianificazione")


@login_required
@require_POST
def macchina_config(request):
    """Aggiorna i parametri di pianificazione di UNA macchina (flag turni, ore/gg, stato).

    Usata sia dalla pagina "Impostazioni macchine" sia dai toggle rapidi nel pannello
    macchina del Gantt. Aggiorna solo i campi presenti nel POST; l'asset NON viene toccato.
    """
    from .models import Macchina

    m = get_object_or_404(Macchina.objects.select_related("asset"), pk=request.POST.get("macchina") or 0)
    aggiornati = []
    if "ha_secondo_turno" in request.POST:
        m.ha_secondo_turno = request.POST.get("ha_secondo_turno") in ("1", "true", "on")
        aggiornati.append("ha_secondo_turno")
    if "ha_turno_notte" in request.POST:
        m.ha_turno_notte = request.POST.get("ha_turno_notte") in ("1", "true", "on")
        aggiornati.append("ha_turno_notte")
    if request.POST.get("ore_giorno"):
        og = _as_dec(request.POST.get("ore_giorno"))
        if og is not None and og > 0:
            m.ore_giorno_disponibili = og
            aggiornati.append("ore_giorno_disponibili")
    if request.POST.get("stato") in dict(Macchina.STATO_CHOICES):
        m.stato_pianificazione = request.POST.get("stato")
        aggiornati.append("stato_pianificazione")
    if aggiornati:
        m.save(update_fields=aggiornati + ["updated_at"])
        _log_azione(request, "config", macchina=m,
                    descrizione="Aggiornato: " + ", ".join(aggiornati))
    return JsonResponse({
        "ok": True, "macchina": m.id, "codice": m.codice,
        "ha_secondo_turno": m.ha_secondo_turno, "ha_turno_notte": m.ha_turno_notte,
        "ore_giorno": float(m.ore_giorno_disponibili), "stato": m.stato_pianificazione,
        "turni": m.turni_consentiti(), "n_turni": m.n_turni_attivi(),
    })


@login_required
def impostazioni_macchine(request):
    """Pagina SSR per configurare i turni/stato/ore delle macchine (capability di pianificazione)."""
    from .models import Macchina

    macchine = list(
        Macchina.objects.filter(attivo=True).select_related("asset")
        .order_by("categoria", "ordine_sezione", "id")
    )
    cat_label = dict(Macchina.CATEGORIA_CHOICES)
    by_cat: dict[str, list] = defaultdict(list)
    for m in macchine:
        by_cat[m.categoria].append(m)
    sezioni = [
        {"categoria": cat, "label": cat_label.get(cat, cat), "macchine": by_cat[cat]}
        for cat in _CAT_ORDER if by_cat.get(cat)
    ]
    return render(request, "gestione_carichi_macchina/impostazioni_macchine.html", {
        "sezioni": sezioni,
        "stato_choices": Macchina.STATO_CHOICES,
        "n_macchine": len(macchine),
        "can_edit": _puo_modificare(request),
    })


@login_required
def registro_azioni(request):
    """Sezione LOG: audit delle azioni sul piano (chi/cosa/quando), filtrabile."""
    from .models import Macchina, RegistroAzione

    from django.db import DatabaseError

    f_azione = request.GET.get("azione") or ""
    f_mac = _as_int(request.GET.get("macchina"))
    f_q = (request.GET.get("q") or "").strip()
    azioni, tabella_assente = [], False
    try:
        qs = RegistroAzione.objects.select_related("utente", "macchina__asset")
        if f_azione in dict(RegistroAzione.AZIONE_CHOICES):
            qs = qs.filter(azione=f_azione)
        if f_mac:
            qs = qs.filter(macchina_id=f_mac)
        if f_q:
            qs = qs.filter(descrizione__icontains=f_q) | qs.filter(utente_nome__icontains=f_q)
        azioni = list(qs.order_by("-created_at", "-id")[:300])
    except DatabaseError:
        # Tabella non ancora creata (deploy senza `migrate`): degrada con un avviso
        # invece di un 500. Il log inizia a popolarsi dopo la migrazione 0006.
        tabella_assente = True
    return render(request, "gestione_carichi_macchina/registro_azioni.html", {
        "azioni": azioni,
        "azione_choices": RegistroAzione.AZIONE_CHOICES,
        "macchine": Macchina.objects.filter(attivo=True).select_related("asset").order_by("categoria", "ordine_sezione"),
        "f_azione": f_azione, "f_mac": f_mac, "f_q": f_q,
        "totale": len(azioni), "tabella_assente": tabella_assente,
    })
