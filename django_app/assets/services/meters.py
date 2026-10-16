"""Letture dei contatori asset (ore, km, cicli): una sola porta d'ingresso.

Che arrivi dal manutentore (scheda asset, pagina del QR), dal collector OPC UA
delle CNC o da un import, ogni lettura passa da ``record_meter_reading``:

* lock sulla riga del contatore (due letture contemporanee non si pestano);
* un valore **in calo** e' rifiutato, salvo azzeramento dichiarato (``is_reset``)
  con nota obbligatoria: e' la difesa dal vecchio difetto della base a zero
  (vedi il comando ``report_origin_proxy_damage``);
* una lettura **piu' vecchia** dell'ultima registrata viene ignorata, cosi' un
  collector che reinvia lo stesso lotto non cambia nulla (idempotenza);
* aggiorna valore, momento della lettura e provenienza del contatore.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from ..models import AssetMeter, AssetMeterHistory


class MeterReadingError(ValueError):
    """Lettura non registrata (messaggio per l'utente)."""


class MeterReadingRejected(MeterReadingError):
    """Valore non accettabile (in calo senza azzeramento, negativo, non numerico)."""


class MeterReadingOlder(MeterReadingError):
    """Lettura piu' vecchia (o uguale) dell'ultima gia' registrata: ignorata."""


def parse_meter_value(raw) -> Decimal:
    if isinstance(raw, Decimal):
        value = raw
    else:
        try:
            value = Decimal(str(raw).strip().replace(",", "."))
        except (InvalidOperation, AttributeError):
            raise MeterReadingRejected("Valore non valido: serve un numero.") from None
    if not value.is_finite():
        raise MeterReadingRejected("Valore non valido: serve un numero.")
    if value < 0:
        raise MeterReadingRejected("Il valore del contatore non puo' essere negativo.")
    return value.quantize(Decimal("0.01"))


def record_meter_reading(
    meter: AssetMeter,
    value,
    *,
    read_at: datetime | None,
    source: str,
    user=None,
    is_reset: bool = False,
    note: str = "",
) -> AssetMeterHistory:
    """Registra una lettura e ritorna la riga di storico creata.

    Solleva ``MeterReadingRejected`` (valore non accettabile) o
    ``MeterReadingOlder`` (lettura superata da una piu' recente).
    """
    value = parse_meter_value(value)
    read_at = read_at or timezone.now()
    if timezone.is_naive(read_at):
        read_at = timezone.make_aware(read_at)
    if read_at > timezone.now() + timedelta(minutes=10):
        raise MeterReadingRejected("La lettura e' nel futuro.")
    note = (note or "").strip()
    if source not in dict(AssetMeter.SOURCE_CHOICES):
        source = AssetMeter.SOURCE_MANUAL

    with transaction.atomic():
        locked = AssetMeter.objects.select_for_update().get(pk=meter.pk)
        if locked.read_at is not None and read_at <= locked.read_at:
            raise MeterReadingOlder(
                f"Lettura del {timezone.localtime(read_at):%d/%m/%Y %H:%M} ignorata: "
                f"ce n'e' gia' una del {timezone.localtime(locked.read_at):%d/%m/%Y %H:%M}."
            )
        old_value = locked.current_value
        if value < old_value:
            if not is_reset:
                raise MeterReadingRejected(
                    f"Il contatore non puo' scendere ({old_value} → {value}). "
                    "Se e' stato azzerato o sostituito, segnalo come azzeramento con una nota."
                )
            if not note:
                raise MeterReadingRejected("Per un azzeramento serve una nota che lo spieghi.")
        authenticated = bool(getattr(user, "is_authenticated", False))
        locked.current_value = value
        locked.read_at = read_at
        locked.source = source
        update_fields = ["current_value", "read_at", "source", "updated_at"]
        if authenticated:
            locked.updated_by = user
            update_fields.append("updated_by")
        locked.save(update_fields=update_fields)
        history = AssetMeterHistory.objects.create(
            meter=locked,
            old_value=old_value,
            new_value=value,
            recorded_by=user if authenticated else None,
            read_at=read_at,
            source=source,
            is_reset=bool(is_reset),
            note=note,
        )
    # L'oggetto del chiamante riflette lo stato salvato.
    meter.current_value = locked.current_value
    meter.read_at = locked.read_at
    meter.source = locked.source
    return history


@dataclass(frozen=True)
class DailyRate:
    per_day: Decimal | None
    reason: str = ""


def daily_rate(meter: AssetMeter, *, days: int = 30) -> DailyRate:
    """Consumo medio giornaliero dalle letture degli ultimi ``days`` giorni.

    Serve almeno due letture distinte nel periodo e nessun azzeramento in mezzo;
    altrimenti la data non si stima (meglio dirlo che inventarla).
    """
    since = timezone.now() - timedelta(days=days)
    rows = list(
        AssetMeterHistory.objects.filter(meter=meter, read_at__gte=since)
        .order_by("read_at", "id")
        .values("read_at", "new_value", "is_reset")
    )
    if any(row["is_reset"] for row in rows):
        rows = rows[[i for i, row in enumerate(rows) if row["is_reset"]][-1]:]
    if len(rows) < 2:
        return DailyRate(None, "storico insufficiente")
    first, last = rows[0], rows[-1]
    elapsed_days = Decimal(str((last["read_at"] - first["read_at"]).total_seconds() / 86400))
    if elapsed_days <= 0:
        return DailyRate(None, "storico insufficiente")
    delta = Decimal(last["new_value"]) - Decimal(first["new_value"])
    if delta <= 0:
        return DailyRate(None, "contatore fermo")
    return DailyRate((delta / elapsed_days).quantize(Decimal("0.01")))
