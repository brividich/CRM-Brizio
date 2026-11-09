"""Segnali del modulo KICK-OFF."""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_delete, pre_save
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


@receiver(post_save, sender=Task, dispatch_uid="tasks_programma_da_attivita")
def programma_da_attivita(sender, instance: Task, raw=False, **kwargs):
    if raw:
        return
    from .services.programmi import allinea_da_attivita

    # Come per le voci d'incontro: un problema sulla riga non deve far perdere l'attività.
    try:
        allinea_da_attivita(instance)
    except Exception:
        logger.exception("Allineamento programma fallito (task=%s)", instance.pk)


@receiver(pre_delete, sender=Task, dispatch_uid="tasks_programma_attivita_eliminata")
def programma_attivita_eliminata(sender, instance: Task, **kwargs):
    from .models import ProjectTechRef
    from .services.programmi import sgancia

    ref = ProjectTechRef.objects.filter(task=instance).first()
    if ref is not None:
        sgancia(ref)


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



# --- Catalogo voci ricorrenti: ogni titolo scritto torna come suggerimento ---------

def _catalogo(tipo, testo, **kw):
    try:
        from .services.catalogo import registra_uso

        registra_uso(tipo, testo, **kw)
    except Exception:
        logger.exception("Catalogo non aggiornato (%s)", tipo)


@receiver(post_save, sender="tasks.MeetingActionItem", dispatch_uid="tasks_catalogo_azione")
def catalogo_azione(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        _catalogo("AZIONE", instance.title)


@receiver(post_save, sender="tasks.MeetingIssue", dispatch_uid="tasks_catalogo_problema")
def catalogo_problema(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        _catalogo("PROBLEMA", instance.title)


@receiver(post_save, sender=Task, dispatch_uid="tasks_catalogo_attivita")
def catalogo_attivita(sender, instance, created, raw=False, **kwargs):
    # Le attività delle tappe hanno titoli composti (macchina, fornitore): non sono voci da riproporre.
    if not created or raw or not instance.project_id:
        return
    if instance.category_id and getattr(instance.category, "tappa", ""):
        return
    _catalogo("ATTIVITA", instance.title)
