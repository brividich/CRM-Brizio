"""Ponte di integrazione tra Carichi Macchina e KICK-OFF (modulo tasks).

Il join è l'**Asset**: una `Macchina` È un `assets.Asset` (OneToOne) e un'attività
KICK-OFF "usa" quella macchina quando referenzia lo stesso Asset (via `TaskExtraRef`).

Tutte le funzioni sono **fail-safe** e di **sola lettura**, tranne il sync esplicito
(`sync_kickoff_task_to_pianificazione`). Per scelta di prodotto l'integrazione è
**non bloccante**: produce avvisi e letture incrociate, mai blocchi.
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta

logger = logging.getLogger(__name__)


def macchina_for_asset(asset_id):
    """Profilo Macchina collegato a un asset, o None."""
    if not asset_id:
        return None
    try:
        from .models import Macchina

        return Macchina.objects.filter(asset_id=asset_id).select_related("asset").first()
    except Exception:
        return None


def _pian_span_days(pian, macchina) -> int:
    """Giorni occupati da una pianificazione (ore / ore_giorno_disponibili, min 1)."""
    try:
        ore = float(pian.ore or 0)
        ogg = float(getattr(macchina, "ore_giorno_disponibili", 0) or 0) or 8.0
        if ore <= 0:
            return 1
        return max(1, math.ceil(ore / ogg))
    except Exception:
        return 1


def pianificazioni_for_asset(asset_id, start, end):
    """Pianificazioni Carichi sovrapposte a [start, end] sulla macchina dell'asset.

    Read-only: list[dict] per avvisi/overlay lato KICK-OFF. [] se l'asset non è una
    macchina o la finestra non è valida.
    """
    mac = macchina_for_asset(asset_id)
    if mac is None or not start or not end:
        return []
    out = []
    try:
        from .models import Pianificazione

        # Le più RECENTI prima: le righe sovrapposte a [start, end] hanno data vicina a
        # `end`; con un ordinamento ascendente + cap, su macchine con storico ampio lo
        # slice tiene le più vecchie (quasi tutte non sovrapposte) e perde proprio quelle
        # rilevanti. Prendiamo le ultime e riordiniamo cronologicamente in output.
        qs = (
            Pianificazione.objects.filter(macchina=mac, data__lte=end)
            .select_related("commessa", "famiglia")
            .order_by("-data", "-id")
        )
        for p in qs[:300]:
            span = _pian_span_days(p, mac)
            p_end = p.data + timedelta(days=span - 1)
            if p_end < start:
                continue
            out.append({
                "id": p.id,
                "data": p.data,
                "fine": p_end,
                "span": span,
                "ore": float(p.ore or 0),
                "qta": p.qta,
                "stato": p.stato,
                "fonte": p.fonte,
                "commessa": (p.commessa.numero or p.commessa.nome) if p.commessa_id else "",
                "label": (p.testo_originale or "")[:80] or (p.famiglia.nome if p.famiglia_id else ""),
                "is_kickoff": p.fonte == Pianificazione.FONTE_KICKOFF,
            })
        out.sort(key=lambda r: (r["data"], r["id"]))  # output cronologico
    except Exception:
        logger.warning("pianificazioni_for_asset fallita asset=%s", asset_id, exc_info=True)
    return out


def kickoff_tasks_for_asset(asset_id, start, end, *, exclude_task_id=None):
    """Attività KICK-OFF attive che usano l'asset e si sovrappongono a [start, end].

    Read-only: list[dict] per overlay/avvisi lato Carichi Macchina.
    """
    if not asset_id or not start or not end:
        return []
    out = []
    try:
        from tasks.models import TaskExtraRef, TaskStatus

        qs = (
            TaskExtraRef.objects.filter(asset_id=asset_id)
            .exclude(task__status__in=[TaskStatus.DONE, TaskStatus.CANCELED])
            .select_related("task", "task__project")
        )
        if exclude_task_id:
            qs = qs.exclude(task_id=exclude_task_id)
        seen: set[int] = set()
        for ref in qs[:200]:
            t = ref.task
            if t.id in seen:
                continue
            s = t.next_step_due or t.due_date
            e = t.due_date or t.next_step_due
            if not s or not e:
                continue
            if e < s:
                s, e = e, s
            if not (s <= end and start <= e):
                continue
            seen.add(t.id)
            out.append({
                "task_id": t.id,
                "title": t.title,
                "start": s,
                "end": e,
                "status": t.status,
                "project": t.project.name if t.project_id else "",
                "project_id": t.project_id,
            })
    except Exception:
        logger.warning("kickoff_tasks_for_asset fallita asset=%s", asset_id, exc_info=True)
    return out


def _commessa_for_project(project_id):
    if not project_id:
        return None
    try:
        from .models import Commessa

        return Commessa.objects.filter(kickoff_project_id=project_id).first()
    except Exception:
        return None


def sync_kickoff_task_to_pianificazione(task, *, user=None):
    """Up-sert (o rimozione) della Pianificazione Carichi collegata a una task KICK-OFF.

    Non bloccante / fail-safe. Tocca SOLO pianificazioni con fonte=kickoff legate a
    questa task (mai quelle manuali/import/ai). Regole:
    - task 'lavoro macchina', non chiusa/annullata, con data inizio e un asset che
      ha un profilo Macchina -> crea/aggiorna 1 pianificazione (data = inizio task);
    - altrimenti rimuove l'eventuale pianificazione kickoff già generata.

    Ritorna ('created'|'updated'|'removed'|'noop', Pianificazione|None).
    """
    try:
        from tasks.models import TaskStatus

        from .models import Pianificazione
    except Exception:
        return ("noop", None)

    try:
        existing = Pianificazione.objects.filter(
            kickoff_task=task, fonte=Pianificazione.FONTE_KICKOFF
        ).first()

        def _remove():
            if existing:
                existing.delete()
                return ("removed", None)
            return ("noop", None)

        is_machine = bool(getattr(getattr(task, "category", None), "is_machine_work", False))
        if not is_machine or task.status in (TaskStatus.DONE, TaskStatus.CANCELED):
            return _remove()

        start = task.next_step_due or task.due_date
        if not start:
            return _remove()

        mac = None
        for ref in task.extra_refs.filter(asset__isnull=False).select_related("asset"):
            mac = macchina_for_asset(ref.asset_id)
            if mac:
                break
        if mac is None:
            return _remove()

        end = task.due_date or start
        if end < start:
            start, end = end, start
        span_days = max(1, (end - start).days + 1)
        ogg = float(getattr(mac, "ore_giorno_disponibili", 8) or 8)
        ore = round(ogg * span_days, 2)
        commessa = _commessa_for_project(task.project_id)
        stato = (
            Pianificazione.STATO_IN_CORSO
            if task.status == TaskStatus.IN_PROGRESS
            else Pianificazione.STATO_PIANIFICATA
        )

        if existing:
            existing.macchina = mac
            existing.data = start
            existing.ore = ore
            existing.stato = stato
            existing.commessa = commessa
            existing.testo_originale = (task.title or "")[:200]
            existing.save()
            return ("updated", existing)

        p = Pianificazione.objects.create(
            macchina=mac,
            data=start,
            ore=ore,
            stato=stato,
            commessa=commessa,
            fonte=Pianificazione.FONTE_KICKOFF,
            kickoff_task=task,
            testo_originale=(task.title or "")[:200],
        )
        return ("created", p)
    except Exception:
        logger.warning(
            "sync_kickoff_task_to_pianificazione fallita task=%s",
            getattr(task, "id", None),
            exc_info=True,
        )
        return ("noop", None)


# ---------------------------------------------------------------------------
# Overlay "abilitati assenti" (Skill Matrix MOD.187 × modulo assenze)
# ---------------------------------------------------------------------------
# Per ogni macchina sappiamo (via Skill Matrix) chi è abilitato a operarla; il
# modulo assenze sa chi è assente e quando. L'incrocio segnala — in modo NON
# bloccante — i giorni in cui parte del pool operativo è già a casa, così la
# pianificazione tiene conto della manodopera realmente disponibile.


def _severita_assenze(n: int, tot: int) -> str:
    """Severità (colore) in base al numero di assenti e alla quota del pool.

    bassa = 1 assente / quota bassa · media = 2 o ~1/3 · alta = ≥3 o ~2/3+.
    """
    if n <= 0:
        return "bassa"
    frac = (n / tot) if tot else 1.0
    if n >= 3 or frac >= 0.66:
        return "alta"
    if n == 2 or frac >= 0.34:
        return "media"
    return "bassa"


def _aggrega_assenze_giorni(pool_by_asset, assenze_by_aid, giorni) -> dict:
    """Aggrega per (asset, giorno) gli operatori assenti. Funzione pura (no DB).

    Ritorna ``{asset_id: {giorno(date): {"n", "tot", "nomi": [(nome, tipo)], "sev"}}}``.
    ``pool_by_asset``: {asset_id: [legacy_anagrafica_id]}; ``assenze_by_aid``:
    {legacy_id: [{"data_inizio", "data_fine", "tipo", "nome"}]}; ``giorni``: lista date.
    """
    out: dict = {}
    if not pool_by_asset or not assenze_by_aid or not giorni:
        return out
    for asset_id, operatori in pool_by_asset.items():
        tot = len(operatori)
        if not tot:
            continue
        per_giorno: dict = {}
        for aid in operatori:
            for ass in assenze_by_aid.get(aid, []):
                di = ass.get("data_inizio")
                df = ass.get("data_fine")
                if not di or not df:
                    continue
                for g in giorni:
                    if di <= g <= df:
                        slot = per_giorno.setdefault(g, {"aids": set(), "nomi": []})
                        if aid not in slot["aids"]:
                            slot["aids"].add(aid)
                            slot["nomi"].append(
                                (ass.get("nome") or f"ID {aid}", ass.get("tipo") or "Assenza")
                            )
        giorni_info = {}
        for g, slot in per_giorno.items():
            n = len(slot["aids"])
            giorni_info[g] = {
                "n": n, "tot": tot,
                "nomi": slot["nomi"], "sev": _severita_assenze(n, tot),
            }
        if giorni_info:
            out[asset_id] = giorni_info
    return out


def assenze_overlay_for_assets(asset_ids, giorni) -> dict:
    """Overlay abilitati-assenti per le macchine, sui giorni della finestra Gantt.

    Read-only, **fail-safe** e **additivo**: se la Skill Matrix non è ancora
    popolata o il modulo assenze non risponde, ritorna ``{}`` e il Gantt resta
    identico a prima. Per scelta di prodotto non blocca mai la pianificazione.

    Ritorna ``{asset_id: {giorno(date): {"n", "tot", "nomi", "sev"}}}``.
    """
    ids = sorted({int(a) for a in (asset_ids or []) if a})
    if not ids or not giorni:
        return {}
    try:
        from anagrafica.services import skillmatrix_resolver as resolver

        from assenze.availability import assenze_per_anagrafica

        # Pool = operatori al livello operativo di config (capacità reale della macchina).
        pool_by_asset = resolver.pool_abilitati_bulk(ids)
        if not pool_by_asset:
            return {}
        all_ids = sorted({lid for ops in pool_by_asset.values() for lid in ops})
        assenze_by_aid = assenze_per_anagrafica(all_ids, giorni[0], giorni[-1])
        if not assenze_by_aid:
            return {}
        return _aggrega_assenze_giorni(pool_by_asset, assenze_by_aid, giorni)
    except Exception:
        logger.warning("assenze_overlay_for_assets fallita (assets=%d)", len(ids), exc_info=True)
        return {}


def autolink_commessa_to_project(commessa) -> bool:
    """Aggancio automatico Commessa -> Project KICK-OFF per part number / numero / nome.

    Non sovrascrive un collegamento esistente. Ritorna True se ha collegato.
    """
    if getattr(commessa, "kickoff_project_id", None):
        return False
    try:
        from tasks.models import Project

        for raw in (commessa.numero, commessa.pezzo, commessa.nome):
            k = str(raw or "").strip()
            if not k:
                continue
            proj = (
                Project.objects.filter(part_number__iexact=k).first()
                or Project.objects.filter(name__iexact=k).first()
            )
            if proj:
                commessa.kickoff_project = proj
                commessa.save(update_fields=["kickoff_project"])
                return True
    except Exception:
        logger.warning(
            "autolink_commessa_to_project fallita commessa=%s",
            getattr(commessa, "id", None),
            exc_info=True,
        )
    return False
