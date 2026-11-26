"""Anagrafica dei P/N (``ArticoloPN``): sincronizzazione dalle fonti e riepilogo precalcolato per il catalogo.

Fonti, senza mai sovrascrivere quello che è stato scritto a mano:
- OP (tabella ``ordini_produzione``): crea l'articolo, conta OP e OP aperti;
- KICK-OFF (``tasks.Project``): crea l'articolo, completa descrizione, cliente e revisione se vuoti;
- Registro FAI (``tasks.FaiArticolo``): completa il cliente se vuoto;
- cartelle P/N della share Collaudo: crea l'articolo, scrive la cartella;
- report CMM letti: numeri del riepilogo (report, ultimi 12 mesi, fuori negli ultimi 30 giorni, andamento) e,
  per i P/N con report recenti, Cpk peggiore e quote non capaci (``analisi_pn``, in cache).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from django.db.models import Count, Max, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from core import ordini_produzione as op_db
from tasks.identity import normalize_part_number

from . import report_cmm_indice as cmm
from .models import ArticoloPN, ReportCMM

logger = logging.getLogger(__name__)

STATI_OP_CHIUSI = {"chiuso", "chiusa", "annullato", "annullata", "completato", "terminato", "evaso"}
CAMPI_RIEPILOGO = ["n_op", "op_aperti", "n_report", "n_report_12m", "fuori_30g", "ultimo_report", "andamento", "riepilogo_il"]


def _crea_mancanti(pn_origine: dict[str, str]) -> int:
    """Crea gli articoli dei P/N che non ci sono ancora. Niente ``ignore_conflicts``: SQL Server (mssql-django)
    non lo supporta. Se un giro in parallelo ne ha appena creato qualcuno, si ripiega su uno alla volta."""
    from django.db import IntegrityError, transaction

    esistenti = set(ArticoloPN.objects.values_list("pn", flat=True))
    da_creare: dict[str, str] = {}
    for pn, o in pn_origine.items():
        chiave = (pn or "")[:100]
        if chiave and chiave not in esistenti:
            da_creare.setdefault(chiave, o)
    if not da_creare:
        return 0
    try:
        with transaction.atomic():
            ArticoloPN.objects.bulk_create([ArticoloPN(pn=pn, origine=o) for pn, o in da_creare.items()], batch_size=500)
        return len(da_creare)
    except IntegrityError:
        creati = 0
        for pn, o in da_creare.items():
            _, nuovo = ArticoloPN.objects.get_or_create(pn=pn, defaults={"origine": o})
            creati += nuovo
        return creati


def _mesi_12(oggi: date) -> list[tuple[int, int]]:
    a, m = oggi.year, oggi.month
    out = []
    for _ in range(12):
        out.append((a, m))
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return out[::-1]


def sincronizza(cartelle: list[tuple[str, str, float]] | None = None, con_cpk_secondi: float = 0) -> dict:
    """Crea gli articoli mancanti dalle fonti e ricalcola il riepilogo di tutti. ``cartelle`` = l'elenco della
    share già fatto dal giro (altrimenti si legge, se la share è impostata). ``con_cpk_secondi`` > 0 ricalcola
    anche Cpk e quote non capaci dei P/N con report negli ultimi 12 mesi, finché c'è tempo."""
    oggi = date.today()
    origine: dict[str, str] = {}
    ops = op_db.elenco() if op_db.disponibile() else []
    for o in ops:
        pn = normalize_part_number(o.get("pn") or "")
        if pn:
            origine.setdefault(pn, "op")
    try:
        from tasks.models import Project

        progetti = list(Project.objects.exclude(part_number="").order_by("-id")
                        .values("part_number", "client_name", "descrizione_pezzo", "revisione"))
    except Exception:  # pragma: no cover - KICK-OFF non disponibile
        progetti = []
    for p in progetti:
        pn = normalize_part_number(p["part_number"])
        if pn:
            origine.setdefault(pn, "kickoff")
    try:
        from tasks.models import FaiArticolo

        clienti_fai = {normalize_part_number(pn): c for pn, c in FaiArticolo.objects.exclude(client_name="")
                       .order_by("-updated_at").values_list("part_number", "client_name")}
    except Exception:  # pragma: no cover - Registro FAI non disponibile
        clienti_fai = {}
    if cartelle is None and cmm.attivo():
        try:
            cartelle = cmm.cartelle_pn()
        except OSError:
            cartelle = []
    cartelle = cartelle or []
    for pn, _percorso, _m in cartelle:
        origine.setdefault(pn, "collaudo")
    creati = _crea_mancanti(origine)

    articoli = {a.pn: a for a in ArticoloPN.objects.all()}
    # Completa dai KICK-OFF (il più recente vince) e dalla share solo i campi vuoti.
    da_salvare_anagrafica = []
    visti_kick = set()
    for p in progetti:
        pn = normalize_part_number(p["part_number"])
        a = articoli.get(pn)
        if a is None or pn in visti_kick:
            continue
        visti_kick.add(pn)
        cambiato = False
        for campo, valore in (("descrizione", p["descrizione_pezzo"]), ("cliente", p["client_name"]), ("revisione", p["revisione"])):
            if valore and not getattr(a, campo):
                setattr(a, campo, valore[: ArticoloPN._meta.get_field(campo).max_length])
                cambiato = True
        if cambiato:
            da_salvare_anagrafica.append(a)
    for pn, cliente in clienti_fai.items():
        a = articoli.get(pn)
        if a is not None and not a.cliente and cliente:
            a.cliente = cliente[:180]
            if a not in da_salvare_anagrafica:
                da_salvare_anagrafica.append(a)
    for pn, percorso, _m in cartelle:
        a = articoli.get(pn)
        if a is not None and a.cartella_collaudo != percorso[:500]:
            a.cartella_collaudo = percorso[:500]
            if a not in da_salvare_anagrafica:
                da_salvare_anagrafica.append(a)
    ArticoloPN.objects.bulk_update(da_salvare_anagrafica, ["descrizione", "cliente", "revisione", "cartella_collaudo"], batch_size=500)

    # OP
    n_op: dict[str, int] = {}
    aperti: dict[str, int] = {}
    for o in ops:
        pn = normalize_part_number(o.get("pn") or "")
        if not pn:
            continue
        n_op[pn] = n_op.get(pn, 0) + 1
        if (o.get("stato") or "").strip().lower() not in STATI_OP_CHIUSI:
            aperti[pn] = aperti.get(pn, 0) + 1

    # Report CMM
    validi = ReportCMM.objects.filter(righe__gt=0, escluso=False)
    tot = {r["pn"]: r for r in validi.values("pn").annotate(
        n=Count("id"), ultimo=Max("data"),
        n12=Count("id", filter=Q(data__gte=oggi - timedelta(days=365))),
        f30=Count("id", filter=Q(data__gte=oggi - timedelta(days=30), fuori__gt=0)))}
    mesi = _mesi_12(oggi)
    per_mese: dict[str, dict] = {}
    for r in (validi.filter(data__gte=date(*mesi[0], 1)).annotate(mese=TruncMonth("data"))
              .values("pn", "mese").annotate(n=Count("id"))):
        if r["mese"]:
            per_mese.setdefault(r["pn"], {})[(r["mese"].year, r["mese"].month)] = r["n"]
    adesso = timezone.now()
    for pn, a in articoli.items():
        t = tot.get(pn, {})
        a.n_op, a.op_aperti = n_op.get(pn, 0), aperti.get(pn, 0)
        a.n_report, a.n_report_12m, a.fuori_30g = t.get("n", 0), t.get("n12", 0), t.get("f30", 0)
        a.ultimo_report = t.get("ultimo")
        pm = per_mese.get(pn, {})
        a.andamento = ",".join(str(pm.get(m, 0)) for m in mesi) if pm else ""
        a.riepilogo_il = adesso
    ArticoloPN.objects.bulk_update(list(articoli.values()), CAMPI_RIEPILOGO, batch_size=500)

    cpk = aggiorna_cpk(con_cpk_secondi) if con_cpk_secondi else 0
    return {"creati": creati, "articoli": len(articoli), "cpk": cpk}


def aggiorna_cpk(secondi: float, pn: list[str] | None = None) -> int:
    """Cpk peggiore e quote non capaci (Cpk < 1,33) dai report CMM: per i P/N indicati, oppure per quelli con
    report negli ultimi 12 mesi dal riepilogo più vecchio, finché c'è tempo."""
    scadenza = time.monotonic() + secondi
    qs = ArticoloPN.objects.filter(pn__in=pn) if pn else ArticoloPN.objects.filter(n_report_12m__gt=0)
    fatti = 0
    for a in qs.order_by("riepilogo_il"):
        if time.monotonic() > scadenza:
            break
        try:
            righe = cmm.analisi_pn(a.pn)
        except Exception:  # pragma: no cover - un P/N difettoso non ferma gli altri
            logger.exception("riepilogo Cpk %s", a.pn)
            continue
        valori = [r["cpk"] for r in righe if r["cpk"] is not None]
        a.cpk_peggiore = min(valori) if valori else None
        a.quote_non_capaci = sum(1 for v in valori if v < 1.33)
        a.save(update_fields=["cpk_peggiore", "quote_non_capaci"])
        fatti += 1
    return fatti


def da_guardare(a: ArticoloPN, anomalie: int = 0, fai_codice: str = "") -> bool:
    """Un P/N «da guardare»: quote non capaci, report con quote fuori nell'ultimo mese, anomalie aperte,
    FAI da ripetere o da verificare."""
    return bool(a.quote_non_capaci or a.fuori_30g or anomalie or fai_codice in ("da_ripetere", "da_verificare"))
