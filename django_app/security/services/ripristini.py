"""Prove di ripristino dei backup (ISO 27001 8.13).

Registro delle prove (``BackupRestoreTest``): data, sistema, cosa è stato ripristinato, esito,
durata, chi, note, allegato. La cadenza attesa (``iso.ripristini.giorni``, default 90) vale
per tutto il parco: l'ultima prova riuscita più vecchia della cadenza è «in ritardo» e, se gli
avvisi sono accesi, parte un promemoria. Una prova **fallita** crea un evento
``backup_restore_test_failed`` sulla sorgente «Prove di ripristino» e il motore delle regole
apre un alert alto del SOC: un ripristino che non funziona è un backup che non c'è.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from security.models import BackupRestoreTest, SecurityEventRecord, SecuritySource, Severity, SourceType
from security.services import soc_settings
from security.services.dedup import make_hash

SOURCE_NAME = "Prove di ripristino"
EVENT_FAILED = "backup_restore_test_failed"


def source():
    src, _ = SecuritySource.objects.get_or_create(name=SOURCE_NAME, defaults={"source_type": SourceType.MANUAL, "vendor": "hub"})
    return src


def cadenza_giorni() -> int:
    return soc_settings.value("iso.ripristini.giorni")


def ultima_prova():
    return BackupRestoreTest.objects.order_by("-data", "-id").first()


def ultima_riuscita():
    return BackupRestoreTest.objects.filter(esito=BackupRestoreTest.ESITO_OK).order_by("-data", "-id").first()


def stato(oggi=None) -> dict:
    """Ultima prova, ultima riuscita, scadenza della prossima e se siamo in ritardo."""
    oggi = oggi or timezone.localdate()
    giorni = cadenza_giorni()
    ultima = ultima_prova()
    ok = ultima_riuscita()
    prossima = (ok.data + timedelta(days=giorni)) if ok else None
    return {
        "ultima": ultima,
        "ultima_riuscita": ok,
        "cadenza_giorni": giorni,
        "prossima_entro": prossima,
        "in_ritardo": prossima is None or prossima < oggi,
        "giorni_ritardo": (oggi - prossima).days if prossima and prossima < oggi else 0,
    }


def registra(user, **campi):
    """Salva la prova; se fallita, scrive l'evento che apre l'alert del SOC."""
    prova = BackupRestoreTest.objects.create(created_by=user if getattr(user, "pk", None) else None, **campi)
    if prova.esito == BackupRestoreTest.ESITO_KO:
        prova.alert = _alert_prova_fallita(prova)
        if prova.alert:
            prova.save(update_fields=["alert"])
    return prova


def _alert_prova_fallita(prova):
    from security.services.rule_engine import evaluate_event

    src = source()
    dedup = make_hash(src.pk, EVENT_FAILED, prova.pk)
    event = SecurityEventRecord.objects.create(
        source=src, event_type=EVENT_FAILED, severity=Severity.HIGH, occurred_at=timezone.now(),
        fingerprint=dedup, dedup_hash=dedup,
        payload={
            "prova_id": prova.pk, "data": prova.data.isoformat(), "sistema": prova.sistema, "job": prova.job,
            "cosa_ripristinato": prova.cosa_ripristinato[:500], "eseguito_da": prova.eseguito_da, "note": prova.note[:500],
        },
    )
    evaluate_event(event)
    event.refresh_from_db()
    return event.alerts.order_by("-id").first()


def riepilogo(dal, al) -> dict:
    s = stato()
    periodo = BackupRestoreTest.objects.filter(data__gte=dal, data__lte=al)
    return {
        "ultimo_test": s["ultima"].data if s["ultima"] else None,
        "esito_ultimo": s["ultima"].esito if s["ultima"] else None,
        "in_ritardo": s["in_ritardo"],
        "test_periodo": periodo.count(),
        "falliti_periodo": periodo.filter(esito=BackupRestoreTest.ESITO_KO).count(),
    }
