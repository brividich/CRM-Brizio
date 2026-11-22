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


def _primaria_incontro(project, incontro, pagina: str, *, gestisce: bool, puo_creare: bool, oggi) -> dict | None:
    """Dentro un incontro il pulsante segue la fase: inizia, termina, approva, invia, pianifica il prossimo."""
    if not gestisce or incontro.stato == MeetingStatus.ANNULLATO:
        return None
    ids = [project.pk, incontro.pk]
    esito = reverse("tasks:project_meeting_minutes", args=ids)
    if pagina == "conduzione":
        return {"label": "Termina l'incontro", "url": esito}
    if incontro.stato == MeetingStatus.PIANIFICATO:
        if incontro.data and incontro.data < oggi:
            return {"label": "Registra l'esito", "url": esito}
        return {"label": "Inizia l'incontro", "url": reverse("tasks:project_meeting_run", args=ids)}
    if not incontro.minuta_chiusa:
        return {
            "label": "Approva la minuta", "url": reverse("tasks:project_meeting_minute_close", args=ids), "post": True,
            "conferma": "Approvare e chiudere la minuta? L'esito non sarà più modificabile senza riaprirla.",
        }
    if not incontro.minuta_inviata:
        return {
            "label": "Invia la minuta", "url": reverse("tasks:project_meeting_send_minute", args=ids), "post": True,
            "conferma": "Inviare la minuta dell'incontro a tutti i partecipanti?",
        }
    if puo_creare and not project.chiuso_il:
        return {
            "label": "Pianifica il prossimo incontro",
            "url": reverse("tasks:project_meeting_create", args=[project.pk]) + f"?da={incontro.pk}",
        }
    return None


def testata_commessa(request, project, *, puo_creare: bool, incontro=None, pagina: str = "") -> dict:
    """Dati della testata: consegna, azione primaria, permessi dei comandi.

    ``incontro`` e ``pagina`` (``convocazione``, ``conduzione``, ``esito``, ``nuovo``):
    dentro un incontro l'azione primaria è quella della sua fase; nelle pagine che
    hanno già il loro «Salva» (esito, incontro nuovo) non ce n'è una seconda.
    """
    from ..access import can_manage_project
    from .filo import stato_consegna

    gestisce = can_manage_project(request, project)
    chiuso = bool(project.chiuso_il)
    oggi = timezone.localdate()
    dentro_incontro = incontro is not None or pagina in ("esito", "nuovo")
    prossimo = None
    if not chiuso and not dentro_incontro:
        prossimo = (
            project.meetings.filter(stato=MeetingStatus.PIANIFICATO, data__gte=oggi)
            .order_by("data", "ora", "numero", "id")
            .first()
        )

    primaria = None
    nuovo_incontro_url = (
        reverse("tasks:project_meeting_create", args=[project.pk]) if gestisce and puo_creare and not chiuso else ""
    )
    if pagina in ("esito", "nuovo"):
        pass
    elif incontro is not None:
        primaria = _primaria_incontro(project, incontro, pagina, gestisce=gestisce, puo_creare=puo_creare, oggi=oggi)
    elif chiuso:
        pass
    elif prossimo is not None and prossimo.data == oggi and gestisce:
        primaria = {
            "label": f"Conduci incontro n. {prossimo.numero}",
            "url": reverse("tasks:project_meeting_run", args=[project.pk, prossimo.pk]),
        }
    elif gestisce and project.vrf_status == VRFDocStatus.PENDING:
        primaria = {"label": "Compila la VRF", "url": _vrf_url(project)}
    elif prossimo is not None:
        primaria = {
            "label": f"Incontro n. {prossimo.numero} del {prossimo.data:%d/%m}",
            "url": reverse("tasks:project_meeting_detail", args=[project.pk, prossimo.pk]),
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
