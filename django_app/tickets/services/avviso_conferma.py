"""Mail a chi ha aperto il ticket quando il tecnico lo segna «Risolto».

La chiusura la conferma chi l'ha aperto (vedi ``stato.stato_di_chiusura``): senza
questa mail il richiedente non saprebbe di dover rispondere. Best-effort: un errore
di invio non annulla il cambio di stato.
"""

from __future__ import annotations

import logging
from html import escape

logger = logging.getLogger("tickets.views")

OGGETTO = "[Ticket {numero}] Risolto: confermi la chiusura?"


def destinatari_conferma(ticket) -> list[str]:
    """Richiedente e compilatore «per conto di», senza doppioni."""
    indirizzi = [ticket.richiedente_email]
    if ticket.aperto_da_user_id:
        indirizzi.append(getattr(ticket.aperto_da_user, "email", ""))
    visti: dict[str, str] = {}
    for indirizzo in indirizzi:
        pulito = str(indirizzo or "").strip()
        if pulito and "@" in pulito:
            visti.setdefault(pulito.lower(), pulito)
    return list(visti.values())


def invia_richiesta_conferma(ticket, *, risolto_da: str = "") -> bool:
    """Ritorna True se la mail e' partita. Non solleva mai."""
    try:
        destinatari = destinatari_conferma(ticket)
        if not destinatari:
            logger.info("Ticket %s risolto: nessun indirizzo di chi l'ha aperto, mail non inviata", ticket.pk)
            return False

        from django.urls import reverse

        from core.accounts.portal_links import portal_link
        from core.email_utils import send_hub_mail

        link = portal_link(reverse("tickets:detail", args=[ticket.pk]))
        ultimo = ticket.interventi.order_by("-data_fine", "-pk").first() if ticket.pk else None
        fatti = [
            ("Ticket", f"{ticket.numero_ticket} — {ticket.titolo}"),
            ("Risolto da", risolto_da or ticket.risolto_da_nome or ticket.assegnato_a or "—"),
        ]
        if ultimo and ultimo.descrizione_lavoro:
            fatti.append(("Cosa è stato fatto", ultimo.descrizione_lavoro))

        righe = "".join(
            f'<tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#475569;white-space:nowrap;vertical-align:top;">{escape(n)}</td>'
            f'<td style="padding:6px 0 6px 12px;color:#0f172a;">{escape(str(v))}</td></tr>'
            for n, v in fatti
        )
        html = (
            '<p style="color:#334155;line-height:1.6;margin:0 0 14px;">Il tecnico ha segnato '
            "<strong>risolto</strong> il ticket che hai aperto. Si chiude solo con la tua conferma.</p>"
            f'<table style="border-collapse:collapse;width:100%;margin:4px 0 16px;">{righe}</table>'
            + (
                f'<p style="margin:0 0 14px;"><a href="{escape(link)}" style="display:inline-block;padding:10px 18px;'
                'background:#06264f;color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;">'
                "Conferma o riapri</a></p>"
                if link else ""
            )
            +
            '<p style="color:#64748b;font-size:13px;margin:0;">Nella scheda: «Sì, è risolto: chiudi il ticket» '
            "oppure «No, non è risolto» con una nota per il tecnico.</p>"
        )
        testo = "\n".join([
            "Il tecnico ha segnato risolto il ticket che hai aperto. Si chiude solo con la tua conferma.",
            "",
            *[f"{n}: {v}" for n, v in fatti],
            "",
            f"Conferma o riapri: {link}" if link else "Apri il ticket nel portale da «I miei ticket».",
        ])
        send_hub_mail(
            OGGETTO.format(numero=ticket.numero_ticket),
            testo,
            destinatari,
            title="Ticket risolto: confermi?",
            email_type="Tickets",
            badge="Da confermare",
            section_label="Ticket",
            body_html_fragment=html,
            preheader=f"Il ticket {ticket.numero_ticket} è risolto: conferma la chiusura o riaprilo.",
            fail_silently=False,
        )
        return True
    except Exception:
        logger.warning("Ticket %s: mail di conferma chiusura non inviata", getattr(ticket, "pk", None), exc_info=True)
        return False
