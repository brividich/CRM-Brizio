"""Segnali del modulo KICK-OFF."""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import MeetingActionItem, MeetingIssue, Task, TaskStatus

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Task, dispatch_uid="tasks_stato_prima_del_salvataggio")
def ricorda_stato_precedente(sender, instance: Task, **kwargs):
    """Annota lo stato in DB prima del salvataggio (solo per chi si sta completando)."""
    instance._stato_precedente = None
    if instance.pk and instance.status == TaskStatus.DONE:
        instance._stato_precedente = (
            Task.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        )


@receiver(post_save, sender=Task, dispatch_uid="tasks_chiudi_voci_incontro")
def chiudi_voci_incontro_su_completamento(sender, instance: Task, created: bool, update_fields=None, **kwargs):
    """Un'attivita' completata chiude azioni e problemi d'incontro collegati.

    Un segnale, e non una chiamata nelle view, perche' un'attivita' si completa
    da molte strade (stato, sotto-attivita', Gantt, attrezzature, import).
    Solo nel passaggio a «Completata»: un salvataggio qualsiasi di un'attivita'
    gia' completata non richiude le voci che qualcuno ha riaperto a mano.
    """
    if created or instance.status != TaskStatus.DONE:
        return
    if update_fields is not None and "status" not in update_fields:
        return
    if getattr(instance, "_stato_precedente", None) == TaskStatus.DONE:
        return
    from .services.meeting_tasks import chiudi_voci_collegate

    try:
        chiudi_voci_collegate(instance)
    except Exception:
        logger.exception("Chiusura voci incontro collegate fallita (task=%s)", instance.pk)


@receiver(post_save, sender=MeetingActionItem, dispatch_uid="tasks_azione_su_attivita_completata")
@receiver(post_save, sender=MeetingIssue, dispatch_uid="tasks_problema_su_attivita_completata")
def voce_nuova_su_attivita_completata(sender, instance, created: bool, **kwargs):
    """Azione o problema creati gia' collegati a un'attivita' completata: nascono chiusi."""
    if not created or not instance.linked_task_id:
        return
    from .services.meeting_tasks import chiudi_voce_se_attivita_completata

    try:
        chiudi_voce_se_attivita_completata(instance)
    except Exception:
        logger.exception("Chiusura voce su attivita' completata fallita (%s=%s)", sender.__name__, instance.pk)
