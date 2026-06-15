"""Task periodici django-q2 per il modulo tickets.

Registrati via automazioni.schedules + setup_q_schedules. Speculare a
``anomalie/tasks.py``.
"""
from __future__ import annotations

import logging

from automazioni.system_runlog import system_job_run

logger = logging.getLogger("tickets.tasks")


def _fetch_tickets_da_escalare(soglia_ore: int):
    """Ticket URGENTE ancora APERTA e senza assegnatario da > soglia_ore.

    ``incide_sicurezza`` forza già la priorità a URGENTE in Ticket.save, quindi
    il filtro su priorità copre entrambi i casi. Ritorna un queryset ordinato dal
    più vecchio (il più in ritardo per primo).
    """
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone

    from tickets.models import PrioritaTicket, StatoTicket, Ticket

    cutoff = timezone.now() - timedelta(hours=int(soglia_ore))
    return (
        Ticket.objects.filter(
            stato=StatoTicket.APERTA,
            priorita=PrioritaTicket.URGENTE,
            created_at__lt=cutoff,
        )
        .filter(Q(assegnato_a="") | Q(assegnato_a__isnull=True))
        .order_by("created_at")
    )


def _create_ticket_reminders(tickets) -> int:
    """Promemoria in-app (core.Notifica, tipo ticket_sla) per i ticket non gestiti.

    Idempotente per (destinatario, url): non duplica se esiste già una notifica
    non letta dello stesso tipo che punta allo stesso ticket. Destinatari:
    - il team gestori del tipo (risolto via email → legacy_user_id);
    - il richiedente del ticket (legacy id già sul modello).
    Ritorna il numero di notifiche create.
    """
    from core.models import Notifica
    from core.notifiche import legacy_user_ids_for_email
    from tickets.models import TicketImpostazioni

    # Cache team gestori per tipo, per non rifare la query a ogni ticket.
    team_per_tipo: dict[str, list[str]] = {}

    def _team_emails(tipo: str) -> list[str]:
        if tipo not in team_per_tipo:
            try:
                imp = TicketImpostazioni.objects.filter(tipo=tipo).first()
                raw = (imp.team_gestori if imp else []) or []
                team_per_tipo[tipo] = [
                    str(g.get("email") or "").strip()
                    for g in raw
                    if isinstance(g, dict) and str(g.get("email") or "").strip()
                ]
            except Exception:
                team_per_tipo[tipo] = []
        return team_per_tipo[tipo]

    created = 0
    for t in tickets:
        ore = 0
        if t.created_at:
            from django.utils import timezone
            ore = int((timezone.now() - t.created_at).total_seconds() // 3600)
        messaggio = (
            f"Ticket urgente {t.numero_ticket} non assegnato da {ore}h: {t.titolo}"
        )[:500]
        url = f"/tickets/gestione/{t.pk}/"

        destinatari_ids: set[int] = set()
        for email in _team_emails(t.tipo):
            destinatari_ids.update(legacy_user_ids_for_email(email))
        if t.richiedente_legacy_user_id:
            destinatari_ids.add(int(t.richiedente_legacy_user_id))

        for legacy_uid in destinatari_ids:
            try:
                exists = Notifica.objects.filter(
                    legacy_user_id=legacy_uid,
                    tipo="ticket_sla",
                    url_azione=url,
                    letta=False,
                ).first()
                if exists:
                    if exists.messaggio != messaggio:
                        exists.messaggio = messaggio
                        exists.save(update_fields=["messaggio"])
                    continue
                Notifica.objects.create(
                    legacy_user_id=legacy_uid,
                    tipo="ticket_sla",
                    messaggio=messaggio,
                    url_azione=url,
                )
                created += 1
            except Exception:
                logger.warning(
                    "_create_ticket_reminders: notifica fallita ticket=%s uid=%s",
                    t.numero_ticket, legacy_uid, exc_info=True,
                )
    return created


def _send_escalation_email(tickets) -> bool:
    """Invia UNA mail aggregata al team gestori con i ticket urgenti non assegnati.

    Destinatari: unione dei team_gestori dei tipi coinvolti. Ritorna True se inviata.
    """
    from django.conf import settings
    from django.utils import timezone

    from tickets.models import TicketImpostazioni

    ticket_list = list(tickets)
    if not ticket_list:
        return False

    tipi = {t.tipo for t in ticket_list}
    destinatari: set[str] = set()
    for tipo in tipi:
        imp = TicketImpostazioni.objects.filter(tipo=tipo).first()
        for g in (imp.team_gestori if imp else []) or []:
            if isinstance(g, dict):
                email = str(g.get("email") or "").strip()
                if email:
                    destinatari.add(email)
    if not destinatari:
        logger.info("_send_escalation_email: nessun destinatario team_gestori, skip")
        return False

    righe = []
    for t in ticket_list:
        ore = int((timezone.now() - t.created_at).total_seconds() // 3600) if t.created_at else 0
        righe.append(f"- [{t.numero_ticket}] {t.titolo} — aperto da {ore}h ({t.label_tipo})")
    corpo = (
        "I seguenti ticket URGENTI risultano ancora APERTI e senza assegnatario:\n\n"
        + "\n".join(righe)
        + "\n\nAprire il portale per prenderli in carico."
    )
    subject = f"[Novicrom Hub] {len(ticket_list)} ticket urgenti non assegnati"
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@costruzioninovicrom.it")
    try:
        from core.email_utils import send_hub_mail
        send_hub_mail(
            subject, corpo, sorted(destinatari),
            email_type="Tickets",
            badge="Urgenti non assegnati",
            section_label="Escalation ticket",
            from_email=from_email,
            fail_silently=False,
        )
        logger.info("tickets escalation resoconto inviato a=%s n=%s", sorted(destinatari), len(ticket_list))
        return True
    except Exception:
        logger.exception("tickets escalation resoconto FALLITO")
        return False


@system_job_run("tickets_escalation")
def run_tickets_escalation(*, force_email: bool = False) -> dict:
    """Promemoria + escalation per i ticket URGENTI aperti e non assegnati.

    Eseguito orariamente. A ogni run:
    - aggiorna SEMPRE i promemoria in dashboard (core.Notifica) per team gestori
      e richiedente dei ticket urgenti non gestiti;
    - invia il RESOCONTO email aggregato solo se ``attivo`` è on e siamo nel giorno
      lavorativo (lun-ven) all'``ora_invio`` configurata — oppure se ``force_email=True``.

    Ritorna {"reminders": n, "email_sent": bool, "tickets": m}.
    """
    from django.utils import timezone

    from tickets.escalation_config import get_escalation_config

    cfg = get_escalation_config()
    soglia = int(cfg["soglia_ore"])
    out = {"reminders": 0, "email_sent": False, "tickets": 0}

    try:
        tickets = list(_fetch_tickets_da_escalare(soglia))
    except Exception:
        logger.exception("run_tickets_escalation: fetch ticket fallito")
        return out

    out["tickets"] = len(tickets)
    if not tickets:
        return out

    # 1) Promemoria dashboard: sempre
    try:
        out["reminders"] = _create_ticket_reminders(tickets)
    except Exception:
        logger.exception("run_tickets_escalation: reminders falliti")

    # 2) Email resoconto: solo on + giorno lavorativo + ora di invio (o forzata)
    now = timezone.localtime(timezone.now())
    is_send_window = (
        cfg["attivo"]
        and now.weekday() < 5  # lun(0)..ven(4)
        and now.hour == int(cfg["ora_invio"])
    )
    if force_email or is_send_window:
        try:
            out["email_sent"] = _send_escalation_email(tickets)
        except Exception:
            logger.exception("run_tickets_escalation: invio resoconto fallito")

    if out["reminders"] or out["email_sent"]:
        logger.info(
            "run_tickets_escalation: reminders=%s email_sent=%s tickets=%s",
            out["reminders"], out["email_sent"], out["tickets"],
        )
    return out
