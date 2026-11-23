"""Date lavorative per l'auto-approvazione "umanizzata" del MOD.133.

`festivi_it` calcola i festivi nazionali italiani (fissi + Pasquetta) senza dipendenze
esterne; `next_business_datetime` restituisce il primo giorno lavorativo dopo una data,
con un'ora casuale in orario ufficio. Calendario unico: patrono e chiusure da Assenze.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from core.calendario_it import festivi_tra, is_lavorativo, pasqua as _pasqua


def festivi_it(anno: int) -> set[date]:
    """Giorni non lavorativi dell'anno dal calendario unico del portale: festivi nazionali,
    patrono e chiusure aziendali (impostazioni di Assenze). La domenica di Pasqua resta fuori.
    """
    return festivi_tra(date(anno, 1, 1), date(anno, 12, 31)) - {_pasqua(anno)}


def _e_lavorativo(d: date) -> bool:
    return is_lavorativo(d, festivi_it(d.year))


def next_business_datetime(base: datetime) -> datetime:
    """Primo giorno lavorativo dopo `base`, con ora casuale in [9:00, 17:00).

    Salta i giorni non lavorativi del calendario unico (festivi, patrono, chiusure). Ritorna un
    `datetime` *aware* nella timezone corrente.
    """
    giorno = base.date() + timedelta(days=1)
    while not _e_lavorativo(giorno):
        giorno += timedelta(days=1)
    ora = time(hour=random.randint(9, 16), minute=random.randint(0, 59), second=random.randint(0, 59))
    return timezone.make_aware(datetime.combine(giorno, ora))
