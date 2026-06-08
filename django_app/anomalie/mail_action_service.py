"""Servizio per invio email di azione anomalie con token sicuro monouso.

Uso:
    from anomalie.mail_action_service import build_anomalie_action_email, send_anomalie_action_email

    token = send_anomalie_action_email(
        recipient_user=request.user,          # o None se non disponibile
        recipient_email="cc@esempio.it",
        recipient_display="Mario Rossi",
        recipient_legacy_user_id=42,
        op_id="OP-2026-001",
        op_nominativo="Lavorazione flangia",
        anomalie_rows=[{"id": 1, "descrizione": "...", ...}, ...],
        action="visualizza",
        expires_hours=48,
        source_automation="anomalia_segnalata",
    )
    # token è l'istanza AnomaliaMailActionToken creata e inviata
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

# Soglia oltre la quale la mail tronca l'elenco a MAX_ANOMALIE_IN_EMAIL
MAX_ANOMALIE_IN_EMAIL = 10


def build_anomalie_action_email(
    *,
    recipient_email: str,
    recipient_display: str,
    op_id: str,
    op_nominativo: str,
    anomalie_rows: list[dict],
    action: str,
    token_str: str,
    expires_at,
    site_url: str | None = None,
) -> tuple[str, str, str]:
    """Costruisce (subject, body_text, body_html) per l'email di notifica anomalie.

    Non invia: restituisce le tre stringhe per poter testare il rendering separatamente.
    """
    if site_url is None:
        site_url = getattr(settings, "SITE_URL", "").rstrip("/")

    action_url = site_url + reverse("anomalie_mail_action", kwargs={"token": token_str})

    n_tot = len(anomalie_rows)
    troncato = n_tot > MAX_ANOMALIE_IN_EMAIL
    anomalie_visibili = anomalie_rows[:MAX_ANOMALIE_IN_EMAIL]

    action_labels = {
        "prendi_in_carico": "Prendi in carico",
        "approva": "Approva",
        "respingi": "Respingi",
        "richiedi_modifica": "Richiedi modifica",
        "chiudi": "Chiudi",
        "visualizza": "Visualizza",
    }
    action_label = action_labels.get(action, action.replace("_", " ").title())

    if n_tot == 1:
        a = anomalie_visibili[0]
        subject = (
            f"[Novicrom Hub] Anomalia #{a.get('id', '?')} su OP {op_id}"
            f" — {action_label}"
        )
    else:
        subject = (
            f"[Novicrom Hub] {n_tot} anomalie su OP {op_id}"
            f" — {action_label} richiesta"
        )

    body_text = _build_plain_text(
        recipient_display=recipient_display,
        op_id=op_id,
        op_nominativo=op_nominativo,
        anomalie_visibili=anomalie_visibili,
        n_tot=n_tot,
        troncato=troncato,
        action_label=action_label,
        action_url=action_url,
        expires_at=expires_at,
    )

    body_html = render_to_string(
        "anomalie/email/anomalie_action_email.html",
        {
            "recipient_display": recipient_display,
            "op_id": op_id,
            "op_nominativo": op_nominativo,
            "anomalie_visibili": anomalie_visibili,
            "n_tot": n_tot,
            "troncato": troncato,
            "max_in_email": MAX_ANOMALIE_IN_EMAIL,
            "action": action,
            "action_label": action_label,
            "action_url": action_url,
            "expires_at": expires_at,
            "site_url": site_url,
        },
    )

    return subject, body_text, body_html


def send_anomalie_action_email(
    *,
    recipient_user=None,
    recipient_email: str,
    recipient_display: str,
    recipient_legacy_user_id: int | None = None,
    op_id: str,
    op_nominativo: str,
    anomalie_rows: list[dict],
    action: str,
    expires_hours: int = 48,
    source_automation: str = "",
    created_by=None,
    site_url: str | None = None,
    from_email: str | None = None,
) -> "AnomaliaMailActionToken":
    """Crea il token, costruisce l'email e la invia.

    Ritorna l'istanza AnomaliaMailActionToken creata.
    """
    from .mail_action_models import AnomaliaMailActionToken

    expires_at = timezone.now() + timedelta(hours=expires_hours)

    token_obj = AnomaliaMailActionToken.objects.create(
        recipient_user=recipient_user,
        recipient_legacy_user_id=recipient_legacy_user_id,
        recipient_email=recipient_email,
        recipient_display=recipient_display,
        op_id=op_id,
        op_nominativo=op_nominativo,
        anomalie_ids=[r["id"] for r in anomalie_rows if r.get("id") is not None],
        anomalie_snapshot=anomalie_rows,
        action=action,
        expires_at=expires_at,
        source_automation=source_automation,
        created_by=created_by,
    )

    subject, body_text, body_html = build_anomalie_action_email(
        recipient_email=recipient_email,
        recipient_display=recipient_display,
        op_id=op_id,
        op_nominativo=op_nominativo,
        anomalie_rows=anomalie_rows,
        action=action,
        token_str=token_obj.token,
        expires_at=expires_at,
        site_url=site_url,
    )

    _from = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@costruzioninovicrom.it")

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body_text,
        from_email=_from,
        to=[recipient_email],
    )
    msg.attach_alternative(body_html, "text/html")

    try:
        msg.send(fail_silently=False)
        logger.info(
            "anomalie mail_action email inviata token=%s op=%s action=%s a=%s",
            token_obj.token[:8],
            op_id,
            action,
            recipient_email,
        )
    except Exception:
        logger.exception(
            "anomalie mail_action email FALLITA token=%s op=%s a=%s",
            token_obj.token[:8],
            op_id,
            recipient_email,
        )
        raise

    return token_obj


def _build_plain_text(
    *,
    recipient_display: str,
    op_id: str,
    op_nominativo: str,
    anomalie_visibili: list[dict],
    n_tot: int,
    troncato: bool,
    action_label: str,
    action_url: str,
    expires_at: Any,
) -> str:
    lines = [
        f"Gentile {recipient_display},",
        "",
        f"Hai {'un'if n_tot == 1 else str(n_tot)} anomali{'a' if n_tot == 1 else 'e'} "
        f"sull'OP {op_id}{(' — ' + op_nominativo) if op_nominativo else ''} "
        f"che {'richiede' if n_tot == 1 else 'richiedono'} la tua attenzione.",
        "",
        "ANOMALIE:",
    ]
    for a in anomalie_visibili:
        desc = a.get("descrizione") or a.get("descrizione_breve") or "(nessuna descrizione)"
        stato = a.get("avanzamento") or a.get("stato") or ""
        lines.append(f"  • #{a.get('id', '?')} — {desc[:120]}" + (f" [{stato}]" if stato else ""))
    if troncato:
        lines.append(f"  … e altre {n_tot - len(anomalie_visibili)} anomalie (apri il link per vedere tutto)")
    lines += [
        "",
        f"AZIONE RICHIESTA: {action_label}",
        "",
        f"Apri la pagina sicura del portale per rispondere:",
        action_url,
        "",
    ]
    if expires_at:
        try:
            from django.utils import timezone as _tz
            local_exp = _tz.localtime(expires_at)
            lines.append(f"Link valido fino a: {local_exp.strftime('%d/%m/%Y %H:%M')}")
        except Exception:
            pass
    lines += [
        "",
        "—",
        "NOVICROM HUB · Portale interno · Email automatica",
        "Non rispondere a questa email.",
    ]
    return "\n".join(lines)
