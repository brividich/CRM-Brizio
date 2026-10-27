"""Riesame degli incidenti («Lezioni apprese», ISO 27001 5.27) e azioni correttive.

Un incidente risolto o chiuso senza riesame mostra «Riesame mancante»; dopo N giorni dalla
risoluzione (impostazione ``iso.riesame.giorni``, default 7) parte un promemoria. La chiusura
non viene bloccata: il flusso del registro resta quello di sempre, cambia solo cosa si vede. Le azioni
correttive hanno responsabile e scadenza: scadute e non fatte sono «in ritardo» e ricevono un
promemoria. Ogni scrittura finisce nella traccia dell'incidente (``SecurityIncidentLog``).
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from security.models import SecurityCorrectiveAction, SecurityIncident, SecurityIncidentReview
from security.services import soc_settings
from security.services.incidents import actor_name, log

STATI_CONCLUSI = [SecurityIncident.STATUS_RESOLVED, SecurityIncident.STATUS_CLOSED]


def riesame_di(incident):
    try:
        return incident.riesame
    except SecurityIncidentReview.DoesNotExist:
        return None


def riesame_mancante(incident) -> bool:
    """Vero se l'incidente è risolto o chiuso e non ha le Lezioni apprese."""
    return incident.status in STATI_CONCLUSI and riesame_di(incident) is None


AVVISO_CHIUSURA = ("L'incidente è concluso senza «Lezioni apprese»: compilale nella scheda (causa, cosa ha funzionato, "
                   "cosa migliorare, azioni correttive). Finché mancano resta «Riesame mancante».")


@transaction.atomic
def salva_riesame(incident, user, *, causa, cosa_ha_funzionato="", cosa_migliorare=""):
    causa = (causa or "").strip()
    if not causa:
        raise ValueError("Indica la causa: è la parte che non può mancare nel riesame.")
    riesame, created = SecurityIncidentReview.objects.update_or_create(
        incident=incident,
        defaults={
            "causa": causa[:4000],
            "cosa_ha_funzionato": (cosa_ha_funzionato or "").strip()[:4000],
            "cosa_migliorare": (cosa_migliorare or "").strip()[:4000],
            "created_by": user if getattr(user, "pk", None) else None,
        },
    )
    # Le lezioni apprese restano anche nel campo storico dell'incidente, letto da PDF e report.
    incident.lessons_learned = "\n".join(p for p in (
        f"Causa: {riesame.causa}",
        f"Cosa ha funzionato: {riesame.cosa_ha_funzionato}" if riesame.cosa_ha_funzionato else "",
        f"Cosa migliorare: {riesame.cosa_migliorare}" if riesame.cosa_migliorare else "",
    ) if p)
    incident.save(update_fields=["lessons_learned", "updated_at"])
    log(incident, "riesame", actor_name(user), "Lezioni apprese " + ("registrate" if created else "aggiornate") + ".")
    return riesame


@transaction.atomic
def aggiungi_azione(incident, user, *, titolo, scadenza, responsabile="", note=""):
    titolo = (titolo or "").strip()
    if not titolo or not scadenza:
        raise ValueError("Per un'azione correttiva servono titolo e scadenza.")
    azione = SecurityCorrectiveAction.objects.create(
        incident=incident, titolo=titolo[:255], scadenza=scadenza, responsabile=(responsabile or "").strip()[:150],
        note=(note or "").strip()[:4000], created_by=user if getattr(user, "pk", None) else None,
    )
    log(incident, "azione_correttiva", actor_name(user),
        f"Azione correttiva: {azione.titolo} (entro {scadenza:%d/%m/%Y}" + (f", {azione.responsabile}" if azione.responsabile else "") + ")",
        azione_id=azione.pk)
    return azione


@transaction.atomic
def segna_azione(azione, user, fatta=True):
    azione.fatta_il = timezone.now() if fatta else None
    azione.fatta_da = (user if getattr(user, "pk", None) else None) if fatta else None
    azione.save(update_fields=["fatta_il", "fatta_da"])
    log(azione.incident, "azione_correttiva", actor_name(user),
        f"Azione correttiva {'completata' if fatta else 'riaperta'}: {azione.titolo}", azione_id=azione.pk)
    return azione


def incidenti_senza_riesame(now=None, solo_da_avvisare=False):
    """Incidenti risolti/chiusi senza Lezioni apprese; con ``solo_da_avvisare`` solo quelli oltre N giorni."""
    now = now or timezone.now()
    giorni = soc_settings.value("iso.riesame.giorni")
    rows = SecurityIncident.objects.filter(status__in=STATI_CONCLUSI, riesame__isnull=True).order_by("resolved_at", "id")
    out = []
    for incident in rows:
        riferimento = incident.resolved_at or incident.updated_at
        if solo_da_avvisare and riferimento > now - timedelta(days=giorni):
            continue
        out.append(incident)
    return out


def azioni_scadute(oggi=None):
    oggi = oggi or timezone.localdate()
    return list(SecurityCorrectiveAction.objects.filter(fatta_il__isnull=True, scadenza__lt=oggi).select_related("incident"))


def azioni_in_scadenza(oggi=None, giorni=3):
    oggi = oggi or timezone.localdate()
    return list(SecurityCorrectiveAction.objects.filter(
        fatta_il__isnull=True, scadenza__gte=oggi, scadenza__lte=oggi + timedelta(days=giorni)).select_related("incident"))
