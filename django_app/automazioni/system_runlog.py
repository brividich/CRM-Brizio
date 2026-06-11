"""Tracciamento dei JOB DI SISTEMA (task periodici django-q2) nel Run-log automazioni.

I task schedulati (es. anomalie_pending_notifications, anomalie_escalation,
report_scadenze_settimanale) non passano dal motore regole, quindi finora non
comparivano nel Run-log / Monitor automazioni. Questo helper crea un
``AutomationRunLog`` "di sistema" attorno all'esecuzione del task:

    from automazioni.system_runlog import system_job_run

    @system_job_run("anomalie_pending_notifications")
    def run_anomalie_pending_notifications(threshold_minutes=5):
        ...
        return {"sent": 3, "checked": 10}   # finisce in result_message

Oppure come context manager, con esito esplicito:

    with system_job_run("anomalie_escalation") as ctx:
        ...
        ctx.set_result({"reminders": 2})
        ctx.set_skipped("fuori finestra")   # opzionale: marca SKIPPED

Il RunLog usa ``rule=None`` (FK nullable) e ``source_code="system:<job>"``: la
lista Run-log mostra "-" come regola e il source_code come identificativo, senza
bisogno di migration o modifiche al template. Il tracciamento e' best-effort: se
la creazione/aggiornamento del RunLog fallisce, NON deve far fallire il job.
"""
from __future__ import annotations

import functools
import json
import logging
import traceback
from typing import Any

from django.utils import timezone

logger = logging.getLogger("automazioni.system_runlog")

# Prefisso convenzionale del source_code per i job di sistema. La lista Run-log
# filtra/visualizza per source_code, quindi questo li raggruppa in modo naturale.
SYSTEM_SOURCE_PREFIX = "system"


def _source_code(job_name: str) -> str:
    return f"{SYSTEM_SOURCE_PREFIX}:{job_name}"


def _stringify_result(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


class SystemJobRun:
    """Context manager: apre un AutomationRunLog all'ingresso, lo chiude all'uscita.

    Stato finale:
    - SUCCESS se il blocco termina senza eccezioni (default);
    - SKIPPED se ``set_skipped(...)`` e' stato chiamato;
    - ERROR se viene sollevata un'eccezione (ri-propagata).
    """

    def __init__(self, job_name: str, *, trigger_label: str | None = None, skip_noop: bool = True):
        self.job_name = job_name
        self.trigger_label = trigger_label or f"Job periodico: {job_name}"
        self.skip_noop = skip_noop
        self._started_at = None
        self._started_monotonic = None
        self._result_message = ""
        self._result_value: Any = None
        self._skipped_reason: str | None = None
        self._force_log = False

    # -- API per il corpo del job ------------------------------------------
    def set_result(self, value: Any) -> None:
        """Imposta l'esito (dict/stringa) mostrato nel Run-log.

        Se ``skip_noop`` e' attivo, il valore viene anche usato per decidere se il
        run e' un no-op (nessuna attivita') e quindi NON va salvato.
        """
        self._result_value = value
        self._result_message = _stringify_result(value)

    def set_skipped(self, reason: str = "") -> None:
        """Marca il run come SKIPPED (es. job che non aveva nulla da fare)."""
        self._skipped_reason = reason or "skipped"

    def force_log(self) -> None:
        """Forza la scrittura del RunLog anche se il risultato sembra un no-op."""
        self._force_log = True

    # -- Lifecycle ----------------------------------------------------------
    def __enter__(self) -> "SystemJobRun":
        import time

        # Il RunLog NON viene creato qui: per i job ad alta frequenza (es. ogni
        # minuto) si materializza solo all'uscita, e solo se non e' un no-op.
        # Cosi' si evita un INSERT+UPDATE per ogni tick a vuoto.
        self._started_at = timezone.now()
        self._started_monotonic = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None and self._skipped_reason is None:
            # Esito positivo: salta i no-op se richiesto.
            if self.skip_noop and not self._force_log and _is_noop_result(self._result_value):
                return False

        try:
            self._write_run_log(exc_type, exc, tb)
        except Exception:
            # Best-effort: il tracciamento non deve mai rompere il job.
            logger.warning("system_runlog: scrittura RunLog fallita job=%s", self.job_name, exc_info=True)

        return False  # non sopprimere mai le eccezioni del job

    def _write_run_log(self, exc_type, exc, tb) -> None:
        import time

        from automazioni.models import (
            AutomationRunLog,
            AutomationRuleOperationType,
            AutomationRunLogStatus,
        )

        elapsed_ms = None
        if self._started_monotonic is not None:
            elapsed_ms = int((time.monotonic() - self._started_monotonic) * 1000)

        if exc_type is not None:
            status = AutomationRunLogStatus.ERROR
            message = (self._result_message or "") + (f"\n{exc_type.__name__}: {exc}" if exc else "")
            error_trace = "".join(traceback.format_exception(exc_type, exc, tb))[:8000]
        elif self._skipped_reason is not None:
            status = AutomationRunLogStatus.SKIPPED
            message = self._skipped_reason
            error_trace = None
        else:
            status = AutomationRunLogStatus.SUCCESS
            message = self._result_message
            error_trace = None

        AutomationRunLog.objects.create(
            rule=None,
            source_code=_source_code(self.job_name),
            operation_type=AutomationRuleOperationType.UPDATE,
            trigger_event_label=self.trigger_label,
            status=status,
            result_message=message,
            error_trace=error_trace,
            started_at=self._started_at or timezone.now(),
            finished_at=timezone.now(),
            execution_ms=elapsed_ms,
            is_test=False,
        )


# Chiavi che, se tutte a 0/falsy nel dict di risultato, indicano "nessuna attivita'".
_NOOP_COUNTER_KEYS = (
    "sent", "processed", "reminders", "email_sent", "op_over", "read",
    "approved", "rejected", "error", "errors", "created", "updated", "deleted",
)


def _is_noop_result(value: Any) -> bool:
    """True se il risultato del job indica che non e' stato fatto nulla.

    - dict: no-op se NESSUNA delle chiavi-contatore note ha un valore truthy.
      (chiavi come 'checked'/'op_da_controllare' sono ignorate: contano quanti
      record sono stati ESAMINATI, non quanti hanno prodotto un'azione.)
    - dict con flag esplicito ``{"skipped": True}``: no-op.
    - None: no-op (job senza esito).
    Qualsiasi altro tipo (stringa, ecc.) NON e' considerato no-op: nel dubbio si logga.
    """
    if value is None:
        return True
    if isinstance(value, dict):
        if value.get("skipped"):
            return True
        relevant = [k for k in _NOOP_COUNTER_KEYS if k in value]
        if not relevant:
            # Nessuna chiave-contatore nota: non sappiamo, meglio loggare.
            return False
        return not any(value.get(k) for k in relevant)
    return False


def system_job_run(job_name: str, *, trigger_label: str | None = None, skip_noop: bool = True):
    """Decorator: traccia la funzione-task come job di sistema nel Run-log.

    Se la funzione ritorna un dict/valore, finisce in ``result_message``. Le
    eccezioni vengono ri-propagate (e registrate come ERROR nel RunLog).

    Con ``skip_noop=True`` (default) i run senza attivita' (es. il poller che
    non aveva nulla da inviare) NON creano un RunLog, per non intasare la
    tabella sui job ad alta frequenza. Errori e SKIPPED espliciti vengono
    sempre registrati.
    """
    def _decorator(func):
        @functools.wraps(func)
        def _wrapper(*args, **kwargs):
            with SystemJobRun(job_name, trigger_label=trigger_label, skip_noop=skip_noop) as ctx:
                result = func(*args, **kwargs)
                if result is not None:
                    ctx.set_result(result)
                return result
        return _wrapper
    return _decorator
