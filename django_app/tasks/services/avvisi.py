"""Avvisi sui cambiamenti degli incarichi e sulle richieste di spostamento.

Chi riceve un incarico deve sapere quando gli cambiano date, priorità, stato o
responsabile. Prima veniva avvisato solo all'assegnazione: uno spostamento nel
Gantt o un annullamento passavano in silenzio.

Destinatari configurabili (Impostazioni KICK-OFF → «Poteri e avvisi»):
INCARICATO, CC (capocommessa), PM, CREATORE. Chi fa la modifica non viene avvisato.
Campanella sempre; mail tramite il flusso «kickoff_avviso_cambiamenti».
"""
from __future__ import annotations

import logging

from django.urls import reverse

from automazioni.managed_flows import event_flow

from ..models import TaskImpostazioni, TaskPriority, TaskStatus
from .notify import notify_user

logger = logging.getLogger(__name__)

ETICHETTE = {"next_step_due": "Inizio", "due_date": "Fine", "priority": "Priorità", "status": "Stato", "title": "Titolo"}


def _nome(user) -> str:
    if user is None:
        return "nessuno"
    return (user.get_full_name() or user.get_username() or "").strip()


def _valore(campo: str, valore) -> str:
    if valore in (None, ""):
        return "—"
    if campo in ("next_step_due", "due_date"):
        return valore.strftime("%d/%m/%Y") if hasattr(valore, "strftime") else str(valore)
    if campo == "priority":
        return dict(TaskPriority.choices).get(valore, str(valore))
    if campo == "status":
        return dict(TaskStatus.choices).get(valore, str(valore))
    return str(valore)


def differenze(task, before: dict) -> list[tuple[str, str, str]]:
    righe = []
    for campo, etichetta in ETICHETTE.items():
        prima, dopo = before.get(campo), getattr(task, campo, None)
        if prima != dopo:
            righe.append((etichetta, _valore(campo, prima), _valore(campo, dopo)))
    return righe


def _ruoli_avviso() -> set[str]:
    raw = TaskImpostazioni.get_singleton().avvisi_destinatari or ""
    return {c.strip().upper() for c in raw.split(",") if c.strip()}


def destinatari(task, *, escludi_ids=()) -> list:
    ruoli = _ruoli_avviso()
    persone = {}
    if "INCARICATO" in ruoli and task.assigned_to_id:
        persone[task.assigned_to_id] = task.assigned_to
    if task.project_id:
        for codice in ("CC", "PM"):
            if codice in ruoli:
                for u in task.project.team_members(codice):
                    persone.setdefault(u.pk, u)
    if "CREATORE" in ruoli and task.created_by_id:
        persone.setdefault(task.created_by_id, task.created_by)
    return [u for pk, u in persone.items() if pk not in set(escludi_ids) and getattr(u, "is_active", True)]


def _testo(task, righe, actor) -> str:
    progetto = f" [{task.project.name}]" if task.project_id else ""
    cambi = "; ".join(f"{e}: {a} → {b}" for e, a, b in righe)
    return f"«{task.title}»{progetto} è cambiata: {cambi} (da {_nome(actor)})."


def notifica_cambiamenti(task, actor, before: dict) -> int:
    """Campanella (e mail, se il flusso è acceso) a chi è coinvolto. Ritorna quante persone."""
    righe = differenze(task, before)
    prima_resp = before.get("assigned_to_id")
    url = reverse("tasks:detail", kwargs={"task_id": task.pk})
    actor_id = getattr(actor, "pk", None)
    avvisati = 0
    # Chi perde l'incarico lo sa; chi lo prende riceve già l'assegnazione.
    if prima_resp and prima_resp != task.assigned_to_id and prima_resp != actor_id:
        from django.contrib.auth import get_user_model

        vecchio = get_user_model().objects.filter(pk=prima_resp).first()
        if vecchio is not None:
            testo = f"Non sei più responsabile di «{task.title}»: ora è di {_nome(task.assigned_to)} (da {_nome(actor)})."
            notify_user(vecchio, testo, url)
            mail_cambiamento(task, vecchio, testo)
            avvisati += 1
    if not righe:
        return avvisati
    escludi = [actor_id]
    if prima_resp != task.assigned_to_id:
        escludi.append(task.assigned_to_id)
    testo = _testo(task, righe, actor)
    for persona in destinatari(task, escludi_ids=escludi):
        try:
            notify_user(persona, testo, url)
            mail_cambiamento(task, persona, testo, righe=righe)
            avvisati += 1
        except Exception:
            logger.exception("Avviso cambiamento non inviato (task=%s, user=%s)", task.pk, persona.pk)
    return avvisati


@event_flow("kickoff_avviso_cambiamenti", skipped_result=False)
def mail_cambiamento(task, persona, testo: str, *, righe=None) -> bool:
    from django.conf import settings

    from core.email_utils import email_cta, email_facts_table, send_hub_mail

    from ..outlook_reminder import _notification_email_for_user

    email = _notification_email_for_user(persona)
    if not email or "@" not in email:
        return False
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    url = base + reverse("tasks:detail", kwargs={"task_id": task.pk}) if base else ""
    fatti = [("Attività", task.title)]
    if task.project_id:
        fatti.append(("Commessa", task.project.name))
    for etichetta, prima, dopo in righe or []:
        fatti.append((etichetta, f"{prima} → {dopo}"))
    html = f"<p>{testo}</p>" + email_facts_table(fatti)
    if url:
        html += '<div style="height:18px"></div>' + email_cta("Apri l'attività", url, "Lì trovi anche lo storico delle modifiche.")
    send_hub_mail(
        f"Cambiata: {task.title}"[:180], testo + (f"\n\n{url}" if url else ""), [email],
        title="Un tuo incarico è cambiato", email_type="VRF - KICK-OFF", body_html_fragment=html, fail_silently=True,
    )
    return True
