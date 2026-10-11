"""Invito Outlook dell'audit con richiesta di conferma agli auditati (Microsoft Graph).

Riusa ``core.outlook_calendar``. L'evento vive nel calendario dell'organizzatore (Lead
Auditor o casella configurata); le risposte dei partecipanti si rileggono da Graph e si
riportano su ``AuditPersona.conferma_stato``. Nessuna chiamata di rete dentro transazioni.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time

from django.utils import timezone
from django.utils.html import escape

from ..models import Audit, AuditPersona

CHIAVE_ORGANIZZATORE = "sistema_gestione.audit_organizer_email"
_STATI = {"accepted": "ACCETTATO", "tentativelyAccepted": "PROVVISORIO", "declined": "RIFIUTATO",
          "none": "IN_ATTESA", "notResponded": "IN_ATTESA", "organizer": "ACCETTATO"}


def organizzatore(audit: Audit) -> str:
    from core.models import SiteConfig

    configurato = (SiteConfig.get(CHIAVE_ORGANIZZATORE, "") or "").strip()
    lead = getattr(audit.lead_auditor.user, "email", "") if audit.lead_auditor.user_id else ""
    return audit.outlook_organizer_email or configurato or (lead or "").strip()


def partecipanti(audit: Audit) -> list[AuditPersona]:
    return [p for p in audit.persone.filter(ruolo__in=[AuditPersona.RUOLO_AUDITATO, AuditPersona.RUOLO_PROCESSO])
            if p.email.strip()]


def payload_evento(audit: Audit) -> dict:
    inizio = datetime.combine(audit.data_inizio, time(9, 0))
    fine = datetime.combine(audit.data_fine or audit.data_inizio, time(17, 0))
    corpo = (f"<p>È pianificato l'audit interno <strong>{escape(audit.numero)}</strong>.</p>"
             f"<p>Processi/aree: {escape(audit.processi)}<br>Norme: {escape(audit.norme_label)}<br>"
             f"Sede: {escape(audit.sede or 'da definire')}</p><p>Conferma la tua presenza rispondendo all'invito.</p>")
    visti, invitati = set(), []
    for p in partecipanti(audit):
        email = p.email.strip().lower()
        if email not in visti:
            visti.add(email)
            invitati.append({"emailAddress": {"address": p.email.strip(), "name": p.nome}, "type": "required"})
    return {
        "subject": f"Audit interno {audit.numero}"[:255],
        "body": {"contentType": "HTML", "content": corpo},
        "start": {"dateTime": inizio.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Europe/Rome"},
        "end": {"dateTime": fine.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "Europe/Rome"},
        "location": {"displayName": (audit.sede or "Da definire")[:255]},
        "attendees": invitati, "responseRequested": True, "showAs": "busy",
        "transactionId": str(uuid.uuid5(uuid.NAMESPACE_URL, f"novicrom-hub/audit/{audit.pk}/invito")),
    }


def invia_invito(audit: Audit) -> str:
    """Crea o aggiorna l'evento; restituisce l'id. Solleva RuntimeError con un messaggio leggibile."""
    from core import outlook_calendar as oc

    if not oc.graph_ready():
        raise RuntimeError("Microsoft Graph non è configurato: usa la comunicazione via email con invito calendario.")
    casella = organizzatore(audit)
    if not casella:
        raise RuntimeError(f"Manca la casella dell'organizzatore: email del Lead Auditor o impostazione «{CHIAVE_ORGANIZZATORE}».")
    if not partecipanti(audit):
        raise RuntimeError("Nessun auditato o responsabile di processo con email da invitare.")
    payload = payload_evento(audit)
    if audit.outlook_event_id:
        evento = oc.update_event(target_email=casella, event_id=audit.outlook_event_id, payload=payload)
    else:
        evento = oc.create_event(target_email=casella, payload=payload)
    audit.outlook_event_id = str(evento.get("id") or audit.outlook_event_id)
    audit.outlook_organizer_email = casella
    audit.save(update_fields=["outlook_event_id", "outlook_organizer_email", "updated_at"])
    AuditPersona.objects.filter(pk__in=[p.pk for p in partecipanti(audit)], conferma_stato="").update(conferma_stato="IN_ATTESA")
    return audit.outlook_event_id


def aggiorna_conferme(audit: Audit) -> dict[str, int]:
    """Rilegge da Graph le risposte all'invito e le riporta sulle persone dell'audit."""
    from core import outlook_calendar as oc

    if not audit.outlook_event_id:
        raise RuntimeError("L'audit non ha ancora un invito Outlook.")
    evento = oc.get_event(target_email=audit.outlook_organizer_email or organizzatore(audit), event_id=audit.outlook_event_id)
    risposte = {}
    for voce in evento.get("attendees") or []:
        email = str((voce.get("emailAddress") or {}).get("address") or "").strip().lower()
        stato = _STATI.get(str((voce.get("status") or {}).get("response") or "none"), "IN_ATTESA")
        if email:
            risposte[email] = stato
    conteggio: dict[str, int] = {}
    adesso = timezone.now()
    for persona in partecipanti(audit):
        stato = risposte.get(persona.email.strip().lower())
        if stato and stato != persona.conferma_stato:
            persona.conferma_stato = stato
            persona.conferma_il = adesso
            persona.save(update_fields=["conferma_stato", "conferma_il"])
        if stato:
            conteggio[stato] = conteggio.get(stato, 0) + 1
    audit.conferme_aggiornate_il = adesso
    audit.save(update_fields=["conferme_aggiornate_il", "updated_at"])
    return conteggio


def annulla_invito(audit: Audit) -> bool:
    from core import outlook_calendar as oc

    if not audit.outlook_event_id or not oc.graph_ready():
        return False
    return oc.delete_event(target_email=audit.outlook_organizer_email or organizzatore(audit), event_id=audit.outlook_event_id)
