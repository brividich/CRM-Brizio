"""Mail al richiedente alla chiusura del ticket: rimandarla dalla scheda.

La mail la manda la regola automazioni ``REGOLA`` quando il trigger del database
accoda il cambio di stato. Qui la si riesegue a mano per un ticket già chiuso
(mail mai partita, richiedente che non la trova), con lo stesso payload che
produrrebbe il trigger: resta un run log in Automazioni e la riga in Mail inviate.
"""

from __future__ import annotations

import json
import logging

from django.core.serializers.json import DjangoJSONEncoder

from ..models import StatoTicket, Ticket, TicketStatoLog

logger = logging.getLogger(__name__)

REGOLA = "tickets-cambio-stato-email-richiedente"


def _riga_ticket(ticket: Ticket) -> dict:
    """La riga come la scrive il trigger (``SELECT * ... FOR JSON``): colonne del database."""
    riga = {f.column: getattr(ticket, f.attname) for f in Ticket._meta.concrete_fields}
    return json.loads(json.dumps(riga, cls=DjangoJSONEncoder))


def puo_rimandare(ticket: Ticket) -> bool:
    return ticket.stato == StatoTicket.CHIUSO and bool((ticket.richiedente_email or "").strip())


def rimanda_mail_chiusura(ticket: Ticket, user=None) -> tuple[bool, str]:
    """Riesegue la regola della mail di chiusura. Restituisce (riuscito, messaggio per l'utente)."""
    from automazioni.models import AutomationRule, AutomationRunLogStatus
    from automazioni.services import run_rule

    if not puo_rimandare(ticket):
        return False, "Si rimanda solo per un ticket chiuso con la mail del richiedente."
    rule = AutomationRule.objects.filter(code=REGOLA).first()
    if rule is None:
        return False, f"La regola «{REGOLA}» non esiste: va creata in Automazioni → Regole."
    if not rule.is_active or rule.is_draft:
        return False, f"La regola «{REGOLA}» è spenta o in bozza: riattivala in Automazioni → Regole."

    ultimo = (
        TicketStatoLog.objects.filter(ticket=ticket, a_stato=StatoTicket.CHIUSO)
        .order_by("-id").values_list("da_stato", flat=True).first()
    )
    precedente = ultimo if ultimo and ultimo != StatoTicket.CHIUSO else StatoTicket.IN_CARICO
    payload = _riga_ticket(ticket)
    old_payload = {**payload, "stato": precedente}
    payload["old_stato"] = precedente
    payload["old_assegnato_a"] = payload.get("assegnato_a")

    try:
        run_log = run_rule(rule, payload, old_payload=old_payload, initiated_by=user)
    except Exception as exc:
        logger.warning("Rimanda mail chiusura ticket %s non riuscito", ticket.pk, exc_info=True)
        return False, f"Invio non riuscito ({type(exc).__name__}): vedi Automazioni → Mail inviate."
    if run_log.status == AutomationRunLogStatus.SUCCESS:
        return True, f"Mail di chiusura rimandata a {ticket.richiedente_email}."
    if run_log.status == AutomationRunLogStatus.SKIPPED:
        return False, f"La regola non ha mandato la mail: {run_log.result_message}"
    return False, f"La mail non è partita (esecuzione #{run_log.pk}): vedi Automazioni → Mail inviate."
