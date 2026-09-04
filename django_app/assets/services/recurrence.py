"""Motore di periodicita' *solo temporale* del nuovo dominio manutenzione.

Nessuna soglia a ore/km/cicli: il portale non ha letture di contatore attendibili,
e una scadenza calcolata su un contatore fermo e' una scadenza falsa presentata
come verde. Qui si ragiona solo a calendario.

La ricorrenza vive su campi normalizzati di ``MaintenancePlanAssignment``
(frequency/interval/weekday/week_of_month/day_of_month/month_of_year) invece che in
un JSON: si legge in SQL, si filtra, e non introduce lookup JSON su SQL Server.

Due ancoraggi, ed e' la differenza che regge tutto il modello:

``FROM_COMPLETION``
    ``next_due = data di esecuzione + ricorrenza``. Manutenzione ordinaria: se il
    cambio olio si fa il 20 invece del 10, i 30 giorni ripartono dal 20.

``FIXED_CALENDAR``
    ``next_due = scadenza teorica + ricorrenza``. Scadenza amministrativa: una
    polizza rinnovata in ritardo scade lo stesso giorno dell'anno dopo, altrimenti
    dodici rinnovi in ritardo spostano la scadenza di mesi senza che si veda.
"""

from __future__ import annotations

import calendar
from datetime import date

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError

FREQ_DAYS = "DAYS"
FREQ_WEEKS = "WEEKS"
FREQ_MONTHS = "MONTHS"
FREQ_YEARS = "YEARS"

ANCHOR_FROM_COMPLETION = "FROM_COMPLETION"
ANCHOR_FIXED_CALENDAR = "FIXED_CALENDAR"

LAST = -1

_WEEKDAY_LABELS = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]
_MONTH_LABELS = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]
_WEEK_LABELS = {1: "primo", 2: "secondo", 3: "terzo", 4: "quarto", LAST: "ultimo"}


class RecurrenceError(ValueError):
    """Ricorrenza non rappresentabile (interval nullo, giorno fuori range...)."""


# ---------------------------------------------------------------------------
# Lettura della ricorrenza da un oggetto (assignment o qualsiasi struttura con
# gli stessi attributi: serve ai form, che validano prima di avere l'istanza).
# ---------------------------------------------------------------------------

def recurrence_spec(source) -> dict:
    """Estrae la ricorrenza da un assignment (o da un oggetto con gli stessi campi)."""
    get = source.get if isinstance(source, dict) else lambda name, default=None: getattr(source, name, default)
    return {
        "frequency": (get("frequency", FREQ_DAYS) or FREQ_DAYS),
        "interval": int(get("interval", 1) or 1),
        "weekday": _as_int_or_none(get("weekday", None)),
        "week_of_month": _as_int_or_none(get("week_of_month", None)),
        "day_of_month": _as_int_or_none(get("day_of_month", None)),
        "month_of_year": _as_int_or_none(get("month_of_year", None)),
    }


def _as_int_or_none(value):
    if value in (None, ""):
        return None
    return int(value)


def validate_recurrence_fields(source) -> dict:
    """Valida la ricorrenza e la restituisce normalizzata.

    Solleva ``ValidationError`` con il campo colpevole, cosi' il messaggio arriva
    accanto all'input sbagliato invece che in cima al form.
    """
    spec = recurrence_spec(source)

    if spec["frequency"] not in (FREQ_DAYS, FREQ_WEEKS, FREQ_MONTHS, FREQ_YEARS):
        raise ValidationError({"frequency": "Frequenza non valida."})
    if spec["interval"] < 1:
        raise ValidationError({"interval": "L'intervallo deve essere almeno 1."})

    weekday, week_of_month = spec["weekday"], spec["week_of_month"]
    day_of_month, month_of_year = spec["day_of_month"], spec["month_of_year"]

    if weekday is not None and not 0 <= weekday <= 6:
        raise ValidationError({"weekday": "Il giorno della settimana va da 0 (lunedi) a 6 (domenica)."})
    if week_of_month is not None and week_of_month not in (1, 2, 3, 4, LAST):
        raise ValidationError({"week_of_month": "La settimana del mese va da 1 a 4, oppure -1 per l'ultima."})
    if day_of_month is not None and not (day_of_month == LAST or 1 <= day_of_month <= 31):
        raise ValidationError({"day_of_month": "Il giorno del mese va da 1 a 31, oppure -1 per l'ultimo."})
    if month_of_year is not None and not 1 <= month_of_year <= 12:
        raise ValidationError({"month_of_year": "Il mese va da 1 a 12."})

    if (weekday is None) != (week_of_month is None):
        raise ValidationError(
            {"week_of_month": "Per una ricorrenza tipo 'primo lunedi del mese' servono sia la settimana sia il giorno."}
        )
    if weekday is not None and day_of_month is not None:
        raise ValidationError(
            {"day_of_month": "Scegli o il giorno fisso del mese o il giorno della settimana, non entrambi."}
        )
    if spec["frequency"] in (FREQ_DAYS, FREQ_WEEKS) and (
        week_of_month is not None or day_of_month is not None or month_of_year is not None
    ):
        raise ValidationError(
            {"frequency": "Giorno del mese, settimana del mese e mese valgono solo per ricorrenze mensili o annuali."}
        )
    if spec["frequency"] == FREQ_MONTHS and month_of_year is not None:
        raise ValidationError({"month_of_year": "Il mese fisso vale solo per le ricorrenze annuali."})
    if spec["frequency"] == FREQ_YEARS and month_of_year is None and (day_of_month is not None or weekday is not None):
        raise ValidationError({"month_of_year": "Per una ricorrenza annuale a data fissa indica anche il mese."})

    return spec


# ---------------------------------------------------------------------------
# Calcolo
# ---------------------------------------------------------------------------

def _last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _apply_day_of_month(value: date, day_of_month: int | None) -> date:
    if day_of_month is None:
        return value
    if day_of_month == LAST:
        return value.replace(day=_last_day_of_month(value.year, value.month))
    # Il 31 in un mese da 30 scivola all'ultimo giorno disponibile, non al mese dopo.
    return value.replace(day=min(day_of_month, _last_day_of_month(value.year, value.month)))


def _apply_weekday_in_month(value: date, weekday: int, week_of_month: int) -> date:
    """Ritorna la N-esima ricorrenza di ``weekday`` nel mese di ``value``."""
    if week_of_month == LAST:
        last_day = _last_day_of_month(value.year, value.month)
        candidate = value.replace(day=last_day)
        delta = (candidate.weekday() - weekday) % 7
        return candidate - relativedelta(days=delta)
    first = value.replace(day=1)
    delta = (weekday - first.weekday()) % 7
    day = 1 + delta + (week_of_month - 1) * 7
    last_day = _last_day_of_month(value.year, value.month)
    if day > last_day:
        # "Quinto lunedi" in un mese che non ce l'ha: si usa l'ultimo disponibile.
        day -= 7
    return value.replace(day=day)


def add_recurrence(spec_source, start: date) -> date:
    """Somma una ricorrenza a ``start`` e allinea il risultato al giorno richiesto."""
    spec = recurrence_spec(spec_source)
    frequency, interval = spec["frequency"], max(1, spec["interval"])

    if frequency == FREQ_DAYS:
        return start + relativedelta(days=interval)
    if frequency == FREQ_WEEKS:
        result = start + relativedelta(weeks=interval)
        if spec["weekday"] is not None:
            result -= relativedelta(days=(result.weekday() - spec["weekday"]) % 7)
        return result

    if frequency == FREQ_MONTHS:
        result = start + relativedelta(months=interval)
    elif frequency == FREQ_YEARS:
        result = start + relativedelta(years=interval)
        if spec["month_of_year"] is not None:
            result = result.replace(month=spec["month_of_year"], day=1)
    else:  # pragma: no cover - validate_recurrence_fields lo esclude
        raise RecurrenceError(f"Frequenza non gestita: {frequency}")

    if spec["weekday"] is not None and spec["week_of_month"] is not None:
        return _apply_weekday_in_month(result, spec["weekday"], spec["week_of_month"])
    return _apply_day_of_month(result, spec["day_of_month"])


def compute_next_due(
    spec_source,
    *,
    anchor: str,
    previous_due: date | None,
    completion_date: date | None,
) -> date | None:
    """Prossima scadenza dopo il completamento di un'occorrenza.

    ``FROM_COMPLETION`` parte dalla data reale di esecuzione, ``FIXED_CALENDAR``
    dalla scadenza teorica. Se manca la base di partenza dell'ancoraggio scelto si
    ripiega sull'altra: meglio una scadenza approssimata che nessuna scadenza.
    """
    if anchor == ANCHOR_FIXED_CALENDAR:
        base = previous_due or completion_date
    else:
        base = completion_date or previous_due
    if base is None:
        return None
    return add_recurrence(spec_source, base)


def first_due_date_for(spec_source, *, start_date: date | None, today: date) -> date:
    """Prima scadenza quando non esiste storico.

    Con una data di partenza nel passato non si crea una scadenza vecchia di anni:
    si avanza di ricorrenza in ricorrenza fino a raggiungere oggi. Il limite di
    giri e' una cintura di sicurezza contro ricorrenze degeneri.
    """
    if start_date is None:
        return today
    candidate = start_date
    for _ in range(2000):
        if candidate >= today:
            return candidate
        candidate = add_recurrence(spec_source, candidate)
    return candidate


# ---------------------------------------------------------------------------
# Descrizione leggibile (la UI non deve mai mostrare una cron expression)
# ---------------------------------------------------------------------------

def describe_recurrence(spec_source) -> str:
    spec = recurrence_spec(spec_source)
    frequency, interval = spec["frequency"], max(1, spec["interval"])
    weekday, week_of_month = spec["weekday"], spec["week_of_month"]
    day_of_month, month_of_year = spec["day_of_month"], spec["month_of_year"]

    if frequency == FREQ_DAYS:
        return "Ogni giorno" if interval == 1 else f"Ogni {interval} giorni"

    if frequency == FREQ_WEEKS:
        base = "Ogni settimana" if interval == 1 else f"Ogni {interval} settimane"
        if weekday is not None:
            return f"{base}, di {_WEEKDAY_LABELS[weekday]}"
        return base

    if frequency == FREQ_MONTHS:
        if interval == 3:
            base = "Ogni trimestre"
        elif interval == 6:
            base = "Ogni semestre"
        elif interval == 1:
            base = "Ogni mese"
        else:
            base = f"Ogni {interval} mesi"
        if weekday is not None and week_of_month is not None:
            return f"{base}, il {_WEEK_LABELS.get(week_of_month, '')} {_WEEKDAY_LABELS[weekday]}"
        if day_of_month == LAST:
            return f"{base}, l'ultimo giorno"
        if day_of_month is not None:
            return f"{base}, il giorno {day_of_month}"
        return base

    base = "Ogni anno" if interval == 1 else f"Ogni {interval} anni"
    if month_of_year is not None:
        month_label = _MONTH_LABELS[month_of_year - 1]
        if weekday is not None and week_of_month is not None:
            return f"{base}, il {_WEEK_LABELS.get(week_of_month, '')} {_WEEKDAY_LABELS[weekday]} di {month_label}"
        if day_of_month == LAST:
            return f"{base}, l'ultimo giorno di {month_label}"
        if day_of_month is not None:
            return f"{base}, il {day_of_month} {month_label}"
        return f"{base}, a {month_label}"
    return base


# Preset offerti dalla UI: l'utente sceglie una voce, non compila sei campi.
RECURRENCE_PRESETS = [
    ("weekly", "Ogni settimana", {"frequency": FREQ_WEEKS, "interval": 1}),
    ("biweekly", "Ogni 2 settimane", {"frequency": FREQ_WEEKS, "interval": 2}),
    ("monthly", "Ogni mese", {"frequency": FREQ_MONTHS, "interval": 1}),
    ("days_30", "Ogni 30 giorni", {"frequency": FREQ_DAYS, "interval": 30}),
    ("days_45", "Ogni 45 giorni", {"frequency": FREQ_DAYS, "interval": 45}),
    ("days_90", "Ogni 90 giorni", {"frequency": FREQ_DAYS, "interval": 90}),
    ("quarterly", "Ogni trimestre", {"frequency": FREQ_MONTHS, "interval": 3}),
    ("biannual", "Ogni semestre", {"frequency": FREQ_MONTHS, "interval": 6}),
    ("yearly", "Ogni anno", {"frequency": FREQ_YEARS, "interval": 1}),
    (
        "first_monday",
        "Primo lunedi del mese",
        {"frequency": FREQ_MONTHS, "interval": 1, "weekday": 0, "week_of_month": 1},
    ),
    (
        "second_monday",
        "Secondo lunedi del mese",
        {"frequency": FREQ_MONTHS, "interval": 1, "weekday": 0, "week_of_month": 2},
    ),
    (
        "last_day_month",
        "Ultimo giorno del mese",
        {"frequency": FREQ_MONTHS, "interval": 1, "day_of_month": LAST},
    ),
]
