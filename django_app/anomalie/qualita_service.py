"""Classificazione qualita' delle singole anomalie (S/N) e Pareto.

La scheda (``AnomaliaSchedaQualita``) nasce da sola al primo salvataggio dell'anomalia
(o alla prima apertura, per le storiche) con istantanea OP/P/N, origine di default e
decisione sul materiale dedotta dai flag (RDC, avanzamento) finche' nessuno la sceglie
a mano. Ogni scheda e' agganciata alla NC aperta del suo OP (``nc_service``).

Tutto e' chiamato fire-and-forget dal salvataggio anomalia: un errore qui non deve
mai bloccare la segnalazione.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from .quality_models import AnomaliaSchedaQualita as Scheda
from .quality_models import AnomaliaTipoDifetto

logger = logging.getLogger(__name__)

_LEGACY_COLS = (
    "id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa",
    "aprire_rdc", "numero_rdc", "segnalare_cliente", "chiudere", "avanzamento",
    "created_datetime",
)


# ── Lettura righe legacy ───────────────────────────────────────────────────


def legacy_row(anomalia_id: int) -> dict | None:
    """Riga della tabella legacy ``anomalie`` (solo le colonne presenti)."""
    rows = legacy_rows([anomalia_id])
    return rows.get(int(anomalia_id))


def legacy_rows(anomalia_ids) -> dict[int, dict]:
    """{id: riga} per piu' anomalie, a blocchi (SQL Server: max ~2100 parametri)."""
    from .automazioni_service import _anomalie_cols, _fetch

    ids = sorted({int(i) for i in anomalia_ids})
    cols = _anomalie_cols()
    if not ids or "id" not in cols:
        return {}
    select = ", ".join(c for c in _LEGACY_COLS if c in cols)
    out: dict[int, dict] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join(["%s"] * len(chunk))
        for r in _fetch(f"SELECT {select} FROM anomalie WHERE id IN ({ph})", chunk):
            out[int(r["id"])] = r
    return out


def anno_di(value) -> int:
    if isinstance(value, (datetime, date)):
        return value.year
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return timezone.localdate().year


def _norm(value) -> str:
    return str(value or "").strip().lower()


# ── Scheda per S/N ─────────────────────────────────────────────────────────


def disposizione_suggerita(row: dict) -> str:
    """Decisione sul materiale dedotta dai flag dell'anomalia (sovrascrivibile)."""
    avanz = _norm(row.get("avanzamento"))
    if row.get("aprire_rdc"):
        return Scheda.Disposizione.DEROGA
    if avanz == "accetto lo stato":
        return Scheda.Disposizione.USO_TALE
    if avanz == "azione di recupero":
        return Scheda.Disposizione.RILAVORAZIONE
    return Scheda.Disposizione.DA_DEFINIRE


def gravita_suggerita(row: dict) -> str:
    """Una NC portata al cliente (segnalazione o richiesta di deroga) e' almeno maggiore."""
    if row.get("segnalare_cliente") or row.get("aprire_rdc"):
        return Scheda.Gravita.MAGGIORE
    return ""


def get_or_create_scheda(anomalia_id: int, *, row: dict | None = None):
    """Scheda della riga legacy, creata al primo accesso. ``(scheda|None, creata)``."""
    esistente = Scheda.objects.filter(anomalia_id=anomalia_id).first()
    if esistente is not None:
        return esistente, False
    row = row if row is not None else legacy_row(anomalia_id)
    if row is None:
        return None, False

    op = str(row.get("ex_op_nominativo") or "").strip()[:100]
    pn = ""
    if op:
        from .mail_action_service import _fetch_pn_for_ops
        pn = (_fetch_pn_for_ops([op]) or {}).get(op.lower(), "")[:120]
    try:
        with transaction.atomic():
            return Scheda.objects.create(
                anomalia_id=anomalia_id,
                op_titolo=op,
                part_number=pn,
                origine=Scheda.Origine.PRODUZIONE,
                gravita=gravita_suggerita(row),
                disposizione=disposizione_suggerita(row),
            ), True
    except IntegrityError:
        # Doppio salvataggio concorrente: l'altra richiesta ha gia' creato la scheda.
        return Scheda.objects.filter(anomalia_id=anomalia_id).first(), False


def aggiorna_automatici(scheda: Scheda, row: dict) -> None:
    """Riallinea i campi dedotti dai flag, senza mai toccare le scelte manuali."""
    campi = []
    if scheda.disposizione_auto:
        nuova = disposizione_suggerita(row)
        if nuova != scheda.disposizione:
            scheda.disposizione = nuova
            campi.append("disposizione")
    if not scheda.gravita:
        grav = gravita_suggerita(row)
        if grav:
            scheda.gravita = grav
            campi.append("gravita")
    if campi:
        scheda.save(update_fields=[*campi, "updated_at"])


def sync_da_anomalia(anomalia_id: int):
    """Punto d'ingresso dal salvataggio anomalia: scheda, campi dedotti, NC dell'OP."""
    from . import nc_service

    row = legacy_row(anomalia_id)
    if row is None:
        return None
    scheda, _ = get_or_create_scheda(anomalia_id, row=row)
    if scheda is None:
        return None
    aggiorna_automatici(scheda, row)
    nc_service.aggancia_a_nc(scheda, row)
    return scheda


# ── Serializzazione per la UI ──────────────────────────────────────────────


def scelte() -> dict:
    """Liste delle select della scheda (solo tipi difetto e reparti attivi)."""
    from anagrafica.models import Reparto

    return {
        "origini": [{"value": v, "label": l} for v, l in Scheda.Origine.choices],
        "gravita": [{"value": v, "label": l} for v, l in Scheda.Gravita.choices],
        "disposizioni": [{"value": v, "label": l} for v, l in Scheda.Disposizione.choices],
        "tipi_difetto": [
            {"value": t.pk, "label": t.nome, "famiglia": t.famiglia}
            for t in AnomaliaTipoDifetto.objects.filter(attivo=True)
        ],
        "reparti": [
            {"value": r.pk, "label": r.nome}
            for r in Reparto.objects.filter(is_active=True).order_by("nome")
        ],
    }


def serializza(scheda: Scheda) -> dict:
    nc = None
    if scheda.nc_id:
        from django.urls import NoReverseMatch, reverse

        try:
            url = reverse("anomalie_nc_dettaglio", args=[scheda.nc_id])
        except NoReverseMatch:
            url = ""
        n = scheda.nc
        nc = {"id": n.pk, "protocollo": n.protocollo, "stato": n.stato,
              "stato_label": n.get_stato_display(), "chiusa": n.is_chiusa, "url": url}
    return {
        "anomalia_id": scheda.anomalia_id,
        "op_titolo": scheda.op_titolo,
        "part_number": scheda.part_number,
        "origine": scheda.origine,
        "tipo_difetto": scheda.tipo_difetto_id,
        "tipo_difetto_label": scheda.tipo_difetto.nome if scheda.tipo_difetto_id else "",
        "gravita": scheda.gravita,
        "reparto": scheda.reparto_id,
        "quantita_nc": scheda.quantita_nc,
        "quantita_scartata": scheda.quantita_scartata,
        "disposizione": scheda.disposizione,
        "disposizione_auto": scheda.disposizione_auto,
        "nc": nc,
    }


def applica_modifiche(scheda: Scheda, data: dict, *, user=None) -> list[str]:
    """Aggiorna la scheda dai dati del form. Ritorna gli errori (vuota = salvata)."""
    errori: list[str] = []

    def _scelta(key, choices):
        if key not in data:
            return
        val = str(data.get(key) or "").strip().upper()
        if val and val not in dict(choices):
            errori.append(f"Valore non ammesso per {key}.")
            return
        setattr(scheda, key, val)

    def _fk(key, model):
        if key not in data:
            return
        raw = data.get(key)
        if raw in (None, "", 0, "0"):
            setattr(scheda, f"{key}_id", None)
            return
        try:
            obj = model.objects.filter(pk=int(raw)).first()
        except (TypeError, ValueError):
            obj = None
        if obj is None:
            errori.append(f"Valore non ammesso per {key}.")
            return
        setattr(scheda, key, obj)

    def _qta(key):
        if key not in data:
            return
        raw = data.get(key)
        if raw in (None, ""):
            setattr(scheda, key, None)
            return
        try:
            val = int(raw)
        except (TypeError, ValueError):
            val = -1
        if val < 0 or val > 1_000_000:
            errori.append(f"Quantità non valida ({key}).")
            return
        setattr(scheda, key, val)

    from anagrafica.models import Reparto

    _scelta("origine", Scheda.Origine.choices)
    _scelta("gravita", Scheda.Gravita.choices)
    if "disposizione" in data:
        val = str(data.get("disposizione") or "").strip().upper() or Scheda.Disposizione.DA_DEFINIRE
        if val not in dict(Scheda.Disposizione.choices):
            errori.append("Valore non ammesso per disposizione.")
        elif val != scheda.disposizione:
            scheda.disposizione = val
            scheda.disposizione_auto = False
    _fk("tipo_difetto", AnomaliaTipoDifetto)
    _fk("reparto", Reparto)
    _qta("quantita_nc")
    _qta("quantita_scartata")
    if (not errori and scheda.quantita_nc is not None and scheda.quantita_scartata is not None
            and scheda.quantita_scartata > scheda.quantita_nc):
        errori.append("La quantità scartata non può superare la quantità non conforme.")
    if errori:
        return errori
    scheda.updated_by = user if getattr(user, "is_authenticated", False) else None
    scheda.save()
    return []


# ── Statistiche ────────────────────────────────────────────────────────────


def pareto(anomalia_ids=None) -> dict:
    """Conteggi per difetto / origine / disposizione / gravita' (+ % cumulata).

    ``anomalia_ids`` (iterabile) restringe alle anomalie filtrate. Il filtro e' fatto
    in Python e non con ``__in``: su SQL Server un IN oltre ~2100 parametri fallisce.
    """
    campi = ("anomalia_id", "tipo_difetto_id", "origine", "disposizione", "gravita", "nc_id")
    righe = list(Scheda.objects.order_by().values_list(*campi))
    if anomalia_ids is not None:
        ammessi = {int(i) for i in anomalia_ids}
        righe = [r for r in righe if r[0] in ammessi]

    def _serie(idx, labels, nome_vuoto="Non classificata"):
        conteggi: dict = {}
        for r in righe:
            conteggi[r[idx]] = conteggi.get(r[idx], 0) + 1
        ordinati = sorted(conteggi.items(), key=lambda kv: -kv[1])
        tot = sum(conteggi.values()) or 1
        out, cum = [], 0
        for key, n in ordinati:
            cum += n
            label = labels.get(key, key) if key not in (None, "") else nome_vuoto
            out.append({"label": label, "n": n, "cum_pct": round(cum * 100 / tot, 1)})
        return out

    tipi = dict(AnomaliaTipoDifetto.objects.values_list("id", "nome"))
    return {
        "totale": len(righe),
        "classificate": sum(1 for r in righe if r[1]),
        "per_difetto": _serie(1, tipi),
        "per_origine": _serie(2, dict(Scheda.Origine.choices)),
        "per_disposizione": _serie(3, dict(Scheda.Disposizione.choices)),
        "per_gravita": _serie(4, dict(Scheda.Gravita.choices)),
        "nc": len({r[5] for r in righe if r[5]}),
    }
