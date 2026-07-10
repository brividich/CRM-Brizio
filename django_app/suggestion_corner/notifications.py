"""Notifiche email del modulo Suggestion Corner (sessione 5, §3).

Riusa il frame grafico HUB (`core.email_utils.send_hub_mail`). Destinatari del
team = membri del Django Group SMS_TEAM; solleciti/escalation ai referenti
(incaricato/controllore) e al responsabile configurato.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import Group

from core.email_utils import send_hub_mail

from .models import SuggestionCorner, SuggestionCornerConfig

EMAIL_TYPE = "Suggestion Corner"


def _base_url() -> str:
    return (getattr(settings, "SITE_URL", "") or "").rstrip("/")


def _dettaglio_url(seg) -> str:
    return f"{_base_url()}/suggestion-corner/{seg.pk}/"


def team_emails() -> list[str]:
    """Email dei membri attivi del Group SMS_TEAM (deduplicate, non vuote)."""
    name = SuggestionCornerConfig.load().sms_team_group_name
    try:
        group = Group.objects.get(name=name)
    except Group.DoesNotExist:
        return []
    emails = []
    for u in group.user_set.filter(is_active=True):
        if u.email and u.email not in emails:
            emails.append(u.email)
    return emails


def notifica_team_nuova_segnalazione(seg) -> int:
    """Mail al team SMS all'arrivo di una nuova segnalazione (§5)."""
    dest = team_emails()
    if not dest:
        return 0
    reparto = seg.reparto_provenienza.nome if seg.reparto_provenienza_id else "—"
    body = (
        f"È arrivata una nuova segnalazione dal reparto {reparto}.\n\n"
        f"{seg.opportunity}\n\n"
        f"Prendila in carico e classificala: {_dettaglio_url(seg)}"
    )
    return send_hub_mail(
        f"[Suggestion Corner] Nuova segnalazione SC#{seg.pk}",
        body, dest,
        title="Nuova segnalazione da classificare",
        email_type=EMAIL_TYPE, badge="Da gestire", fail_silently=True,
    )


def notifica_cliente_sms(seg, messaggio: str = "") -> int:
    """Comunicazione al cliente per una segnalazione classificata SMS Sì.

    Destinatario = `seg.cliente_email` (per-segnalazione). Invio manuale dal team.
    `fail_silently=False`: l'esito è restituito al chiamante (la view marca la
    comunicazione come inviata solo se l'invio riesce)."""
    if not seg.cliente_email:
        return 0
    reparto = seg.reparto_provenienza.nome if seg.reparto_provenienza_id else "—"
    corpo = (
        f"Gentile {seg.cliente_nome or 'cliente'},\n\n"
        f"nell'ambito del nostro Sistema di Miglioramento/Segnalazione (SMS) le "
        f"comunichiamo la seguente segnalazione (SC#{seg.pk}, reparto {reparto}):\n\n"
        f"{seg.opportunity}\n"
    )
    if messaggio:
        corpo += f"\n{messaggio}\n"
    return send_hub_mail(
        f"[Suggestion Corner] Comunicazione SMS — SC#{seg.pk}",
        corpo, [seg.cliente_email],
        title="Comunicazione al cliente (SMS)", email_type=EMAIL_TYPE,
        badge="SMS Sì", fail_silently=False,
    )


def _sollecito(dest_email: str, seg, fase: str, giorni: int) -> int:
    if not dest_email:
        return 0
    quando = "scaduta" if giorni < 0 else f"tra {giorni} giorni"
    body = (
        f"La fase {fase} della segnalazione SC#{seg.pk} è {quando}.\n\n"
        f"{seg.opportunity[:200]}\n\nApri: {_dettaglio_url(seg)}"
    )
    return send_hub_mail(
        f"[Suggestion Corner] Sollecito {fase} — SC#{seg.pk}",
        body, [dest_email],
        title=f"Sollecito {fase}", email_type=EMAIL_TYPE,
        badge="Scaduta" if giorni < 0 else "In scadenza", fail_silently=True,
    )


def notifica_assegnazione_in_app(seg) -> int:
    """Notifica in-app (sessione 6) a incaricato e controllore quando il PLAN è
    definito. Riusa `core.notifiche.invia_notifica` (rispetta gli interruttori
    on/off via notifiche_prefs). Convenzione legacy_user_id = Django user.id.
    """
    from core.notifiche import invia_notifica

    url = f"/suggestion-corner/{seg.pk}/"
    n = 0
    if seg.incaricato_id:
        invia_notifica(seg.incaricato_id, "sc_assegnazione",
                       f"Ti è stato assegnato il DO della segnalazione SC#{seg.pk}.", url)
        n += 1
    if seg.controllore_id:
        invia_notifica(seg.controllore_id, "sc_assegnazione",
                       f"Ti è stato assegnato il CHECK della segnalazione SC#{seg.pk}.", url)
        n += 1
    return n


def _escalation(seg, fase: str) -> int:
    dest = SuggestionCornerConfig.load().email_responsabile_escalation
    if not dest:
        return 0
    body = (
        f"La fase {fase} della segnalazione SC#{seg.pk} è scaduta oltre la soglia "
        f"di escalation e non risulta completata.\n\nApri: {_dettaglio_url(seg)}"
    )
    return send_hub_mail(
        f"[Suggestion Corner] ESCALATION {fase} — SC#{seg.pk}",
        body, [dest],
        title=f"Escalation {fase}", email_type=EMAIL_TYPE,
        badge="Escalation", fail_silently=True,
    )
