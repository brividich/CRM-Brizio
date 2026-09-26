"""Scheda qualita' delle anomalie e registrazione automatica delle NC (ISO 9001 §10.2).

Tre responsabilita':

1. **Scheda qualita'** (``AnomaliaSchedaQualita``): nasce da sola al primo salvataggio
   dell'anomalia con protocollo ``NC-<anno>-<nnnn>``, istantanea OP/P/N, origine di
   default e decisione sul materiale dedotta dai flag (RDC, avanzamento) finche'
   nessuno la sceglie a mano.
2. **Registro NC**: le anomalie *significative* (gravita' maggiore/critica, segnalate
   al cliente, con RDC/deroga, o difetto ricorrente sullo stesso P/N) diventano una
   voce ``NC`` del registro OFI/NC trasversale (``gestione_specifiche.RegistroOFI``,
   MOD.174), gia' con numero, riferimento norma, processo, priorita' e scadenza. Le
   anomalie dello stesso evento (stesso OP, o stesso P/N se ricorrente, e stesso
   difetto) si agganciano alla NC aperta invece di crearne un'altra.
   Chi compila l'analisi delle cause e le azioni resta da decidere: la voce nasce
   senza proprietario e con il promemoria spento.
3. **Pareto** per le statistiche.

Tutto e' chiamato fire-and-forget dal salvataggio anomalia: un errore qui non deve
mai bloccare la segnalazione.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from urllib.parse import quote

from django.db import IntegrityError, transaction
from django.utils import timezone

from .quality_models import AnomaliaSchedaQualita as Scheda
from .quality_models import AnomaliaTipoDifetto

logger = logging.getLogger(__name__)

MODULO_ORIGINE = "anomalie"
RIF_NORMA_NC = "ISO 9001 §10.2 / EN 9100 §8.7"
GIORNI_CHIUSURA = {"ALTA": 30, "MEDIA": 60, "BASSA": 90}
_PRIORITA_RANK = {"BASSA": 0, "MEDIA": 1, "ALTA": 2}

_LEGACY_COLS = (
    "id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa",
    "aprire_rdc", "numero_rdc", "segnalare_cliente", "chiudere", "avanzamento",
    "created_datetime",
)


# ── Lettura riga legacy ────────────────────────────────────────────────────


def legacy_row(anomalia_id: int) -> dict | None:
    """Riga della tabella legacy ``anomalie`` (solo le colonne presenti)."""
    from .automazioni_service import _anomalie_cols, _fetch

    cols = _anomalie_cols()
    if "id" not in cols:
        return None
    select = ", ".join(c for c in _LEGACY_COLS if c in cols)
    rows = _fetch(f"SELECT {select} FROM anomalie WHERE id = %s", [int(anomalia_id)])
    return rows[0] if rows else None


def _anno(value) -> int:
    if isinstance(value, datetime):
        return value.year
    if isinstance(value, date):
        return value.year
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return timezone.localdate().year


def _norm(value) -> str:
    return str(value or "").strip().lower()


# ── Scheda ─────────────────────────────────────────────────────────────────


def prossimo_protocollo(anno: int) -> str:
    prefisso = f"NC-{anno}-"
    ultimo = 0
    for prot in Scheda.objects.filter(protocollo__startswith=prefisso).values_list("protocollo", flat=True):
        coda = prot[len(prefisso):]
        if coda.isdigit():
            ultimo = max(ultimo, int(coda))
    return f"{prefisso}{ultimo + 1:04d}"


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
    anno = _anno(row.get("created_datetime"))
    for _ in range(3):
        try:
            with transaction.atomic():
                return Scheda.objects.create(
                    anomalia_id=anomalia_id,
                    protocollo=prossimo_protocollo(anno),
                    op_titolo=op,
                    part_number=pn,
                    origine=Scheda.Origine.PRODUZIONE,
                    gravita=gravita_suggerita(row),
                    disposizione=disposizione_suggerita(row),
                ), True
        except IntegrityError:
            # Doppio salvataggio concorrente: o l'altra richiesta ha gia' creato la
            # scheda (la si riusa) o ha preso lo stesso protocollo (si riprova).
            esistente = Scheda.objects.filter(anomalia_id=anomalia_id).first()
            if esistente is not None:
                return esistente, False
    raise RuntimeError(f"protocollo NC non assegnabile per anomalia {anomalia_id}")


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


# ── Registro NC (ISO 9001 §10.2) ───────────────────────────────────────────


def _conteggio_ricorrenza(scheda: Scheda, giorni: int) -> int:
    if not (scheda.tipo_difetto_id and scheda.part_number):
        return 0
    da = timezone.now() - timedelta(days=giorni)
    return Scheda.objects.filter(
        part_number__iexact=scheda.part_number,
        tipo_difetto_id=scheda.tipo_difetto_id,
        created_at__gte=da,
    ).count()


def motivi_registro_nc(scheda: Scheda, row: dict, cfg: dict | None = None) -> list[str]:
    """Perche' questa anomalia va nel registro NC (lista vuota = resta solo in anomalie)."""
    if cfg is None:
        from .escalation_config import get_escalation_config
        cfg = get_escalation_config()
    motivi = []
    if scheda.gravita in (Scheda.Gravita.MAGGIORE, Scheda.Gravita.CRITICA):
        motivi.append(f"gravità {scheda.get_gravita_display().lower()}")
    if row.get("segnalare_cliente"):
        motivi.append("segnalata al cliente")
    if row.get("aprire_rdc"):
        motivi.append("richiesta di deroga (RDC) al cliente")
    n = _conteggio_ricorrenza(scheda, int(cfg.get("ricorrenza_giorni") or 30))
    if n >= int(cfg.get("ricorrenza_n") or 3):
        motivi.append(
            f"difetto ricorrente: {n} casi sul P/N {scheda.part_number} "
            f"in {int(cfg.get('ricorrenza_giorni') or 30)} giorni"
        )
    return motivi


def _priorita(scheda: Scheda, motivi: list[str]) -> str:
    if scheda.gravita in (Scheda.Gravita.MAGGIORE, Scheda.Gravita.CRITICA):
        return "ALTA"
    return "MEDIA" if motivi else "BASSA"


def _nc_aperta_collegabile(scheda: Scheda):
    """NC aperta dello stesso evento: stesso difetto e stesso OP (o stesso P/N)."""
    from gestione_specifiche.models import RegistroOFI

    qs = (Scheda.objects.exclude(pk=scheda.pk)
          .filter(registro_nc__isnull=False, registro_nc__data_chiusura__isnull=True,
                  tipo_difetto_id=scheda.tipo_difetto_id)
          .exclude(registro_nc__fase=RegistroOFI.FASE_CHIUSO)
          .select_related("registro_nc"))
    stesso_op = qs.filter(op_titolo__iexact=scheda.op_titolo).first() if scheda.op_titolo else None
    if stesso_op is not None:
        return stesso_op.registro_nc
    if scheda.tipo_difetto_id and scheda.part_number:
        stesso_pn = qs.filter(part_number__iexact=scheda.part_number).first()
        if stesso_pn is not None:
            return stesso_pn.registro_nc
    return None


def _riga_scheda(scheda: Scheda, row: dict) -> str:
    parti = [scheda.protocollo, f"OP {scheda.op_titolo or '—'}"]
    if scheda.part_number:
        parti.append(f"P/N {scheda.part_number}")
    if row.get("seriale"):
        parti.append(f"S/N {row.get('seriale')}")
    return " · ".join(parti)


def _testo_nc(scheda: Scheda, row: dict, motivi: list[str]) -> str:
    righe = [_riga_scheda(scheda, row)]
    difetto = scheda.tipo_difetto.nome if scheda.tipo_difetto_id else "da classificare"
    grav = scheda.get_gravita_display() if scheda.gravita else "da valutare"
    righe.append(f"Difetto: {difetto} (gravità {grav.lower()})")
    righe.append(f"Registrata perché: {', '.join(motivi)}")
    desc = str(row.get("descrizione") or "").strip()
    if desc:
        righe += ["", desc]
    return "\n".join(righe)[:5000]


def _collega_a_nc(scheda: Scheda, registro, row: dict, motivi: list[str]) -> None:
    scheda.registro_nc = registro
    scheda.save(update_fields=["registro_nc", "updated_at"])
    riga = f"+ {_riga_scheda(scheda, row)} ({', '.join(motivi)})"
    campi = []
    gia_citata = " ".join([registro.ref or "", registro.opportunita or "", registro.note or ""])
    if scheda.protocollo not in gia_citata:
        registro.note = f"{registro.note}\n{riga}".strip()
        campi.append("note")
    nuova = _priorita(scheda, motivi)
    if _PRIORITA_RANK.get(nuova, 0) > _PRIORITA_RANK.get(registro.priorita, 0):
        registro.priorita = nuova
        campi.append("priorita")
    if campi:
        registro.save(update_fields=[*campi, "updated_at"])


def valuta_registro_nc(scheda: Scheda, row: dict, *, cfg: dict | None = None):
    """Crea o collega la voce NC del registro quando l'anomalia e' significativa."""
    from gestione_specifiche.models import RegistroOFI

    if cfg is None:
        from .escalation_config import get_escalation_config
        cfg = get_escalation_config()
    if scheda.registro_nc_id:
        motivi = motivi_registro_nc(scheda, row, cfg)
        if motivi:
            _collega_a_nc(scheda, scheda.registro_nc, row, motivi)
        return scheda.registro_nc
    if not cfg.get("nc_registro_attivo", True):
        return None
    motivi = motivi_registro_nc(scheda, row, cfg)
    if not motivi:
        return None

    esistente = _nc_aperta_collegabile(scheda)
    if esistente is not None:
        _collega_a_nc(scheda, esistente, row, motivi)
        return esistente

    from django.contrib.contenttypes.models import ContentType
    from gestione_specifiche.registro_ofi import prossimo_numero

    oggi = timezone.localdate()
    priorita = _priorita(scheda, motivi)
    processo = scheda.reparto.nome if scheda.reparto_id else "Produzione"
    op_q = quote(scheda.op_titolo)
    with transaction.atomic():
        registro = RegistroOFI.objects.create(
            numero=prossimo_numero(),
            ref=scheda.protocollo,
            data_apertura=oggi,
            tipo=RegistroOFI.TIPO_NC,
            norma_en9100=True,
            rif_norma=RIF_NORMA_NC,
            processo=processo[:200],
            opportunita=_testo_nc(scheda, row, motivi),
            priorita=priorita,
            data_richiesta=oggi + timedelta(days=GIORNI_CHIUSURA[priorita]),
            # Responsabile dell'analisi ancora da definire: niente solleciti a vuoto.
            reminder_attivo=False,
            allegato_link=f"/gestione-anomalie?op={op_q}" if scheda.op_titolo else "",
            modulo_origine=MODULO_ORIGINE,
            content_type=ContentType.objects.get_for_model(Scheda),
            object_id=scheda.pk,
            note=(
                "Registrata in automatico dal modulo Anomalie. Analisi delle cause "
                "(§10.2.1 b) gestita esternamente: riportarne qui il riferimento."
            ),
        )
        scheda.registro_nc = registro
        scheda.save(update_fields=["registro_nc", "updated_at"])
    return registro


def sync_da_anomalia(anomalia_id: int):
    """Punto d'ingresso dal salvataggio anomalia: scheda + automatici + registro NC."""
    row = legacy_row(anomalia_id)
    if row is None:
        return None
    scheda, _ = get_or_create_scheda(anomalia_id, row=row)
    if scheda is None:
        return None
    aggiorna_automatici(scheda, row)
    valuta_registro_nc(scheda, row)
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
    registro = None
    if scheda.registro_nc_id:
        from django.urls import NoReverseMatch, reverse

        r = scheda.registro_nc
        try:
            url = reverse("registro_ofi:dettaglio", args=[r.pk])
        except NoReverseMatch:
            url = ""
        registro = {
            "numero": r.numero, "fase": r.get_fase_display(), "chiuso": r.is_chiuso,
            "priorita": r.get_priorita_display(), "url": url,
        }
    return {
        "anomalia_id": scheda.anomalia_id,
        "protocollo": scheda.protocollo,
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
        "registro_nc": registro,
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

    def _fk(key, model, **filtri):
        if key not in data:
            return
        raw = data.get(key)
        if raw in (None, "", 0, "0"):
            setattr(scheda, f"{key}_id", None)
            return
        try:
            obj = model.objects.filter(pk=int(raw), **filtri).first()
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
    campi = ("anomalia_id", "tipo_difetto_id", "origine", "disposizione", "gravita", "registro_nc_id")
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
        "registrate_nc": len({r[5] for r in righe if r[5]}),
    }