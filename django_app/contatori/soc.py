"""Apparati di rete che smettono di rispondere: eventi per il SOC.

Firewall, switch, server, storage, UPS e videoregistratori sono infrastruttura: se
cadono, il SOC deve saperlo come sa di un backup fallito. Dopo ``soglia``
interrogazioni consecutive senza risposta (default 2, cioe' circa 10 minuti) nasce
l'evento ``apparato_irraggiungibile``; alla prima risposta dopo la caduta nasce
``apparato_raggiungibile``, che chiude l'alert. Gli eventi passano dal motore regole
del SOC come tutti gli altri (soppressioni, alert, notifiche).

Stampanti, telecamere, lettori e sensori restano nel solo monitor di Contatori IT.
Un apparato mai verificato (bozza del wizard) non genera eventi: e' un problema di
configurazione, non una caduta.
"""
from __future__ import annotations

import logging

from django.urls import reverse
from django.utils import timezone

from .models import DispositivoSNMP

logger = logging.getLogger(__name__)

FONTE_SOC = "Contatori IT · apparati di rete"
EVENTO_GIU = "apparato_irraggiungibile"
EVENTO_SU = "apparato_raggiungibile"

CATEGORIE_SOC = (
    DispositivoSNMP.Categoria.FIREWALL,
    DispositivoSNMP.Categoria.RETE,
    DispositivoSNMP.Categoria.SERVER,
    DispositivoSNMP.Categoria.STORAGE,
    DispositivoSNMP.Categoria.UPS,
    DispositivoSNMP.Categoria.TVCC_NVR,
)


def _impostazione(chiave, default):
    try:
        from security.services import soc_settings

        return soc_settings.value(chiave)
    except Exception:  # noqa: BLE001 - SOC non configurato: si usa il default
        return default


def soglia_controlli() -> int:
    try:
        return max(1, int(_impostazione("apparati.irraggiungibile.controlli", 2)))
    except (TypeError, ValueError):
        return 2


def _fonte(crea=True):
    from security.models import SecuritySource, SourceType

    if not crea:
        return SecuritySource.objects.filter(name=FONTE_SOC).first()
    fonte, _ = SecuritySource.objects.get_or_create(
        name=FONTE_SOC, defaults={"source_type": SourceType.API, "vendor": "novicrom"})
    return fonte


def dedup_irraggiungibile(dispositivo, crea_fonte=True) -> str:
    """Impronta dell'alert di caduta: una per apparato (si riapre se ricade dopo la chiusura)."""
    from security.services.dedup import make_hash

    fonte = _fonte(crea=crea_fonte)
    if fonte is None:
        return ""
    return make_hash(fonte.pk, EVENTO_GIU, dispositivo.pk)


def transizione(dispositivo) -> str:
    """``"giu"``, ``"su"`` o ``""`` guardando le ultime interrogazioni salvate.

    Un'interrogazione «senza risposta» e' una rilevazione con ``errore`` (timeout,
    credenziali rifiutate…); una sonda fuori soglia non e' una caduta.
    """
    n = soglia_controlli()
    errori = list(dispositivo.rilevazioni.order_by("-rilevata_il", "-pk").values_list("errore", flat=True)[:n + 1])
    giu = [bool(e) for e in errori]
    if len(giu) >= n and all(giu[:n]) and (len(giu) == n or not giu[n]):
        return "giu"
    if len(giu) > n and not giu[0] and all(giu[1:n + 1]):
        return "su"
    return ""


def valuta(dispositivo) -> object | None:
    """Chiamato dopo ogni interrogazione: crea l'evento SOC se l'apparato e' appena caduto o tornato."""
    if dispositivo.categoria not in CATEGORIE_SOC or not dispositivo.verificato:
        return None
    if not _impostazione("apparati.irraggiungibile.attivo", True):
        return None
    try:
        verso = transizione(dispositivo)
        return _crea_evento(dispositivo, verso) if verso else None
    except Exception:  # noqa: BLE001 - il polling non si ferma per il SOC
        logger.exception("Evento SOC non creato per il dispositivo %s", dispositivo.pk)
        return None


def _crea_evento(dispositivo, verso):
    from security.models import SecurityEventRecord, Severity
    from security.services.dedup import make_hash

    fonte = _fonte()
    dedup = make_hash(fonte.pk, EVENTO_GIU, dispositivo.pk)
    ora = timezone.now()
    tipo = EVENTO_GIU if verso == "giu" else EVENTO_SU
    severita = Severity.HIGH if dispositivo.categoria == DispositivoSNMP.Categoria.FIREWALL else Severity.WARNING
    asset = dispositivo.asset
    payload = {
        "apparato": dispositivo.nome,
        "categoria": dispositivo.get_categoria_display(),
        "host": dispositivo.host,
        "errore": dispositivo.snmp_ultimo_errore[:300] if verso == "giu" else "",
        "controlli_senza_risposta": soglia_controlli(),
        "url": reverse("contatori:snmp_dispositivo", args=[dispositivo.pk]),
        "asset_tag": asset.asset_tag if asset else "",
        "asset_url": reverse("assets:asset_view", args=[asset.pk]) if asset else "",
        "alert_candidate": verso == "giu",
    }
    return SecurityEventRecord.objects.create(
        source=fonte, event_type=tipo, occurred_at=ora,
        severity=severita if verso == "giu" else Severity.INFO,
        # Impronte diverse: una soppressione appresa sulla caduta non deve inghiottire il ripristino.
        fingerprint=make_hash(fonte.pk, tipo, dispositivo.pk), dedup_hash=dedup, payload=payload,
    )


def alert_aperti_irraggiungibili() -> int:
    from security.models import SecurityAlert
    from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

    fonte = _fonte(crea=False)
    if fonte is None:
        return 0
    return SecurityAlert.objects.filter(source=fonte, status__in=ACTIVE_ALERT_STATUSES).count()
