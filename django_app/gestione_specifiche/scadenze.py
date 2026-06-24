"""F4 — Timer/scadenze e notifiche per gestione_specifiche.

Logica pura (clock iniettabile via `now`) usata dai task django-q2 in `tasks.py`.
Canali notifica: email (SMTP esistente) + in-app HUB (core.Notifica). Ogni
esecuzione che agisce scrive un `EventoSpecifica` (audit). Tutto fail-safe: un
errore di notifica non deve impedire l'aggiornamento dello stato timer.
"""
from __future__ import annotations

import logging

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from . import constants as C
from .models import EventoSpecifica, MOD133, Specifica

logger = logging.getLogger(__name__)


def _cfg(key: str, default):
    return (getattr(settings, "GESTIONE_SPECIFICHE", {}) or {}).get(key, default)


def _url_dettaglio(spec: Specifica) -> str:
    try:
        return reverse("gestione_specifiche:dettaglio", args=[spec.pk])
    except Exception:
        return f"/gestione-specifiche/{spec.pk}/"


def _email_for(user) -> str:
    if not user:
        return ""
    try:
        from tasks.outlook_reminder import _notification_email_for_user
        email = _notification_email_for_user(user)
        if email:
            return email
    except Exception:
        pass
    return getattr(user, "email", "") or ""


def _legacy_user_id(user):
    if not user:
        return None
    try:
        from core.legacy_utils import get_legacy_user
        lu = get_legacy_user(user)
        return int(lu.id) if lu and getattr(lu, "id", None) else None
    except Exception:
        return None


def _notifica(users, *, oggetto: str, messaggio: str, url: str, tipo: str = "generico") -> None:
    """Invia email + notifica in-app ai destinatari (fail-safe, dedup)."""
    seen = set()
    for user in users:
        if user is None or user.id in seen:
            continue
        seen.add(user.id)
        # in-app
        lid = _legacy_user_id(user)
        if lid is not None:
            try:
                from core.notifiche import invia_notifica
                invia_notifica(legacy_user_id=lid, tipo=tipo, messaggio=messaggio, url_azione=url)
            except Exception as exc:
                logger.debug("gs notifica in-app fallita: %s", exc)
        # email
        email = _email_for(user)
        if email:
            try:
                from core.email_utils import send_hub_mail
                send_hub_mail(
                    subject=oggetto, body_text=messaggio, recipients=[email],
                    title="Gestione Specifiche", email_type="Scadenze",
                    fail_silently=True,
                )
            except Exception as exc:
                logger.debug("gs email fallita: %s", exc)


def _log_evento(spec: Specifica, trigger: str, payload: dict) -> None:
    try:
        EventoSpecifica.objects.create(
            specifica=spec, stato_da=spec.stato, stato_a=spec.stato,
            attore=None, trigger=trigger,
            payload={"snapshot": spec.snapshot_metadati(), **payload},
        )
    except Exception as exc:
        logger.debug("gs log evento timer fallito: %s", exc)


# ---------------------------------------------------------------------------

def invia_reminder_mod133(now=None) -> dict:
    """Reminder 7gg: MOD.133 in flow-down non ancora preso in carico."""
    now = now or timezone.now()
    giorni = int(_cfg("REMINDER_GIORNI", 7))
    inviati = 0
    qs = MOD133.objects.select_related("specifica", "avviato_da").filter(
        reminder_inviato=False, timer_anchor__isnull=False, timer_pausa_at__isnull=True,
    )
    for mod in qs:
        spec = mod.specifica
        if spec.stato != C.STATO_FLOW_DOWN:      # pausa S5/S9 o uscito dallo stato
            continue
        if mod.compilatore_id:                   # preso in carico -> stop reminder
            continue
        if (now - mod.timer_anchor).days < giorni:
            continue
        _notifica(
            [mod.avviato_da, mod.compilatore],
            oggetto=f"Promemoria MOD.133 — {spec.codice}",
            messaggio=f"Il MOD.133 della specifica {spec.codice} attende la presa in carico da {giorni} giorni.",
            url=_url_dettaglio(spec), tipo="generico",
        )
        mod.reminder_inviato = True
        mod.save(update_fields=["reminder_inviato", "updated_at"])
        _log_evento(spec, "reminder_mod133", {"giorni": giorni})
        inviati += 1
    return {"reminder_inviati": inviati}


def invia_escalation_mod133(now=None) -> dict:
    """Escalation 14gg: MOD.133 ancora in flow-down → Approvatore + DM (+SGI opz.)."""
    now = now or timezone.now()
    giorni = int(_cfg("ESCALATION_GIORNI", 14))
    inviate = 0
    qs = MOD133.objects.select_related("specifica", "avviato_da", "approvatore").filter(
        escalation_inviata=False, timer_anchor__isnull=False, timer_pausa_at__isnull=True,
    )
    for mod in qs:
        spec = mod.specifica
        if spec.stato != C.STATO_FLOW_DOWN:
            continue
        if (now - mod.timer_anchor).days < giorni:
            continue
        _notifica(
            [mod.approvatore, mod.avviato_da, mod.compilatore],
            oggetto=f"ESCALATION MOD.133 — {spec.codice}",
            messaggio=f"Il MOD.133 della specifica {spec.codice} è in flow-down da oltre {giorni} giorni senza approvazione.",
            url=_url_dettaglio(spec), tipo="generico",
        )
        mod.escalation_inviata = True
        mod.save(update_fields=["escalation_inviata", "updated_at"])
        _log_evento(spec, "escalation_mod133", {"giorni": giorni})
        inviate += 1
    return {"escalation_inviate": inviate}


def esegui_verifica_periodica(now=None) -> dict:
    """Verifica periodica: specifiche in validità con data_verifica scaduta.

    Ricorrente: dopo il reminder, avanza `data_verifica` di VERIFICA_PERIODICA_MESI.
    """
    now = now or timezone.now()
    oggi = now.date()
    mesi = int(_cfg("VERIFICA_PERIODICA_MESI", 6))
    inviati = 0
    qs = Specifica.objects.filter(
        stato=C.STATO_IN_VALIDITA, data_verifica__isnull=False, data_verifica__lte=oggi,
    )
    for spec in qs:
        mod = MOD133.objects.filter(specifica=spec).first()
        destinatari = [mod.approvatore, mod.compilatore] if mod else []
        _notifica(
            destinatari,
            oggetto=f"Verifica periodica — {spec.codice}",
            messaggio=f"La specifica {spec.codice} è in scadenza di verifica periodica (al {spec.data_verifica}).",
            url=_url_dettaglio(spec), tipo="generico",
        )
        spec.verifica_reminder_inviata_at = now
        spec.data_verifica = spec.data_verifica + relativedelta(months=mesi)
        spec.save(update_fields=["verifica_reminder_inviata_at", "data_verifica", "updated_at"])
        _log_evento(spec, "verifica_periodica", {"prossima_verifica": spec.data_verifica.isoformat()})
        inviati += 1
    return {"verifiche_inviate": inviati}
