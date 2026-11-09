"""Soppressioni in scadenza: promemoria prima che una regola di soppressione smetta di valere.

Stesso schema delle accettazioni del rischio (``accettazione_rischio.controlla_scadenze``):
``soppressione.scadenza.promemoria_giorni`` prima di ``expires_at`` il ciclo del SOC crea
l'evento ``soppressione_in_scadenza``; il motore delle regole ne fa un alert di attenzione
(se ``soppressione.scadenza.alert`` è acceso) che arriva sui canali come ogni alert nuovo.
Una volta sola per scadenza: ``promemoria_il`` sulla regola e il dedup dell'evento su
(regola, scadenza). Se la scadenza viene spostata in avanti il promemoria riparte.
Ogni promemoria resta nell'audit sigillato (``traccia``).
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from security.models import SecurityAlertSuppressionRule, SecurityEventRecord, SecuritySource, Severity, SourceType
from security.services import soc_settings, traccia
from security.services.dedup import make_hash

SOURCE_NAME = "Soppressioni"
EVENT_IN_SCADENZA = "soppressione_in_scadenza"


def giorni() -> int:
    """Soglia unica: promemoria del ciclo e filtro «In scadenza» della pagina Soppressioni."""
    return soc_settings.value("soppressione.scadenza.promemoria_giorni")


def attive_q(now=None):
    now = now or timezone.now()
    return Q(is_active=True) & (Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def in_scadenza_q(now=None):
    """Soppressioni attive che scadono entro la soglia: stessa definizione per pagina, contatore e promemoria."""
    now = now or timezone.now()
    return attive_q(now) & Q(expires_at__lte=now + timedelta(days=giorni()))


def source():
    src, _ = SecuritySource.objects.get_or_create(name=SOURCE_NAME, defaults={"source_type": SourceType.MANUAL, "vendor": "hub"})
    return src


def _da_avvisare(rule, anticipo):
    """Nessun promemoria per questa scadenza: mai mandato, o mandato per una scadenza precedente."""
    return rule.promemoria_il is None or rule.promemoria_il < rule.expires_at - anticipo


def controlla_scadenze(now=None):
    """Un evento per ogni soppressione attiva che scade entro la soglia, una volta per scadenza. Torna quanti."""
    now = now or timezone.now()
    anticipo = timedelta(days=giorni())
    src = None
    fatti = 0
    for rule in SecurityAlertSuppressionRule.objects.filter(in_scadenza_q(now)).select_related("source"):
        if not _da_avvisare(rule, anticipo):
            continue
        src = src or source()
        dedup = make_hash(src.pk, EVENT_IN_SCADENZA, rule.pk, rule.expires_at.isoformat())
        event = None
        if not SecurityEventRecord.objects.filter(source=src, event_type=EVENT_IN_SCADENZA, dedup_hash=dedup).exists():
            restano = max(0, (timezone.localtime(rule.expires_at).date() - timezone.localtime(now).date()).days)
            event = SecurityEventRecord.objects.create(
                source=src, event_type=EVENT_IN_SCADENZA, severity=Severity.WARNING, occurred_at=now,
                fingerprint=dedup, dedup_hash=dedup,
                payload={
                    "regola_id": rule.pk, "regola": rule.name[:160], "appresa": rule.is_learned,
                    "scadenza": timezone.localtime(rule.expires_at).date().isoformat(), "giorni": restano,
                    "sorgente": rule.source.name if rule.source_id else "", "tipo_evento": rule.event_type,
                    "volte_applicata": rule.hit_count, "alert_candidate": True,
                },
            )
        rule.promemoria_il = now
        rule.save(update_fields=["promemoria_il"])
        traccia.registra(traccia.SOPPRESSIONE_IN_SCADENZA, {
            "regola_id": rule.pk, "regola": rule.name, "scadenza": rule.expires_at, "evento_id": event.pk if event else None,
        }, oggetto=rule)
        fatti += 1
    return fatti


def titolo_evento(payload):
    giorni_restanti = payload.get("giorni")
    quando = "oggi" if giorni_restanti == 0 else ("domani" if giorni_restanti == 1 else f"fra {giorni_restanti} giorni")
    tipo = "appresa" if payload.get("appresa") else "manuale"
    return f"Soppressione {tipo} in scadenza {quando}: {payload.get('regola')}"[:255]
