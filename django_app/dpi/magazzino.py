"""Magazzino DPI: giacenza per modello come somma dei movimenti registrati."""
from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Sum

from .models import ModelloDPI, MovimentoMagazzinoDPI, RichiestaDPI

Tipo = MovimentoMagazzinoDPI.Tipo

STATO_ESAURITO = "esaurito"
STATO_SOTTO_SCORTA = "sotto"
STATO_OK = "ok"


def giacenza(modello_id: int) -> int:
    return int(MovimentoMagazzinoDPI.objects.filter(modello_id=modello_id).aggregate(t=Sum("quantita"))["t"] or 0)


def giacenze() -> dict[int, int]:
    rows = MovimentoMagazzinoDPI.objects.values("modello_id").annotate(t=Sum("quantita"))
    return {r["modello_id"]: int(r["t"] or 0) for r in rows}


def stato_scorta(qta: int, minima: int) -> str:
    if qta <= 0:
        return STATO_ESAURITO
    if minima and qta <= minima:
        return STATO_SOTTO_SCORTA
    return STATO_OK


def carica_ddt(modello: ModelloDPI, quantita: int, *, ddt_numero: str = "", data: date | None = None,
               fornitore: str = "", note: str = "", user=None) -> MovimentoMagazzinoDPI:
    if quantita <= 0:
        raise ValueError("La quantita' del carico deve essere positiva.")
    return MovimentoMagazzinoDPI.objects.create(
        modello=modello, tipo=Tipo.CARICO, quantita=quantita, data=data or date.today(),
        ddt_numero=ddt_numero[:60], fornitore=fornitore[:150], note=note[:300],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


@transaction.atomic
def imposta_giacenza(modello: ModelloDPI, nuova: int, *, note: str = "", user=None) -> MovimentoMagazzinoDPI | None:
    """Rettifica d'inventario: porta la giacenza a ``nuova`` registrando la differenza."""
    if nuova < 0:
        raise ValueError("La giacenza non puo' essere negativa.")
    delta = nuova - giacenza(modello.pk)
    if delta == 0:
        return None
    return MovimentoMagazzinoDPI.objects.create(
        modello=modello, tipo=Tipo.RETTIFICA, quantita=delta, note=(note or "Inventario")[:300],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


def scarica_per_consegna(richiesta: RichiestaDPI, data: date, *, user=None) -> tuple[MovimentoMagazzinoDPI | None, int | None]:
    """Scarica dal magazzino la quantita' consegnata. Idempotente per richiesta.

    Ritorna (movimento, giacenza_residua); (None, None) se la richiesta non ha un
    modello DPI (nulla da scaricare). La consegna non viene mai bloccata da una
    giacenza insufficiente: il chiamante segnala il residuo negativo."""
    if not richiesta.modello_dpi_id:
        return None, None
    movimento, created = MovimentoMagazzinoDPI.objects.get_or_create(
        richiesta=richiesta, tipo=Tipo.SCARICO,
        defaults={
            "modello_id": richiesta.modello_dpi_id, "quantita": -int(richiesta.quantita or 1), "data": data,
            "note": f"Consegna {richiesta.numero} - {richiesta.richiedente_nome}"[:300],
            "created_by": user if getattr(user, "is_authenticated", False) else None,
        },
    )
    return movimento, giacenza(richiesta.modello_dpi_id)
