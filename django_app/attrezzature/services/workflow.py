from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from attrezzature.models import (
    Attrezzatura,
    AttrezzaturaAvanzamento,
    AttrezzaturaNota,
    AttrezzaturaStato,
    AttrezzaturaTask,
    AttrezzaturaTaskOrigine,
    AttrezzaturaTaskPriorita,
    AttrezzaturaTaskStato,
    AttrezzaturaTaskTipo,
    DisponibilitaStato,
)


def _clean(value) -> str:
    return str(value or "").strip()


def update_attrezzatura_progress(attrezzatura, percentuale=None, stato=None, user=None, note="", origine=""):
    old_stato = attrezzatura.stato
    old_percentuale = attrezzatura.avanzamento_percentuale
    changed_fields = []

    if percentuale is not None and percentuale != attrezzatura.avanzamento_percentuale:
        attrezzatura.avanzamento_percentuale = percentuale
        changed_fields.append("avanzamento_percentuale")
    if stato and stato != attrezzatura.stato:
        attrezzatura.stato = stato
        changed_fields.append("stato")
    if user is not None:
        attrezzatura.updated_by = user
        changed_fields.append("updated_by")

    if changed_fields:
        attrezzatura.save(update_fields=[*changed_fields, "updated_at"])
        AttrezzaturaAvanzamento.objects.create(
            attrezzatura=attrezzatura,
            stato_precedente=old_stato or "",
            stato_nuovo=attrezzatura.stato or "",
            avanzamento_precedente=old_percentuale,
            avanzamento_nuovo=attrezzatura.avanzamento_percentuale,
            nota=note or "",
            origine=origine or "",
            created_by=user,
        )
    elif note:
        AttrezzaturaNota.objects.create(attrezzatura=attrezzatura, testo=note, origine=origine or "workflow", created_by=user)
    return attrezzatura


def set_availability_status(attrezzatura, disponibilita_stato, user=None, note=""):
    old_stato = attrezzatura.stato
    old_percentuale = attrezzatura.avanzamento_percentuale
    attrezzatura.disponibilita_stato = disponibilita_stato
    if disponibilita_stato == DisponibilitaStato.DISPONIBILE:
        attrezzatura.stato = AttrezzaturaStato.AVAILABLE
    elif disponibilita_stato == DisponibilitaStato.DA_CREARE:
        attrezzatura.stato = AttrezzaturaStato.TO_CREATE
    elif disponibilita_stato == DisponibilitaStato.DA_VERIFICARE:
        attrezzatura.stato = AttrezzaturaStato.CHECKING_AVAILABLE
    if user is not None:
        attrezzatura.updated_by = user
    fields = ["disponibilita_stato", "stato", "updated_at"]
    if user is not None:
        fields.append("updated_by")
    attrezzatura.save(update_fields=fields)
    if old_stato != attrezzatura.stato:
        AttrezzaturaAvanzamento.objects.create(
            attrezzatura=attrezzatura,
            stato_precedente=old_stato or "",
            stato_nuovo=attrezzatura.stato or "",
            avanzamento_precedente=old_percentuale,
            avanzamento_nuovo=attrezzatura.avanzamento_percentuale,
            nota=note or "Disponibilita aggiornata",
            origine="disponibilita",
            created_by=user,
        )
    if note:
        AttrezzaturaNota.objects.create(attrezzatura=attrezzatura, testo=note, origine="disponibilita", created_by=user)
    return attrezzatura


def mark_availability_check_started(attrezzatura, user=None, note=""):
    return update_attrezzatura_progress(
        attrezzatura,
        stato=AttrezzaturaStato.CHECKING_AVAILABLE,
        user=user,
        note=note or "Verifica disponibilita avviata",
        origine="verifica_disponibilita",
    )


def mark_available(attrezzatura, user=None, note=""):
    return set_availability_status(attrezzatura, DisponibilitaStato.DISPONIBILE, user=user, note=note)


def mark_to_create(attrezzatura, user=None, note=""):
    return set_availability_status(attrezzatura, DisponibilitaStato.DA_CREARE, user=user, note=note or "Attrezzatura da creare")


def mark_blocked(attrezzatura, user=None, reason=""):
    attrezzatura.blocked_reason = reason or ""
    attrezzatura.save(update_fields=["blocked_reason", "updated_at"])
    return update_attrezzatura_progress(
        attrezzatura,
        stato=AttrezzaturaStato.BLOCKED,
        user=user,
        note=reason or "Attrezzatura bloccata",
        origine="blocco",
    )


def close_attrezzatura(attrezzatura, user=None, note=""):
    return update_attrezzatura_progress(
        attrezzatura,
        percentuale=attrezzatura.avanzamento_percentuale,
        stato=AttrezzaturaStato.CLOSED,
        user=user,
        note=note or "Attrezzatura chiusa",
        origine="chiusura",
    )


def archive_attrezzatura(attrezzatura, user=None, note=""):
    return update_attrezzatura_progress(
        attrezzatura,
        percentuale=attrezzatura.avanzamento_percentuale,
        stato=AttrezzaturaStato.ARCHIVED,
        user=user,
        note=note or "Attrezzatura archiviata",
        origine="archiviazione",
    )


@transaction.atomic
def confirm_ready_for_production(attrezzatura, user=None, note=""):
    old_stato = attrezzatura.stato
    old_percentuale = attrezzatura.avanzamento_percentuale
    attrezzatura.stato = AttrezzaturaStato.READY_FOR_PRODUCTION
    attrezzatura.disponibilita_stato = DisponibilitaStato.DISPONIBILE
    attrezzatura.pronta_produzione_at = timezone.now()
    attrezzatura.pronta_produzione_by = user
    if user is not None:
        attrezzatura.updated_by = user
    attrezzatura.save(
        update_fields=[
            "stato",
            "disponibilita_stato",
            "pronta_produzione_at",
            "pronta_produzione_by",
            "updated_by",
            "updated_at",
        ]
    )
    AttrezzaturaAvanzamento.objects.create(
        attrezzatura=attrezzatura,
        stato_precedente=old_stato or "",
        stato_nuovo=attrezzatura.stato,
        avanzamento_precedente=old_percentuale,
        avanzamento_nuovo=attrezzatura.avanzamento_percentuale,
        nota=note or "Confermata pronta per produzione",
        origine="pronta_produzione",
        created_by=user,
    )
    AttrezzaturaTask.objects.filter(
        attrezzatura=attrezzatura,
        tipo=AttrezzaturaTaskTipo.CONFERMA_PRONTA_PRODUZIONE,
        stato__in=[AttrezzaturaTaskStato.APERTA, AttrezzaturaTaskStato.IN_LAVORAZIONE],
    ).update(stato=AttrezzaturaTaskStato.COMPLETATA, completed_at=timezone.now(), completed_by=user)
    return attrezzatura


def create_availability_check_task(part_number, attrezzatura=None, kickoff_ref=None, kickoff_activity_ref=None, user=None):
    pn = _clean(part_number or getattr(attrezzatura, "part_number", ""))
    return AttrezzaturaTask.objects.create(
        attrezzatura=attrezzatura,
        part_number=pn,
        codice_attrezzo=_clean(getattr(attrezzatura, "codice", "")),
        tipo=AttrezzaturaTaskTipo.VERIFICA_DISPONIBILITA,
        titolo=f"Verificare disponibilita attrezzatura per P/N {pn or '-'}",
        stato=AttrezzaturaTaskStato.APERTA,
        priorita=AttrezzaturaTaskPriorita.NORMALE,
        origine=AttrezzaturaTaskOrigine.KICKOFF if kickoff_ref or kickoff_activity_ref else AttrezzaturaTaskOrigine.MANUALE,
        external_kickoff_id=_clean(kickoff_ref),
        external_kickoff_activity_id=_clean(kickoff_activity_ref),
        created_by=user,
    )


def create_new_tool_task(part_number, description="", codice_attrezzo="", kickoff_ref=None, kickoff_activity_ref=None, user=None):
    pn = _clean(part_number)
    return AttrezzaturaTask.objects.create(
        part_number=pn,
        codice_attrezzo=_clean(codice_attrezzo),
        tipo=AttrezzaturaTaskTipo.CREAZIONE_ATTREZZO,
        titolo=f"Creare nuovo attrezzo per P/N {pn or '-'}",
        descrizione=description or "",
        stato=AttrezzaturaTaskStato.APERTA,
        priorita=AttrezzaturaTaskPriorita.NORMALE,
        origine=AttrezzaturaTaskOrigine.KICKOFF if kickoff_ref or kickoff_activity_ref else AttrezzaturaTaskOrigine.MANUALE,
        external_kickoff_id=_clean(kickoff_ref),
        external_kickoff_activity_id=_clean(kickoff_activity_ref),
        created_by=user,
    )


def create_delay_check_task(attrezzatura, user=None):
    existing = AttrezzaturaTask.objects.filter(
        attrezzatura=attrezzatura,
        tipo=AttrezzaturaTaskTipo.CONTROLLO_RITARDO,
        stato__in=[AttrezzaturaTaskStato.APERTA, AttrezzaturaTaskStato.IN_LAVORAZIONE, AttrezzaturaTaskStato.BLOCCATA],
    ).first()
    if existing is not None:
        return existing
    return AttrezzaturaTask.objects.create(
        attrezzatura=attrezzatura,
        part_number=attrezzatura.part_number,
        codice_attrezzo=attrezzatura.codice,
        tipo=AttrezzaturaTaskTipo.CONTROLLO_RITARDO,
        titolo=f"Controllare ritardo attrezzatura {attrezzatura.codice or attrezzatura.part_number or attrezzatura.pk}",
        stato=AttrezzaturaTaskStato.APERTA,
        priorita=AttrezzaturaTaskPriorita.ALTA,
        scadenza=timezone.localdate(),
        origine=AttrezzaturaTaskOrigine.REGOLA_AUTOMATICA,
        created_by=user,
    )


def complete_task(task, user=None, note=""):
    task.stato = AttrezzaturaTaskStato.COMPLETATA
    task.completed_at = timezone.now()
    task.completed_by = user
    task.blocked_reason = ""
    task.save(update_fields=["stato", "completed_at", "completed_by", "blocked_reason", "updated_at"])
    if note and task.attrezzatura_id:
        AttrezzaturaNota.objects.create(attrezzatura=task.attrezzatura, task=task, testo=note, origine="task_complete", created_by=user)
    return task


def block_task(task, user=None, reason=""):
    task.stato = AttrezzaturaTaskStato.BLOCCATA
    task.blocked_reason = reason or ""
    task.save(update_fields=["stato", "blocked_reason", "updated_at"])
    if reason and task.attrezzatura_id:
        AttrezzaturaNota.objects.create(attrezzatura=task.attrezzatura, task=task, testo=reason, origine="task_block", created_by=user)
    return task


def reopen_task(task, user=None, note=""):
    task.stato = AttrezzaturaTaskStato.APERTA
    task.completed_at = None
    task.completed_by = None
    task.save(update_fields=["stato", "completed_at", "completed_by", "updated_at"])
    if note and task.attrezzatura_id:
        AttrezzaturaNota.objects.create(attrezzatura=task.attrezzatura, task=task, testo=note, origine="task_reopen", created_by=user)
    return task
