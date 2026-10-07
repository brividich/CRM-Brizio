"""Service layer per il calcolo delle scadenze formazione.

Il calcolo vero e' in ``services.requisiti`` (motore unico) e la scrittura in
``services.scadenze``: qui restano la regola di stato ``_compute_stato`` e
``refresh_deadlines`` per i chiamanti storici.
"""
from __future__ import annotations

from datetime import date


def _compute_stato(
    data_scadenza: date | None,
    validita_mesi: int,
    today: date,
) -> tuple[str, int | None]:
    """Ritorna (stato_scadenza, giorni_alla_scadenza).

    Decide la scadenza scritta sull'attestato, non la validita' attuale del
    corso: un corso portato a «una tantum» (validita' 0) dopo che gli attestati
    erano stati emessi con scadenza li rendeva eterni (in prod 177 attestati,
    73 gia' scaduti mostrati validi). ``validita_mesi`` resta per compatibilita'.
    """
    if data_scadenza is None:
        return "UNA_TANTUM", None
    giorni = (data_scadenza - today).days
    if giorni < 0:
        return "SCADUTO", giorni
    if giorni <= 30:
        return "IN_SCADENZA_30", giorni
    if giorni <= 90:
        return "IN_SCADENZA_90", giorni
    return "VALIDO", giorni


def refresh_deadlines(
    legacy_id: int | None = None,
    corso_id: int | None = None,
) -> int:
    """Ricalcola TrainingDeadline con il motore unico dei requisiti.

    Delegato a :func:`anagrafica.services.scadenze.ricalcola_formazione`: requisiti
    da mansione, fattori di rischio, area, ruoli, regole in vigore e processi,
    stato alla data, righe non piu' valide cancellate. Con ``legacy_id`` si
    ricalcola solo quella persona; ``corso_id`` da solo ricalcola tutti (un corso
    tocca le persone di piu' fonti, ricalcolarle tutte e' l'unico modo corretto).
    Restituisce il numero di righe valide dopo il ricalcolo.
    """
    from .scadenze import ricalcola_formazione  # noqa: PLC0415

    esito = ricalcola_formazione([legacy_id] if legacy_id is not None else None)
    return esito["righe"]
