"""Testata unica di commessa: stessa intestazione su tutte le pagine del kickoff.

Prima ogni pagina (Panoramica, Piano, Incontri, VRF, Programmi) aveva titolo,
pillole e pulsanti propri, e la stessa cosa si faceva da nomi diversi. Qui si
decide in un punto solo cosa mostrare: i dati della commessa, **una** azione
primaria che dipende dallo stato, «+ Attività» e il menu «Altro».
"""
from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from ..models import MeetingStatus, VRFDocStatus

# Sezioni di commessa: (chiave tab, etichetta, pagine che la tengono accesa).
SEZIONI = {
    "overview": "panoramica",
    "actions": "piano",
    "gantt": "piano",
    "board": "piano",
    "meetings": "incontri",
    "decisions": "incontri",
    "vrf": "documenti",
    "tech_refs": "documenti",
}


def sezione_di(active: str) -> str:
    """Tab di commessa a cui appartiene la pagina (``""`` se nessuna)."""
    return SEZIONI.get(active, "")


def _vrf_url(project) -> str:
    nome = "tasks:project_vrf_compile" if project.vrf_status == VRFDocStatus.PENDING else "tasks:project_vrf_upload"
    return reverse(nome, args=[project.pk])


def testata_commessa(request, project, *, puo_creare: bool) -> dict:
    """Dati della testata: consegna, azione primaria, permessi dei comandi."""
    from ..access import can_manage_project
    from .filo import stato_consegna

    gestisce = can_manage_project(request, project)
    chiuso = bool(project.chiuso_il)
    oggi = timezone.localdate()
    incontro = None
    if not chiuso:
        incontro = (
            project.meetings.filter(stato=MeetingStatus.PIANIFICATO, data__gte=oggi)
            .order_by("data", "ora", "numero", "id")
            .first()
        )

    primaria = None
    nuovo_incontro_url = (
        reverse("tasks:project_meeting_create", args=[project.pk]) if gestisce and puo_creare and not chiuso else ""
    )
    if chiuso:
        pass
    elif incontro is not None and incontro.data == oggi and gestisce:
        primaria = {
            "label": f"Conduci incontro n. {incontro.numero}",
            "url": reverse("tasks:project_meeting_run", args=[project.pk, incontro.pk]),
        }
    elif gestisce and project.vrf_status == VRFDocStatus.PENDING:
        primaria = {"label": "Compila la VRF", "url": _vrf_url(project)}
    elif incontro is not None:
        primaria = {
            "label": f"Incontro n. {incontro.numero} del {incontro.data:%d/%m}",
            "url": reverse("tasks:project_meeting_detail", args=[project.pk, incontro.pk]),
        }
    elif nuovo_incontro_url:
        primaria = {"label": "Nuovo incontro", "url": nuovo_incontro_url}
        nuovo_incontro_url = ""  # già in evidenza: non si ripete nel menu

    return {
        "consegna": stato_consegna(project),
        "chiuso": chiuso,
        "gestisce": gestisce,
        "primaria": primaria,
        "nuova_attivita_url": (
            f"{reverse('tasks:create')}?project={project.pk}" if gestisce and puo_creare and not chiuso else ""
        ),
        "nuovo_incontro_url": nuovo_incontro_url,
        "puo_copiare": gestisce and puo_creare,
        "vrf_url": _vrf_url(project),
    }
