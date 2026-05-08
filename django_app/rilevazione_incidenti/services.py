from __future__ import annotations

from collections import defaultdict
from datetime import date

from django.utils import timezone

from core.legacy_anagrafica import fetch_anagrafica_rows

from .models import RilevazioneIncidente, TipoEventoSicurezza, normalize_tipo_evento

EVENT_TYPE_LABELS = {
    TipoEventoSicurezza.UNSAFE_CONDITION: "Unsafe condition",
    TipoEventoSicurezza.NEAR_MISS: "Near miss",
    TipoEventoSicurezza.INCIDENTE: "Incidente",
}


def event_type_label(value: str) -> str:
    return EVENT_TYPE_LABELS.get(normalize_tipo_evento(value), "Unsafe condition")


def active_headcount() -> int:
    try:
        rows = fetch_anagrafica_rows(deduplicate=True)
    except Exception:
        return 0
    return sum(
        1 for row in rows
        if row.get("id") and (row.get("attivo") is None or bool(row.get("attivo")))
    )


def _month_keys(today: date, months: int = 12) -> list[tuple[int, int]]:
    keys: list[tuple[int, int]] = []
    year = today.year
    month = today.month
    for offset in range(months - 1, -1, -1):
        y = year
        m = month - offset
        while m <= 0:
            y -= 1
            m += 12
        keys.append((y, m))
    return keys


def get_safety_kpis(today: date | None = None) -> dict:
    today = today or timezone.localdate()
    year_start = date(today.year, 1, 1)
    next_year = date(today.year + 1, 1, 1)
    qs_year = RilevazioneIncidente.objects.filter(
        data_segnalazione__date__gte=year_start,
        data_segnalazione__date__lt=next_year,
    )

    counts = {
        TipoEventoSicurezza.UNSAFE_CONDITION: 0,
        TipoEventoSicurezza.NEAR_MISS: 0,
        TipoEventoSicurezza.INCIDENTE: 0,
    }
    for evento in qs_year.only("tipo_evento", "tipologia_scheda"):
        counts[normalize_tipo_evento(evento.tipo_evento or evento.tipologia_scheda)] += 1

    headcount = active_headcount()
    annual_hours = headcount * 2000
    incidenti = counts[TipoEventoSicurezza.INCIDENTE]
    trir = round((incidenti * 200000) / annual_hours, 2) if annual_hours else None

    last_incident = (
        RilevazioneIncidente.objects.filter(tipo_evento=TipoEventoSicurezza.INCIDENTE, data_segnalazione__isnull=False)
        .order_by("-data_segnalazione")
        .values_list("data_segnalazione", flat=True)
        .first()
    )
    giorni_senza_infortuni = None
    if last_incident:
        giorni_senza_infortuni = (today - timezone.localdate(last_incident)).days

    month_counts: dict[tuple[int, int], int] = defaultdict(int)
    first_month = _month_keys(today, 12)[0]
    first_day = date(first_month[0], first_month[1], 1)
    for evento in RilevazioneIncidente.objects.filter(data_segnalazione__date__gte=first_day).only("data_segnalazione"):
        if evento.data_segnalazione:
            d = timezone.localdate(evento.data_segnalazione)
            month_counts[(d.year, d.month)] += 1
    trend = [
        {
            "label": f"{month:02d}/{str(year)[2:]}",
            "count": month_counts[(year, month)],
        }
        for year, month in _month_keys(today, 12)
    ]

    return {
        "year": today.year,
        "headcount": headcount,
        "trir": trir,
        "giorni_senza_infortuni": giorni_senza_infortuni,
        "unsafe_condition": counts[TipoEventoSicurezza.UNSAFE_CONDITION],
        "near_miss": counts[TipoEventoSicurezza.NEAR_MISS],
        "incidenti": incidenti,
        "totale": sum(counts.values()),
        "trend": trend,
    }
