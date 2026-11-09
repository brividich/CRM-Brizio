"""Filo della commessa: kickoff → incontro → attività. Dice qual è il prossimo passo.

Calcolato al volo dai dati che ci sono già (incontri, minuta, Percorso), nessun
campo nuovo. Serve alla Panoramica: in alto i passi da fare, nell'ordine in cui
una commessa li incontra.
"""
from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from ..models import MeetingStatus


def _passo(titolo: str, dettaglio: str, url: str, azione: str, tono: str = "info") -> dict:
    return {"titolo": titolo, "dettaglio": dettaglio, "url": url, "azione": azione, "tono": tono}


def prossimi_passi(project, *, tappe: dict | None = None, can_manage: bool = True, limite: int = 3) -> list[dict]:
    oggi = timezone.localdate()
    pid = project.pk
    incontri = list(project.meetings.exclude(stato=MeetingStatus.ANNULLATO).order_by("data", "numero"))
    passi: list[dict] = []

    if not incontri:
        passi.append(_passo(
            "Pianifica il primo incontro", "Il kickoff parte dall'incontro di avvio: data, sala e partecipanti.",
            reverse("tasks:project_meeting_create", args=[pid]), "Pianifica", "warn",
        ))
    for m in incontri:
        dettaglio_url = reverse("tasks:project_meeting_detail", args=[pid, m.pk])
        nome = f"incontro {m.numero}"
        if m.stato == MeetingStatus.PIANIFICATO:
            if m.data < oggi:
                passi.append(_passo(
                    f"Registra l'esito dell'{nome}", f"Era previsto il {m.data:%d/%m}: verbale, decisioni, azioni.",
                    reverse("tasks:project_meeting_minutes", args=[pid, m.pk]), "Registra esito", "danger",
                ))
            elif m.data == oggi:
                passi.append(_passo(
                    f"Conduci l'{nome}", "È oggi: un punto alla volta, assegna le tappe e le attività mentre ne parlate.",
                    reverse("tasks:project_meeting_run", args=[pid, m.pk]), "Conduci", "warn",
                ))
            elif not m.convocazione_inviata and not m.outlook_event_id:
                passi.append(_passo(
                    f"Convoca l'{nome}", f"Fissato il {m.data:%d/%m}: invito Outlook con la sala, o convocazione via mail.",
                    dettaglio_url, "Apri", "info",
                ))
            elif m.convocazione_da_reinviare:
                passi.append(_passo(
                    f"Reinvia la convocazione dell'{nome}", "Data, luogo, convocati o ordine del giorno sono cambiati.",
                    dettaglio_url, "Apri", "warn",
                ))
        elif m.stato == MeetingStatus.SVOLTO:
            if not m.minuta_chiusa:
                passi.append(_passo(
                    f"Approva la minuta dell'{nome}", "Controlla verbale e azioni, poi approvala e inviala.",
                    dettaglio_url, "Apri", "info",
                ))
            elif m.minuta_da_reinviare:
                passi.append(_passo(
                    f"Invia l'aggiornamento della minuta dell'{nome}", "È cambiata dopo l'invio.",
                    dettaglio_url, "Apri", "warn",
                ))
            elif not m.minuta_inviata:
                passi.append(_passo(
                    f"Invia la minuta dell'{nome}", "Approvata ma non ancora mandata ai partecipanti.",
                    dettaglio_url, "Apri", "info",
                ))

    if tappe:
        vuote = [r["label"] for r in tappe.get("righe", []) if r["stato"] == "vuota"]
        ritardo = [r["label"] for r in tappe.get("righe", []) if r["stato"] == "ritardo"]
        if ritardo:
            passi.append(_passo(
                "Tappe in ritardo", ", ".join(ritardo) + ": parlane al prossimo incontro o sposta le date.",
                "#percorso", "Vedi", "danger",
            ))
        if vuote:
            passi.append(_passo(
                f"Assegna {len(vuote)} tapp{'a' if len(vuote) == 1 else 'e'} del percorso", ", ".join(vuote) + ".",
                "#percorso", "Assegna", "warn",
            ))

    # Consegna al cliente: attività aperte che finiscono dopo la consegna la mettono a rischio.
    if project.data_consegna and not project.chiuso_il:
        from ..models import TaskStatus

        dopo = list(
            project.tasks.exclude(status__in=[TaskStatus.DONE, TaskStatus.CANCELED])
            .filter(due_date__gt=project.data_consegna).values_list("title", flat=True)[:3]
        )
        if dopo:
            passi.append(_passo(
                f"Consegna del {project.data_consegna:%d/%m} a rischio",
                "Finiscono dopo la consegna: " + ", ".join(dopo) + ".",
                reverse("tasks:project_gantt", args=[pid]), "Gantt", "danger",
            ))
    # Tutto a posto: si chiude il kickoff.
    if not project.chiuso_il and tappe and tappe.get("totale") and tappe.get("a_posto") == tappe.get("totale"):
        from ..models import TaskStatus

        if not project.tasks.exclude(status__in=[TaskStatus.DONE, TaskStatus.CANCELED]).exists():
            passi.append(_passo(
                "Chiudi il kickoff", "Tutte le tappe sono a posto e non ci sono attività aperte.", "#chiusura", "Chiudi", "info",
            ))
    futuri = [m for m in incontri if m.stato == MeetingStatus.PIANIFICATO and m.data >= oggi]
    svolti = [m for m in incontri if m.stato == MeetingStatus.SVOLTO]
    if incontri and not futuri and svolti:
        ultimo = svolti[-1]
        passi.append(_passo(
            "Pianifica il prossimo incontro", f"L'ultimo è stato il {ultimo.data:%d/%m}: si riparte da convocati, sala e punti rimasti.",
            reverse("tasks:project_meeting_create", args=[pid]) + f"?da={ultimo.pk}", "Pianifica", "info",
        ))

    if project.chiuso_il:
        return []
    if not can_manage:
        passi = [p for p in passi if p["url"].startswith("#") and p["url"] != "#chiusura"]
    ordine = {"danger": 0, "warn": 1, "info": 2}
    passi.sort(key=lambda p: ordine.get(p["tono"], 3))
    return passi[:limite]



def stato_consegna(project) -> dict | None:
    """Giorni alla consegna e se è a rischio (attività aperte che finiscono dopo)."""
    if not project.data_consegna:
        return None
    from ..models import TaskStatus

    oggi = timezone.localdate()
    a_rischio = project.tasks.exclude(status__in=[TaskStatus.DONE, TaskStatus.CANCELED]).filter(
        due_date__gt=project.data_consegna
    ).exists()
    return {"data": project.data_consegna, "giorni": (project.data_consegna - oggi).days, "a_rischio": a_rischio}



def cruscotto(request, progetti) -> list[dict]:
    """Una riga per commessa: percorso, consegna, spostamenti da decidere, prossimo incontro, passo più urgente."""
    from ..models import SpostamentoStato, TaskSpostamento
    from .tappe import percorso

    oggi = timezone.localdate()
    spostamenti = {}
    for pid in TaskSpostamento.objects.filter(
        stato=SpostamentoStato.IN_ATTESA, task__project__in=progetti
    ).values_list("task__project_id", flat=True):
        spostamenti[pid] = spostamenti.get(pid, 0) + 1
    righe = []
    for p in progetti:
        tappe = percorso(p)
        prossimo = (
            p.meetings.filter(stato=MeetingStatus.PIANIFICATO, data__gte=oggi).order_by("data", "ora").first()
        )
        passi = prossimi_passi(p, tappe=tappe, limite=1)
        righe.append({
            "project": p,
            "tappe": tappe,
            "consegna": stato_consegna(p),
            "spostamenti": spostamenti.get(p.pk, 0),
            "prossimo": prossimo,
            "passo": passi[0] if passi else None,
            "ritardo": sum(1 for r in tappe["righe"] if r["stato"] == "ritardo"),
        })
    # Prima chi ha problemi: ritardi, consegna a rischio, decisioni da prendere.
    righe.sort(key=lambda r: (
        -(r["ritardo"] + (2 if r["consegna"] and r["consegna"]["a_rischio"] else 0) + r["spostamenti"]),
        r["consegna"]["data"] if r["consegna"] else timezone.localdate().replace(year=9999),
    ))
    return righe



def durate_reali(modello) -> dict[str, dict]:
    """Per ogni tappa: quanti giorni prima della consegna è stata davvero chiusa (media sulle commesse del modello)."""
    from ..models import Task, TaskEvent, TaskEventType, TaskStatus

    valori: dict[str, list[int]] = {}
    tasks = (
        Task.objects.filter(project__modello=modello, project__data_consegna__isnull=False, status=TaskStatus.DONE)
        .exclude(category__tappa="").select_related("project", "category")
    )
    for t in tasks:
        # Niente ricerca dentro il JSON nel database (su SQL Server non è affidabile): si guarda in Python.
        evento = next(
            (e for e in TaskEvent.objects.filter(task=t, type=TaskEventType.STATUS_CHANGE).order_by("-created_at")
             if (e.payload or {}).get("to") == TaskStatus.DONE),
            None,
        )
        fatta = timezone.localtime(evento.created_at).date() if evento else timezone.localtime(t.updated_at).date()
        valori.setdefault(t.category.tappa, []).append((t.project.data_consegna - fatta).days)
    return {k: {"media": round(sum(v) / len(v)), "n": len(v)} for k, v in valori.items() if v}
