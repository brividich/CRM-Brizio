"""Pulizia una tantum dei log operativi prima dell'entrata in produzione.

Svuota solo le tabelle di **log operativo** accumulate durante sviluppo e
collaudo: esecuzioni automazioni, coda eventi già processata, notifiche in-app,
log email anomalie, conversazioni AI, esiti task django-q, sessioni scadute.

NON tocca, per scelta, l'audit trail e le fonti di verità: ``AuditLog``,
``AclDenialEvent``, log admin Django, Axes, ``AnomaliaActionLog``,
``WorkOrderLog``, ``CandidatoLog``, ``TicketStatoLog``, ``SgiSyncLog``,
registri del Security Center (incidenti, notifiche, audit configurazione),
approvazioni e messaggi di casella usati per la deduplica, dati di dominio.

Dry-run di default: mostra solo i conteggi. ``--esegui`` cancella davvero, a
batch, e registra una riga ``AuditLog`` con i numeri. Fare il backup del DB prima.

    python django_app\\manage.py pulizia_pre_golive
    python django_app\\manage.py pulizia_pre_golive --esegui
    python django_app\\manage.py pulizia_pre_golive --solo notifiche,email_anomalie --esegui
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

BATCH_SIZE = 2000


@dataclass(frozen=True)
class Voce:
    codice: str
    etichetta: str
    queryset: Callable  # () -> QuerySet | None (None = tabella non disponibile)


def _qs_run_log():
    from automazioni.models import AutomationRunLog

    # Gli AutomationActionLog figli cadono via CASCADE.
    return AutomationRunLog.objects.all()


def _qs_notifiche():
    from core.models import Notifica

    return Notifica.objects.all()


def _qs_email_anomalie():
    from anomalie.mail_log_models import AnomalieEmailLog

    return AnomalieEmailLog.objects.all()


def _qs_pending_anomalie():
    from anomalie.mail_action_models import AnomaliaPendingNotification

    # Solo quelle già inviate: le pending vere sono mail ancora da spedire.
    return AnomaliaPendingNotification.objects.filter(notified=True)


def _qs_chat_assistente():
    from ai_assistant.models import AiConversation

    return AiConversation.objects.all()


def _qs_chat_security():
    from security.models import AIConversation

    return AIConversation.objects.all()


def _qs_ingestion_security():
    from security.models import SecurityMailboxIngestionRun

    # Le esecuzioni in corso restano: le chiude il poller.
    return SecurityMailboxIngestionRun.objects.exclude(finished_at=None)


def _qs_task_django_q():
    try:
        from django_q.models import Task
    except Exception:  # pragma: no cover - django_q assente
        return None
    return Task.objects.all()


def _qs_sessioni_scadute():
    from django.contrib.sessions.models import Session

    return Session.objects.filter(expire_date__lt=timezone.now())


VOCI: tuple[Voce, ...] = (
    Voce("run_log", "Automazioni: run log + action log", _qs_run_log),
    Voce("notifiche", "Notifiche in-app (campanella)", _qs_notifiche),
    Voce("email_anomalie", "Anomalie: log invii email", _qs_email_anomalie),
    Voce("pending_anomalie", "Anomalie: notifiche in attesa già inviate", _qs_pending_anomalie),
    Voce("chat_assistente", "Assistente AI: conversazioni", _qs_chat_assistente),
    Voce("chat_security", "Security Center: conversazioni AI", _qs_chat_security),
    Voce("ingestion_security", "Security Center: esecuzioni lettura casella", _qs_ingestion_security),
    Voce("task_django_q", "django-q: esiti task eseguiti", _qs_task_django_q),
    Voce("sessioni_scadute", "Sessioni web scadute", _qs_sessioni_scadute),
)

CODA = "coda_automazioni"
CODA_ETICHETTA = "Automazioni: coda eventi già processati (done/error)"
_CODA_WHERE = "WHERE status IN (%s, %s)"


def _coda_disponibile() -> bool:
    if connection.vendor != "microsoft":
        return False
    return "automation_event_queue" in connection.introspection.table_names()


def _coda_conta() -> int:
    from automazioni.services import QueueEventStatus

    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) FROM dbo.automation_event_queue {_CODA_WHERE};",
            [QueueEventStatus.DONE, QueueEventStatus.ERROR],
        )
        row = cursor.fetchone()
    return int(row[0] or 0) if row else 0


def _coda_cancella() -> int:
    from automazioni.services import QueueEventStatus

    totale = 0
    while True:
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE TOP ({BATCH_SIZE}) FROM dbo.automation_event_queue {_CODA_WHERE};",
                [QueueEventStatus.DONE, QueueEventStatus.ERROR],
            )
            cancellati = int(cursor.rowcount or 0)
        totale += max(cancellati, 0)
        if cancellati < BATCH_SIZE:
            return totale


def _cancella_a_batch(qs) -> int:
    totale = 0
    while True:
        ids = list(qs.order_by().values_list("pk", flat=True)[:BATCH_SIZE])
        if not ids:
            return totale
        qs.model.objects.filter(pk__in=ids).delete()
        totale += len(ids)


class Command(BaseCommand):
    help = "Svuota i log operativi di sviluppo/collaudo prima del go-live (audit trail escluso)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--esegui",
            action="store_true",
            help="Cancella davvero. Senza questo flag è un dry-run che mostra solo i conteggi.",
        )
        parser.add_argument(
            "--solo",
            default="",
            help="Codici separati da virgola per limitare la pulizia (vedi l'elenco nel dry-run).",
        )

    def handle(self, *args, **options):
        esegui = bool(options["esegui"])
        codici_validi = [v.codice for v in VOCI] + [CODA]
        solo = [c.strip() for c in (options["solo"] or "").split(",") if c.strip()]
        sconosciuti = sorted(set(solo) - set(codici_validi))
        if sconosciuti:
            raise CommandError(
                f"Codici sconosciuti: {', '.join(sconosciuti)}. Validi: {', '.join(codici_validi)}."
            )
        scelti = set(solo or codici_validi)

        modo = "ESECUZIONE" if esegui else "DRY-RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Pulizia pre go-live — {modo}"))

        risultati: dict[str, int] = {}
        for voce in VOCI:
            if voce.codice not in scelti:
                continue
            qs = voce.queryset()
            if qs is None:
                self.stdout.write(f"  {voce.codice:<20} {voce.etichetta}: non disponibile")
                continue
            if esegui:
                numero = _cancella_a_batch(qs)
            else:
                numero = qs.count()
            risultati[voce.codice] = numero
            self.stdout.write(f"  {voce.codice:<20} {voce.etichetta}: {numero}")

        if CODA in scelti:
            if _coda_disponibile():
                numero = _coda_cancella() if esegui else _coda_conta()
                risultati[CODA] = numero
                self.stdout.write(f"  {CODA:<20} {CODA_ETICHETTA}: {numero}")
            else:
                self.stdout.write(f"  {CODA:<20} {CODA_ETICHETTA}: non disponibile")

        totale = sum(risultati.values())
        if not esegui:
            self.stdout.write(f"Totale righe candidate: {totale}. Esegui con --esegui (dopo il backup).")
            return

        from core.models import AuditLog

        AuditLog.objects.create(
            azione="pulizia_pre_golive",
            modulo="core",
            utente_display="manage.py pulizia_pre_golive",
            dettaglio={"righe_cancellate": risultati, "totale": totale},
        )
        logger.info("pulizia_pre_golive: %s righe cancellate %s", totale, risultati)
        self.stdout.write(self.style.SUCCESS(f"Completato: {totale} righe cancellate."))
