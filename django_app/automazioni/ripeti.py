"""«Ripeti» di un'esecuzione (run log) da Mail inviate e dal dettaglio del run log.

- Regola normale: riesegue solo quella regola con il payload salvato nel run log
  (non tutto l'evento della coda, che rimanderebbe anche le mail delle altre regole).
- Flusso pianificato: lo avvia ora (come «Esegui ora» di Pianificati).
- Flusso su evento di un modulo: non si ripete da qui, perché i dati dell'operazione
  restano in memoria e non si salvano nel run log; si rifà l'operazione nel modulo.

L'esecuzione va nel cluster django-q; se l'accodamento non riesce gira subito.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def come_ripetere(run_log) -> dict:
    """``{"modo": "regola"|"pianificato"|None, "codice": str, "motivo": str}``."""
    from .models import ManagedFlow

    rule = getattr(run_log, "rule", None)
    if rule is None:
        return {"modo": None, "codice": "", "motivo": "La regola di questa esecuzione non esiste più."}
    binding = ManagedFlow.objects.filter(rule_id=rule.pk).first()
    if binding is not None:
        if binding.kind == "schedule":
            return {"modo": "pianificato", "codice": binding.code, "motivo": ""}
        return {"modo": None, "codice": binding.code,
                "motivo": "Parte da un'operazione del modulo: per rimandarla rifai l'operazione nel modulo."}
    if not rule.is_active or rule.is_draft:
        return {"modo": None, "codice": "", "motivo": "La regola è spenta o in bozza: riattivala prima di ripetere."}
    return {"modo": "regola", "codice": "", "motivo": ""}


def ripeti_regola(run_log_id: int, user_id: int | None = None) -> int | None:
    """Riesegue la regola del run log con lo stesso payload. Restituisce il nuovo run log."""
    from django.contrib.auth import get_user_model

    from .models import AutomationRunLog
    from .services import run_rule

    origine = AutomationRunLog.objects.select_related("rule").get(pk=run_log_id)
    utente = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    nuovo = run_rule(
        origine.rule,
        origine.payload_json,
        old_payload=origine.old_payload_json,
        queue_event_id=origine.queue_event_id,
        initiated_by=utente,
        payload_enriched=True,
    )
    logger.info("ripeti_regola: run log %s ripetuto come %s (%s)", run_log_id, nuovo.pk, nuovo.status)
    return nuovo.pk


def ripeti(run_log, user) -> tuple[bool, str]:
    """Avvia la ripetizione; restituisce (riuscito, messaggio per l'utente)."""
    piano = come_ripetere(run_log)
    if piano["modo"] is None:
        return False, piano["motivo"]
    user_id = getattr(user, "pk", None)
    try:
        from django_q.tasks import async_task

        if piano["modo"] == "pianificato":
            async_task("automazioni.managed_flows.run_managed_flow", piano["codice"], ignora_sospensione=True)
        else:
            async_task("automazioni.ripeti.ripeti_regola", run_log.pk, user_id,
                       task_name=f"automazioni_ripeti_run_log_{run_log.pk}")
    except Exception:
        logger.warning("Ripeti run log %s: accodamento non riuscito, eseguo subito", run_log.pk, exc_info=True)
        if piano["modo"] == "pianificato":
            from .managed_flows import run_managed_flow

            esito = run_managed_flow(piano["codice"], ignora_sospensione=True)
            return True, f"Flusso eseguito ora (esito: {esito.get('status', 'saltato')})."
        nuovo = ripeti_regola(run_log.pk, user_id)
        return True, f"Regola rieseguita: nuovo run log #{nuovo}."
    if piano["modo"] == "pianificato":
        return True, "Flusso avviato ora: l'esito compare tra qualche secondo in Mail inviate e nei run log."
    return True, "Regola rimandata con gli stessi dati: l'esito compare tra qualche secondo in Mail inviate e nei run log."
