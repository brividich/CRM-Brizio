"""Numerazioni progressive ``MAX()+1`` sicure sotto concorrenza (audit S8).

Due inserimenti contemporanei leggono lo stesso massimo e il secondo urta il
vincolo di unicità: invece di un errore 500 si ricalcola il numero e si riprova,
come già fa ``Project.kickoff_number``. Ogni tentativo gira in un savepoint, così
l'errore non compromette la transazione esterna.
"""
from __future__ import annotations

from typing import Callable, TypeVar

from django.db import IntegrityError, transaction

T = TypeVar("T")

DEFAULT_ATTEMPTS = 5


def save_with_next_number(
    assign_number: Callable[[], None],
    save: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    on_conflict: Callable[[], None] | None = None,
) -> T:
    """Assegna il numero, salva; su IntegrityError ricalcola e riprova.

    ``assign_number`` calcola e imposta il prossimo numero, ``save`` esegue il
    salvataggio e ne restituisce il risultato; ``on_conflict`` ripulisce lo
    stato dell'oggetto prima del nuovo tentativo.
    """
    last_error: IntegrityError | None = None
    for _ in range(max(1, attempts)):
        assign_number()
        try:
            with transaction.atomic():
                return save()
        except IntegrityError as exc:
            last_error = exc
            if on_conflict is not None:
                on_conflict()
    assert last_error is not None
    raise last_error
