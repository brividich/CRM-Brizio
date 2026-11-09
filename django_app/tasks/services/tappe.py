"""Percorso del kickoff: le attività base che ogni commessa deve avere a posto.

Arrivo materiali, programma CAM, programma CMM, macchina, terzista, processi
speciali e FAI. Ogni tappa è un tipo attività (``TaskCategory.tappa``): assegnarla
crea un'attività normale (Gantt, «Le mie azioni», mail), quindi non c'è un secondo
registro da tenere allineato. Una tappa che non serve si segna in
``Project.tappe_escluse``.

Per la macchina il percorso legge quello che il portale sa già: abilitati dalla
skill matrix, loro assenze nel periodo, manutenzioni e verifiche dell'asset.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from automazioni.managed_flows import event_flow, flusso_attivo

from ..models import Task, TaskCategory, TaskExtraRef, TaskPriority, TaskStatus, TappaKickoff

logger = logging.getLogger(__name__)

AIUTO = {
    TappaKickoff.MATERIALI: "Chi si occupa del materiale e quando deve essere in casa.",
    TappaKickoff.CAM: "Chi scrive il programma CAM e per quando.",
    TappaKickoff.CMM: "Chi scrive il programma di misura e per quando.",
    TappaKickoff.MACCHINA: "Su quale macchina gira: il portale controlla abilitati, assenze e manutenzione.",
    TappaKickoff.TERZISTA: "Lavorazione esterna: fornitore e data di rientro.",
    TappaKickoff.PROCESSI: "Processo speciale qualificato: quale e per quando.",
    TappaKickoff.FAI: "Chi esegue il FAI e per quando.",
}
# Una sola attività per tappa, tranne dove ha senso averne più di una.
MULTIPLE = {TappaKickoff.MACCHINA, TappaKickoff.TERZISTA, TappaKickoff.PROCESSI}
CAMPO_TESTO = {TappaKickoff.TERZISTA: "fornitore", TappaKickoff.PROCESSI: "processo"}
CAMPO_MACCHINA = "macchina"
TIPI_MACCHINA = ("CNC", "WORK_MACHINE")


class TappaNonValida(ValueError):
    pass


def tipi_per_tappa() -> dict[str, TaskCategory]:
    tipi: dict[str, TaskCategory] = {}
    for cat in TaskCategory.objects.filter(is_active=True).exclude(tappa="").order_by("order_index", "id"):
        tipi.setdefault(cat.tappa, cat)
    return tipi


def _escluse(project) -> set[str]:
    return {str(v) for v in (project.tappe_escluse or []) if v in TappaKickoff.values}


# --- Macchina ---------------------------------------------------------------

def macchine_disponibili():
    from assets.models import Asset

    return (
        Asset.objects.filter(asset_type__in=TIPI_MACCHINA)
        .exclude(status="RETIRED")
        .order_by("asset_tag", "name")
        .only("id", "asset_tag", "name")
    )


def _asset_del_task(task):
    ref = next((r for r in task.extra_refs.all() if r.asset_id and r.field_code == CAMPO_MACCHINA), None)
    return ref.asset if ref else None


def _finestra(task) -> tuple[date, date]:
    oggi = timezone.localdate()
    inizio = task.next_step_due or oggi
    fine = task.due_date or inizio + timedelta(days=14)
    if fine < inizio:
        inizio, fine = fine, inizio
    return inizio, fine


def dettaglio_macchina(task, *, con_nomi: bool) -> dict | None:
    asset = _asset_del_task(task)
    if asset is None:
        return None
    inizio, fine = _finestra(task)
    return disponibilita_macchina(asset, inizio, fine, con_nomi=con_nomi, escludi_task_id=task.pk)


def periodo(inizio: date | None, fine: date | None) -> tuple[date, date]:
    """Periodo da controllare: senza date, da oggi per due settimane."""
    inizio = inizio or timezone.localdate()
    fine = fine or inizio + timedelta(days=14)
    return (fine, inizio) if fine < inizio else (inizio, fine)


def disponibilita_macchina(asset, inizio: date, fine: date, *, con_nomi: bool, escludi_task_id=None) -> dict:
    """Abilitati, assenze nel periodo e impegni dell'asset. Mai un errore a video."""
    task_pk = escludi_task_id
    esito = {"asset": asset, "inizio": inizio, "fine": fine, "abilitati": None, "assenti": [], "impegni": []}
    try:
        from anagrafica.services.skillmatrix_resolver import pool_abilitati

        ids = pool_abilitati(asset)
        esito["abilitati"] = len(ids)
        if ids:
            from assenze.availability import disponibilita_per_anagrafica

            assenze = disponibilita_per_anagrafica(ids, inizio, fine)
            nomi = {}
            if con_nomi and assenze:
                from core import naming
                from core.legacy_anagrafica import fetch_anagrafica_rows

                nomi = {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome"))
                        for r in fetch_anagrafica_rows(ids=list(assenze))}
            for aid, righe in assenze.items():
                if not righe:
                    continue
                # Niente tipo di assenza: al kickoff basta sapere che manca.
                esito["assenti"].append({
                    "nome": nomi.get(int(aid), ""),
                    "periodi": [(r.get("data_inizio"), r.get("data_fine")) for r in righe[:3]],
                })
            esito["disponibili"] = len(ids) - len(esito["assenti"])
    except Exception:
        logger.exception("Percorso kickoff: abilitati/assenze non letti (asset=%s)", asset.pk)
    try:
        from .asset_conflicts import _asset_availability_report

        report = _asset_availability_report(asset, inizio, fine, exclude_task_id=task_pk)
        esito["impegni"] = [
            {"titolo": c.get("title", ""), "quando": c.get("when", ""), "grave": c.get("severity") == "block",
             "url": c.get("url", "")}
            for c in (report.get("conflicts") or [])[:4]
        ]
    except Exception:
        logger.exception("Percorso kickoff: disponibilità asset non letta (asset=%s)", asset.pk)
    return esito


# --- Lettura ----------------------------------------------------------------

def _stato_tappa(attivita: list, esclusa: bool) -> tuple[str, str, str]:
    """(codice, etichetta, classe chip)."""
    if esclusa:
        return "esclusa", "Non serve", ""
    if not attivita:
        return "vuota", "Da assegnare", "warn"
    oggi = timezone.localdate()
    aperte = [t for t in attivita if t.status != TaskStatus.DONE]
    if not aperte:
        return "fatta", "Fatto", ""
    if any(t.due_date and t.due_date < oggi for t in aperte):
        return "ritardo", "In ritardo", "danger"
    if any(t.status == TaskStatus.IN_PROGRESS for t in aperte):
        return "corso", "In corso", "info"
    return "fare", "Da fare", "ok"


def percorso(project, *, con_nomi: bool = False) -> dict:
    tipi = tipi_per_tappa()
    escluse = _escluse(project)
    attivita: dict[str, list] = {}
    if tipi:
        qs = (
            Task.objects.filter(project=project, category__in=tipi.values())
            .exclude(status=TaskStatus.CANCELED)
            .select_related("assigned_to", "category")
            .prefetch_related("extra_refs__asset")
            .order_by("id")
        )
        per_cat = {c.pk: k for k, c in tipi.items()}
        for t in qs:
            attivita.setdefault(per_cat[t.category_id], []).append(t)

    righe = []
    for key, label in TappaKickoff.choices:
        tipo = tipi.get(key)
        if tipo is None:
            continue
        elenco = attivita.get(key, [])
        stato, stato_label, chip = _stato_tappa(elenco, key in escluse)
        voci = []
        for t in elenco:
            # Il nome del tipo è già il titolo della riga: si mostra solo quello che aggiunge.
            breve = t.title[len(tipo.name):].lstrip(" -") if t.title.startswith(tipo.name) else t.title
            voce = {"task": t, "url": reverse("tasks:detail", args=[t.pk]), "dettaglio": "", "titolo_breve": breve or t.title}
            if key in CAMPO_TESTO:
                voce["dettaglio"] = str((t.extra_data or {}).get(CAMPO_TESTO[key]) or "")
            elif key in (TappaKickoff.CAM, TappaKickoff.CMM, TappaKickoff.FAI):
                ref = getattr(t, "tech_ref", None)
                voce["dettaglio"] = ref.code if ref is not None else ""
            elif key == TappaKickoff.MACCHINA:
                voce["macchina"] = dettaglio_macchina(t, con_nomi=con_nomi)
            voci.append(voce)
        righe.append({
            "key": key, "label": label, "aiuto": AIUTO.get(key, ""), "tipo": tipo, "voci": voci,
            "stato": stato, "stato_label": stato_label, "chip": chip,
            "puo_aggiungere": key not in escluse and (not elenco or key in MULTIPLE),
            "puo_escludere": not elenco and key not in escluse,
        })
    a_posto = sum(1 for r in righe if r["stato"] in ("fatta", "esclusa"))
    assegnate = sum(1 for r in righe if r["stato"] != "vuota")
    return {"righe": righe, "totale": len(righe), "a_posto": a_posto, "assegnate": assegnate}


# --- Scrittura --------------------------------------------------------------

def _titolo(key: str, tipo: TaskCategory, *, asset=None, testo: str = "") -> str:
    if key == TappaKickoff.MACCHINA and asset is not None:
        return f"Macchina {asset.asset_tag} {asset.name}".strip()
    if key in CAMPO_TESTO and testo:
        return f"{tipo.name} - {testo}"
    return tipo.name


@transaction.atomic
def assegna(
    project, key: str, user, *, assigned_to=None, due_date=None, start_date=None, asset=None, testo: str = "",
    meeting=None, outlook: bool = False, request=None,
) -> Task:
    from .meeting_tasks import (
        KickoffBloccatoVRF,
        kickoff_bloccato_vrf,
        meeting_task_marker,
        notify_task_assignment,
        titolo_attivita,
    )

    tipo = tipi_per_tappa().get(key)
    if tipo is None:
        raise TappaNonValida("Tappa non configurata: controlla i tipi attività in Impostazioni.")
    if key == TappaKickoff.MACCHINA and asset is None:
        raise TappaNonValida("Scegli la macchina.")
    if key in CAMPO_TESTO and not testo:
        raise TappaNonValida("Scegli il fornitore." if key == TappaKickoff.TERZISTA else "Scegli il processo.")
    if key not in MULTIPLE and Task.objects.filter(project=project, category=tipo).exclude(status=TaskStatus.CANCELED).exists():
        raise TappaNonValida("Questa tappa ha già la sua attività.")
    if start_date and due_date and due_date < start_date:
        raise TappaNonValida("«Entro il» non può venire prima dell'inizio.")
    if kickoff_bloccato_vrf(project):
        raise KickoffBloccatoVRF()

    oggi = timezone.localdate()
    if meeting is not None:
        data = f"{meeting.data:%d-%m-%Y}" if hasattr(meeting.data, "strftime") else str(meeting.data or "")
        descrizione = f"{meeting_task_marker(meeting)}{data}). Percorso del kickoff."
    else:
        descrizione = "Percorso del kickoff."
    extra = {}
    if asset is not None:
        extra[CAMPO_MACCHINA] = asset.pk
    if key in CAMPO_TESTO:
        extra[CAMPO_TESTO[key]] = testo[:200]
    task = Task.objects.create(
        title=titolo_attivita(_titolo(key, tipo, asset=asset, testo=testo)),
        project=project,
        assigned_to=assigned_to,
        category=tipo,
        next_step_due=start_date or (min(oggi, due_date) if due_date else oggi),
        due_date=due_date,
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
        created_by=user,
        description=descrizione,
        extra_data=extra,
    )
    if asset is not None:
        TaskExtraRef.objects.create(task=task, field_code=CAMPO_MACCHINA, asset=asset)
    if key in _escluse(project):
        project.tappe_escluse = [v for v in project.tappe_escluse if v != key]
        project.save(update_fields=["tappe_escluse"])
    notify_task_assignment(task, actor=user)
    dopo_assegnazione(task, outlook=outlook, request=request)
    return task


# --- Flussi (automazioni → eventi applicativi, spenti di default) ---------------

@event_flow("kickoff_promemoria_scadenza", skipped_result=False)
def promemoria_scadenza(task) -> bool:
    from ..outlook_reminder import sync_task_portal_reminder

    sync_task_portal_reminder(task=task)
    return True


@event_flow("kickoff_evento_outlook", skipped_result="")
def evento_outlook(task, request=None) -> str:
    from ..outlook_reminder import sync_task_outlook_event

    _livello, messaggio = sync_task_outlook_event(request=request, task=task, requested=True, explicit_email="")
    return messaggio


def outlook_disponibile() -> bool:
    return flusso_attivo("kickoff_evento_outlook")


def dopo_assegnazione(task, *, outlook: bool = False, request=None) -> None:
    """Dopo il salvataggio: promemoria ed evento Outlook, se i flussi sono accesi. Mai bloccante."""
    def esegui():
        try:
            promemoria_scadenza(task)
        except Exception:
            logger.exception("Promemoria tappa non preparato (task=%s)", task.pk)
        if outlook and task.due_date:
            try:
                evento_outlook(task, request)
            except Exception:
                logger.exception("Evento Outlook tappa non creato (task=%s)", task.pk)

    transaction.on_commit(esegui)


def escludi(project, key: str, *, valore: bool) -> None:
    if key not in TappaKickoff.values:
        raise TappaNonValida("Tappa non valida.")
    escluse = _escluse(project)
    if valore:
        tipo = tipi_per_tappa().get(key)
        if tipo and Task.objects.filter(project=project, category=tipo).exclude(status=TaskStatus.CANCELED).exists():
            raise TappaNonValida("La tappa ha già un'attività: annullala prima di dire che non serve.")
        escluse.add(key)
    else:
        escluse.discard(key)
    project.tappe_escluse = [k for k in TappaKickoff.values if k in escluse]
    project.save(update_fields=["tappe_escluse"])


def assenze_persona(user, inizio: date, fine: date) -> list[tuple[date, date]]:
    """Periodi di assenza del responsabile nel periodo, senza il motivo."""
    if user is None:
        return []
    try:
        from .absences import _load_user_absences

        return [(r["start_date"], r["end_date"]) for r in _load_user_absences(user, date_start=inizio, date_end=fine)][:4]
    except Exception:
        logger.exception("Percorso kickoff: assenze del responsabile non lette (user=%s)", getattr(user, "pk", None))
        return []
