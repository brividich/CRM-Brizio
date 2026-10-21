"""Conservazione dei dati personali negli archivi tecnici (GDPR art. 5.1.e).

Un registro di regole, una per archivio: log di monitoring, feedback della chat,
link di approvazione, posta e chat AI del SOC, tentativi di accesso, sessioni.
Ogni regola ha un termine in giorni (SiteConfig ``gdpr_ret_<codice>_giorni``,
default dalla checklist GDPR del 21/10/2026) e fa una sola cosa: cancella le
righe oltre il termine o, dove la riga serve ancora (posta SOC: dedup e report),
svuota i campi personali.

I dati di dominio (dipendenti cessati, candidati) NON passano da qui: restano
nella pagina «Conservazione dei dati» dell'anagrafica, con conferma di un
amministratore (``anagrafica/services/retention.py``).

Il job notturno ``gdpr_retention`` chiama ``esegui(apply=True)``; il comando
``manage.py gdpr_retention`` senza ``--apply`` mostra solo i conteggi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from django.utils import timezone

logger = logging.getLogger(__name__)

GIORNI_MIN = 7
GIORNI_MAX = 3650


@dataclass(frozen=True)
class Regola:
    codice: str
    titolo: str
    giorni_default: int
    # (cutoff, apply) -> righe toccate (o che si toccherebbero)
    esegui: Callable


def _conta_o_cancella(qs, apply: bool) -> int:
    if not apply:
        return qs.count()
    eliminati, _ = qs.delete()
    return eliminati


def _monitoring_occorrenze(cutoff, apply):
    from monitoring.models import IssueOccurrence

    return _conta_o_cancella(IssueOccurrence.objects.filter(created_at__lt=cutoff), apply)


def _monitoring_segnalazioni(cutoff, apply):
    """Segnalazioni degli utenti oltre il termine, solo se la issue e' chiusa (o non c'e')."""
    from django.db.models import Q

    from monitoring.models import Issue, UserProblemReport

    chiuse = (Issue.Status.RESOLVED, Issue.Status.IGNORED)
    qs = UserProblemReport.objects.filter(created_at__lt=cutoff).filter(
        Q(issue__isnull=True) | Q(issue__status__in=chiuse, issue__updated_at__lt=cutoff)
    )
    return _conta_o_cancella(qs, apply)


def _monitoring_esecuzioni(cutoff, apply):
    """Esecuzioni dei job oltre il termine, tenendo sempre l'ultima di ogni job
    (serve al monitoraggio dei job mensili)."""
    from django.db.models import Max

    from monitoring.models import AutomationExecution

    ultime = AutomationExecution.objects.values("job_id").annotate(ultima=Max("id")).order_by()
    da_tenere = [r["ultima"] for r in ultime]
    qs = AutomationExecution.objects.filter(created_at__lt=cutoff).exclude(id__in=da_tenere)
    return _conta_o_cancella(qs, apply)


def _ai_feedback(cutoff, apply):
    from ai_assistant.models import AiChatFeedback

    return _conta_o_cancella(AiChatFeedback.objects.filter(created_at__lt=cutoff), apply)


def _approval_link(cutoff, apply):
    """Link (email destinatario + impronta del token) di approvazioni gia' decise o
    scadute: chi ha deciso e quando resta su ``AutomationApproval``."""
    from automazioni.models import AutomationApproval, AutomationApprovalLink

    qs = AutomationApprovalLink.objects.filter(created_at__lt=cutoff).exclude(
        approval__status=AutomationApproval.Status.PENDING
    )
    return _conta_o_cancella(qs, apply)


def _approval_posta(cutoff, apply):
    """Risposte di approvazione lette dalla casella (corpo email): solo quelle gia' elaborate."""
    from automazioni.models import ApprovalMailboxMessage

    qs = ApprovalMailboxMessage.objects.filter(received_at__lt=cutoff, processed_at__isnull=False)
    return _conta_o_cancella(qs, apply)


def _soc_posta(cutoff, apply):
    """Messaggi della casella SOC: la riga resta (dedup, report collegati), si
    svuotano mittente, corpo e payload originale."""
    from django.db.models import Q

    from security.models import SecurityMailboxMessage

    qs = SecurityMailboxMessage.objects.filter(received_at__lt=cutoff).filter(
        ~Q(body="") | ~Q(sender="")
    )
    if not apply:
        return qs.count()
    return qs.update(sender="", body="", raw_payload={})


def _soc_ai(cutoff, apply):
    from security.models import AIConversation, SecurityAiInteractionLog

    n = _conta_o_cancella(SecurityAiInteractionLog.objects.filter(created_at__lt=cutoff), apply)
    return n + _conta_o_cancella(AIConversation.objects.filter(updated_at__lt=cutoff), apply)


def _accessi(cutoff, apply):
    from axes.models import AccessAttempt, AccessFailureLog, AccessLog

    n = 0
    for model in (AccessAttempt, AccessFailureLog, AccessLog):
        n += _conta_o_cancella(model.objects.filter(attempt_time__lt=cutoff), apply)
    return n


def _sessioni(_cutoff, apply):
    """Sessioni scadute (come ``clearsessions``): il termine non si applica."""
    from django.contrib.sessions.models import Session

    return _conta_o_cancella(Session.objects.filter(expire_date__lt=timezone.now()), apply)


REGOLE: tuple[Regola, ...] = (
    Regola("monitoring_occorrenze", "Monitoring: occorrenze degli errori", 90, _monitoring_occorrenze),
    Regola("monitoring_segnalazioni", "Monitoring: segnalazioni degli utenti (issue chiusa)", 365,
           _monitoring_segnalazioni),
    Regola("monitoring_esecuzioni", "Monitoring: esecuzioni dei job (tranne l'ultima)", 30, _monitoring_esecuzioni),
    Regola("ai_feedback", "Assistente AI: feedback della chat", 90, _ai_feedback),
    Regola("approval_link", "Automazioni: link di approvazione decisi o scaduti", 180, _approval_link),
    Regola("approval_posta", "Automazioni: risposte di approvazione lette dalla casella", 180, _approval_posta),
    Regola("soc_posta", "SOC: mittente e corpo dei messaggi della casella", 365, _soc_posta),
    Regola("soc_ai", "SOC: chat e log dell'AI", 365, _soc_ai),
    Regola("accessi", "Tentativi di accesso (axes)", 90, _accessi),
    Regola("sessioni", "Sessioni scadute", GIORNI_MIN, _sessioni),
)


def chiave(regola: Regola) -> str:
    return f"gdpr_ret_{regola.codice}_giorni"


def giorni(regola: Regola) -> int:
    """Termine della regola da SiteConfig, con default e limiti (degrada sul default)."""
    try:
        from core.models import SiteConfig

        valore = int(SiteConfig.get(chiave(regola), "") or regola.giorni_default)
    except Exception:
        return regola.giorni_default
    return max(GIORNI_MIN, min(valore, GIORNI_MAX))


def esegui(*, apply: bool = False, solo: str | None = None) -> list[dict]:
    """Esegue (o simula) le regole. Una regola che fallisce non ferma le altre."""
    esiti = []
    for regola in REGOLE:
        if solo and regola.codice != solo:
            continue
        termine = giorni(regola)
        cutoff = timezone.now() - timedelta(days=termine)
        esito = {"codice": regola.codice, "titolo": regola.titolo, "giorni": termine, "righe": 0, "errore": ""}
        try:
            esito["righe"] = int(regola.esegui(cutoff, apply) or 0)
        except Exception as exc:
            logger.exception("gdpr_retention: regola %s fallita", regola.codice)
            esito["errore"] = f"{type(exc).__name__}: {exc}"[:300]
        esiti.append(esito)
    if apply:
        from core.audit import log_action

        log_action(None, "gdpr_retention", "core", {
            "regole": {e["codice"]: {"giorni": e["giorni"], "righe": e["righe"], "errore": e["errore"]}
                       for e in esiti},
        })
    return esiti
