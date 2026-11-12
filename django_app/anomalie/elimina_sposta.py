"""Eliminare o spostare («Taglia») una singola anomalia finché nessuno ci ha lavorato.

- **Elimina**: solo chi l'ha inserita. La riga legacy sparisce con scheda, dati
  del controllo e timeline; gli allegati vanno in ``_eliminate/`` (recuperabili)
  e l'audit del portale conserva testo, OP e S/N.
- **Taglia**: sposta l'anomalia su un altro S/N dello stesso OP o di un altro OP.
  Stesso OP: resta nel controllo, nel blocco che ha già quei seriali (o in uno
  nuovo). Altro OP: esce dal controllo, passa alla NC del nuovo OP e il suo
  capocommessa la riceve nel riepilogo delle modifiche.

In entrambi i casi l'anomalia non deve avere avanzamenti (``motivi_avanzamento``).
"""
from __future__ import annotations

import logging
import shutil

from django.db import connections, transaction
from django.utils import timezone

from . import controllo_service as cs
from .seriali import espandi_voce, etichetta_blocco, normalizza_voci

logger = logging.getLogger(__name__)

# Azioni di timeline che vogliono dire «qualcuno ci ha già lavorato».
AZIONI_AVANZAMENTO = frozenset({
    "prendi_in_carico", "approva", "respingi", "richiedi_modifica", "chiudi",
    "riapri", "risposta_cliente", "risposta_terzista", "azione", "segnalato", "aggiorna_avanzamento",
})


def riga(local_id: int) -> dict | None:
    from .qualita_service import legacy_row

    return legacy_row(int(local_id))


def motivi_avanzamento(local_id: int, row: dict | None = None) -> list[str]:
    """Perché l'anomalia non si può più eliminare né spostare (vuota = si può)."""
    from .mail_action_models import AnomaliaActionLog
    from .quality_models import AnomaliaEsito, AnomaliaSchedaQualita

    row = row if row is not None else riga(local_id)
    if row is None:
        return ["anomalia non trovata"]
    motivi: list[str] = []
    if row.get("chiudere"):
        motivi.append("è chiusa")
    elif cs.riga_gestita(row):
        motivi.append("il capocommessa ha già preso una decisione")
    scheda = AnomaliaSchedaQualita.objects.filter(anomalia_id=local_id).first()
    if scheda is not None and (
        scheda.segnala_terzista or scheda.segnala_car or scheda.segnalato_cliente_il or scheda.segnalato_terzista_il
    ) and not motivi:
        motivi.append("il capocommessa ha già preso una decisione")
    if AnomaliaEsito.objects.filter(anomalia_id=local_id).exists():
        motivi.append("ci sono risposte del cliente o azioni registrate")
    if AnomaliaActionLog.objects.filter(anomalia_id=local_id, action__in=AZIONI_AVANZAMENTO).exists() and not motivi:
        motivi.append("è già stata presa in carico")
    return motivi


def testo_motivi(motivi: list[str]) -> str:
    return "; ".join(motivi)


# ── Pulizia delle code di notifica ─────────────────────────────────────────


def _togli_da_controllo(controllo_id, local_id: int) -> None:
    from .quality_models import AnomaliaControllo

    if not controllo_id:
        return
    controllo = AnomaliaControllo.objects.filter(pk=controllo_id).first()
    if controllo is None:
        return
    pending = [int(i) for i in (controllo.da_notificare or []) if str(i).isdigit() and int(i) != int(local_id)]
    if pending != list(controllo.da_notificare or []):
        controllo.da_notificare = pending
        controllo.save(update_fields=["da_notificare", "updated_at"])


def _togli_da_riepilogo(op_id: str, local_id: int) -> None:
    """Toglie l'anomalia dal riepilogo modifiche non ancora inviato dell'OP."""
    from .mail_action_models import AnomaliaPendingNotification

    for p in AnomaliaPendingNotification.objects.filter(op_id__iexact=str(op_id or "").strip(), notified=False):
        snapshot = p.updates_snapshot if isinstance(p.updates_snapshot, list) else []
        nuovo = [u for u in snapshot if str((u or {}).get("id")) != str(local_id)]
        if len(nuovo) != len(snapshot):
            p.updates_snapshot = nuovo
            # Nessuna modifica rimasta: niente mail vuota.
            p.notified = not nuovo
            p.save(update_fields=["updates_snapshot", "notified"])


def _blocco_vuoto_via(blocco_id) -> None:
    """Un blocco del controllo senza più anomalie non ha motivo di restare."""
    from .quality_models import AnomaliaBlocco, AnomaliaSegnalazioneMeta

    if blocco_id and not AnomaliaSegnalazioneMeta.objects.filter(blocco_id=blocco_id).exists():
        AnomaliaBlocco.objects.filter(pk=blocco_id).delete()


def _allegati_in_cestino(local_id: int) -> str:
    """Sposta la cartella allegati in ``_eliminate/<id>_<data>``: si recupera a mano."""
    from .views import _anomalie_attachments_root, _attachment_dir_for_local

    try:
        cartella = _attachment_dir_for_local(local_id)
        if not cartella.exists() or not any(cartella.iterdir()):
            return ""
        cestino = _anomalie_attachments_root() / "_eliminate"
        cestino.mkdir(parents=True, exist_ok=True)
        dest = cestino / f"{local_id}_{timezone.now().strftime('%Y%m%d%H%M%S')}"
        shutil.move(str(cartella), str(dest))
        return str(dest)
    except Exception:
        logger.warning("elimina anomalia %s: allegati non spostati", local_id, exc_info=True)
        return ""


# ── Elimina ────────────────────────────────────────────────────────────────


def elimina(local_id: int) -> dict:
    """Elimina la riga e i suoi dati collegati. Ritorna l'istantanea per l'audit."""
    from .mail_action_models import AnomaliaActionLog
    from .nc_service import ricalcola_stato, registra_evento
    from .quality_models import AnomaliaSchedaQualita, AnomaliaSegnalazioneMeta

    row = riga(local_id) or {}
    op_id = str(row.get("ex_op_nominativo") or "").strip()
    meta = AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=local_id).first()
    scheda = AnomaliaSchedaQualita.objects.filter(anomalia_id=local_id).select_related("nc").first()
    nc = scheda.nc if scheda is not None and scheda.nc_id else None
    istantanea = {
        "local_id": local_id,
        "op_id": op_id,
        "seriale": str(row.get("seriale") or ""),
        "descrizione": str(row.get("descrizione") or "")[:2000],
        "fase": meta.fase if meta else "",
        "controllo_id": meta.controllo_id if meta else None,
        "blocco_id": meta.blocco_id if meta else None,
        "dettaglio_controllo": scheda.dettaglio_controllo if scheda is not None else {},
    }
    with transaction.atomic():
        with connections["default"].cursor() as cur:
            cur.execute("DELETE FROM anomalie WHERE id = %s", [local_id])
        if meta is not None:
            meta.delete()  # anche le descrizioni multiple (CASCADE)
        if scheda is not None:
            scheda.delete()
        # Solo creazione/modifiche/visualizzazioni (gli avanzamenti bloccano l'eliminazione):
        # l'audit del portale ne conserva la traccia, qui non devono restare orfane.
        AnomaliaActionLog.objects.filter(anomalia_id=local_id).delete()
        if meta is not None:
            _blocco_vuoto_via(meta.blocco_id)
    if meta is not None:
        _togli_da_controllo(meta.controllo_id, local_id)
    _togli_da_riepilogo(op_id, local_id)
    istantanea["allegati_in"] = _allegati_in_cestino(local_id)
    if nc is not None:
        sn = istantanea["seriale"]
        registra_evento(nc, "anomalia", f"Anomalia #{local_id} eliminata da chi l'aveva inserita{f' (S/N {sn})' if sn else ''}")
        try:
            ricalcola_stato(nc)
        except Exception:
            logger.warning("elimina anomalia %s: stato NC non ricalcolato", local_id, exc_info=True)
    return istantanea


# ── Taglia (sposta) ────────────────────────────────────────────────────────


def _tokens(voci) -> set[str]:
    return {t.lower() for v in voci or [] for t in espandi_voce(v)}


def _blocco_per(controllo, voci: list[str], origine):
    """Blocco del controllo che contiene già tutti quei seriali, se no uno nuovo
    (stessa fase e stato superficie del blocco di partenza)."""
    from .quality_models import AnomaliaBlocco

    cercati = _tokens(voci)
    for blocco in controllo.blocchi.all().order_by("ordine", "id"):
        if cercati and cercati <= _tokens(blocco.seriali if isinstance(blocco.seriali, list) else []):
            return blocco
    ultimo = controllo.blocchi.order_by("-ordine").values_list("ordine", flat=True).first()
    return AnomaliaBlocco.objects.create(
        controllo=controllo,
        ordine=(ultimo or 0) + 1,
        fase=(origine.fase if origine is not None else controllo.fase),
        seriali=voci,
        seriale_label=etichetta_blocco(voci),
        stato_superficie=(origine.stato_superficie if origine is not None and isinstance(origine.stato_superficie, list) else []),
    )


def sposta(local_id: int, *, op_dest: str, op_dest_item_id, voci: list[str]) -> dict:
    """Sposta l'anomalia. Ritorna ``{"da": {...}, "a": {...}, "cambia_op": bool}``."""
    from .nc_service import ricalcola_stato, registra_evento
    from .quality_models import AnomaliaSchedaQualita, AnomaliaSegnalazioneMeta

    voci = normalizza_voci(voci)
    row = riga(local_id) or {}
    op_da = str(row.get("ex_op_nominativo") or "").strip()
    sn_da = str(row.get("seriale") or "")
    cambia_op = op_da.lower() != op_dest.strip().lower()
    meta = AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=local_id).select_related("blocco", "controllo").first()
    blocco_da = meta.blocco if meta is not None and meta.blocco_id else None
    controllo_da = meta.controllo_id if meta is not None else None

    with transaction.atomic():
        blocco_a = None
        if meta is not None and not cambia_op and meta.controllo_id:
            blocco_a = _blocco_per(meta.controllo, voci, blocco_da)
        # Etichetta della colonna ``seriale``: come «Salva blocco» (sottoinsieme del blocco o blocco intero).
        sn_a = etichetta_blocco(voci)
        if blocco_a is not None and _tokens(voci) == _tokens(blocco_a.seriali):
            sn_a = blocco_a.seriale_label or sn_a
        sets = ["seriale = %s", "ex_op_nominativo = %s"]
        params: list = [sn_a, op_dest.strip()[:100]]
        from core.legacy_utils import legacy_table_columns

        cols = legacy_table_columns("anomalie") or set()
        if "op_lookup_id" in cols and cambia_op:
            from .views import _resolve_op_lookup_id

            sets.append("op_lookup_id = %s")
            params.append(_resolve_op_lookup_id(op_dest_item_id, op_dest))
        if "modified_datetime" in cols:
            sets.append("modified_datetime = SYSUTCDATETIME()" if connections["default"].vendor != "sqlite"
                        else "modified_datetime = CURRENT_TIMESTAMP")
        with connections["default"].cursor() as cur:
            cur.execute(f"UPDATE anomalie SET {', '.join(sets)} WHERE id = %s", params + [local_id])

        if meta is not None:
            if cambia_op:
                meta.controllo = None
                meta.blocco = None
                meta.nc = None
            else:
                meta.blocco = blocco_a if blocco_a is not None else meta.blocco
            meta.save()
            if blocco_da is not None and (blocco_a is None or blocco_a.pk != blocco_da.pk):
                _blocco_vuoto_via(blocco_da.pk)

        nc_da = None
        scheda = AnomaliaSchedaQualita.objects.filter(anomalia_id=local_id).select_related("nc").first()
        if scheda is not None and cambia_op:
            from .mail_action_service import _fetch_pn_for_ops

            nc_da = scheda.nc if scheda.nc_id else None
            scheda.op_titolo = op_dest.strip()[:100]
            scheda.part_number = ((_fetch_pn_for_ops([op_dest.strip()]) or {}).get(op_dest.strip().lower(), "") or "")[:120]
            scheda.nc = None
            scheda.save(update_fields=["op_titolo", "part_number", "nc", "updated_at"])

    if cambia_op:
        _togli_da_controllo(controllo_da, local_id)
        _togli_da_riepilogo(op_da, local_id)
        if nc_da is not None:
            registra_evento(nc_da, "anomalia", f"Anomalia #{local_id} spostata sull'OP {op_dest.strip()}")
            try:
                ricalcola_stato(nc_da)
            except Exception:
                logger.warning("sposta anomalia %s: stato NC non ricalcolato", local_id, exc_info=True)
    try:
        from .qualita_service import sync_da_anomalia

        with transaction.atomic():
            nuova = sync_da_anomalia(local_id)
            if nuova is not None and nuova.nc_id:
                AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=local_id).update(nc_id=nuova.nc_id)
    except Exception:
        logger.warning("sposta anomalia %s: scheda qualita' non aggiornata", local_id, exc_info=True)
    return {
        "da": {"op_id": op_da, "seriale": sn_da},
        "a": {"op_id": op_dest.strip(), "seriale": sn_a},
        "cambia_op": cambia_op,
        "controllo_id": None if cambia_op else controllo_da,
        "descrizione": str(row.get("descrizione") or ""),
        "avanzamento": str(row.get("avanzamento") or ""),
    }


def ids_con_avanzamenti(ids) -> set[int]:
    """Fra gli id, quelli con esiti, decisioni di scheda o azioni di avanzamento
    (in blocco, per l'elenco di Gestione anomalie; la riga legacy va vista a parte)."""
    from django.db.models import Q

    from .mail_action_models import AnomaliaActionLog
    from .quality_models import AnomaliaEsito, AnomaliaSchedaQualita

    ids = [int(i) for i in ids if str(i or "").isdigit()]
    if not ids:
        return set()
    out = set(AnomaliaEsito.objects.filter(anomalia_id__in=ids).values_list("anomalia_id", flat=True))
    out |= set(AnomaliaActionLog.objects.filter(
        anomalia_id__in=ids, action__in=AZIONI_AVANZAMENTO,
    ).values_list("anomalia_id", flat=True))
    out |= set(AnomaliaSchedaQualita.objects.filter(anomalia_id__in=ids).filter(
        Q(segnala_terzista=True) | Q(segnala_car=True)
        | Q(segnalato_cliente_il__isnull=False) | Q(segnalato_terzista_il__isnull=False)
    ).values_list("anomalia_id", flat=True))
    return out


# ── Cambio OP di un controllo intero (dati inseriti sull'OP sbagliato) ─────


def cambia_op_controllo(controllo, *, op_dest: str, op_dest_item_id) -> dict:
    """Porta il controllo e tutte le sue anomalie su un altro OP.

    Solo se nessuna anomalia ha avanzamenti (``ValueError`` con il motivo). Ritorna
    ``{"ids", "gia_comunicate", "op_da"}``: le già comunicate vanno nel riepilogo del nuovo OP.
    """
    from core.legacy_utils import legacy_table_columns

    from .mail_action_service import _fetch_pn_for_ops
    from .nc_service import ricalcola_stato, registra_evento
    from .quality_models import AnomaliaSchedaQualita, AnomaliaSegnalazioneMeta
    from .qualita_service import legacy_rows
    from .views import _resolve_op_lookup_id

    op_dest = op_dest.strip()[:100]
    op_da = controllo.op_id
    ids = list(AnomaliaSegnalazioneMeta.objects.filter(controllo=controllo).values_list("anomalia_id", flat=True))
    righe = legacy_rows(ids) if ids else {}
    bloccate = [f"#{i} ({testo_motivi(m)})" for i in ids if (m := motivi_avanzamento(i, righe.get(i)))]
    if bloccate:
        raise ValueError("Alcune anomalie hanno già avanzamenti e non si possono spostare: " + "; ".join(bloccate))
    cols = legacy_table_columns("anomalie") or set()
    lookup = _resolve_op_lookup_id(op_dest_item_id, op_dest) if "op_lookup_id" in cols else None
    pn = ((_fetch_pn_for_ops([op_dest]) or {}).get(op_dest.lower(), "") or "")[:120]
    nc_vecchie = {}
    with transaction.atomic():
        if ids:
            sets, params = ["ex_op_nominativo = %s"], [op_dest]
            if "op_lookup_id" in cols:
                sets.append("op_lookup_id = %s")
                params.append(lookup)
            ph = ",".join(["%s"] * len(ids))
            with connections["default"].cursor() as cur:
                cur.execute(f"UPDATE anomalie SET {', '.join(sets)} WHERE id IN ({ph})", params + ids)
            for scheda in AnomaliaSchedaQualita.objects.filter(anomalia_id__in=ids).select_related("nc"):
                if scheda.nc_id:
                    nc_vecchie[scheda.nc_id] = scheda.nc
                scheda.op_titolo, scheda.part_number, scheda.nc = op_dest, pn, None
                scheda.save(update_fields=["op_titolo", "part_number", "nc", "updated_at"])
            AnomaliaSegnalazioneMeta.objects.filter(anomalia_id__in=ids).update(nc=None)
        pending = [int(i) for i in (controllo.da_notificare or []) if str(i).isdigit()]
        controllo.op_id = op_dest
        controllo.op_item_id = str(op_dest_item_id or "")[:100]
        controllo.op_nuovo = {}
        controllo.save(update_fields=["op_id", "op_item_id", "op_nuovo", "updated_at"])
    for i in ids:
        _togli_da_riepilogo(op_da, i)
    for nc in nc_vecchie.values():
        registra_evento(nc, "anomalia", f"{len(ids)} anomalie del controllo #{controllo.pk} spostate sull'OP {op_dest}")
        try:
            ricalcola_stato(nc)
        except Exception:
            logger.warning("cambio OP controllo %s: stato NC non ricalcolato", controllo.pk, exc_info=True)
    from .qualita_service import sync_da_anomalia

    for i in ids:
        try:
            with transaction.atomic():
                scheda = sync_da_anomalia(i)
                if scheda is not None and scheda.nc_id:
                    AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=i).update(nc_id=scheda.nc_id)
        except Exception:
            logger.warning("cambio OP controllo: scheda %s non aggiornata", i, exc_info=True)
    return {"ids": ids, "gia_comunicate": [i for i in ids if i not in pending], "op_da": op_da, "righe": righe}
